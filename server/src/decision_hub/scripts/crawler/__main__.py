"""CLI entry point for the GitHub skills crawler.

Usage:
    DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler [OPTIONS]
"""

import argparse
import os
import sys
from collections.abc import Generator
from pathlib import Path

from loguru import logger

from decision_hub.scripts.crawler.checkpoint import Checkpoint
from decision_hub.scripts.crawler.models import CrawlStats, DiscoveredRepo, repo_to_dict

DEFAULT_CHECKPOINT_PATH = Path("crawl_checkpoint.json")
ALL_STRATEGIES = ["size", "path", "topic", "fork", "curated"]

_STRATEGY_LABELS: dict[str, str] = {
    "size": "File-size partitioning",
    "path": "Path-based search",
    "topic": "Topic-based discovery",
    "curated": "Curated list parsing",
    "fork": "Fork scanning",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover and publish GitHub skills through the Gauntlet pipeline.",
    )
    parser.add_argument(
        "--github-token",
        type=str,
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub PAT (reads from $GITHUB_TOKEN by default)",
    )
    parser.add_argument(
        "--max-skills",
        type=int,
        default=None,
        help="Stop after publishing this many skills (for testing)",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Decision Hub environment (default: dev)",
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=ALL_STRATEGIES,
        default=ALL_STRATEGIES,
        help="Subset of discovery strategies to run",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_CHECKPOINT_PATH,
        help="Checkpoint file path",
    )

    resume_group = parser.add_mutually_exclusive_group()
    resume_group.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing checkpoint (skip discovery)",
    )
    resume_group.add_argument(
        "--fresh",
        action="store_true",
        help="Delete checkpoint and start over",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run discovery only, print stats, do not process",
    )
    return parser.parse_args(argv)


def discover_batches(
    github_token: str | None,
    strategies: list[str],
    stats: CrawlStats,
) -> Generator[dict[str, DiscoveredRepo], None, None]:
    """Yield a batch of newly-discovered repos after each strategy completes.

    Each batch contains only repos not seen in previous batches, so the caller
    can start processing immediately without waiting for all strategies.
    """
    from decision_hub.scripts.crawler.discovery import (
        GitHubClient,
        parse_curated_lists,
        scan_forks,
        search_by_file_size,
        search_by_path,
        search_by_topic,
    )

    gh = GitHubClient(github_token)
    seen: set[str] = set()
    all_repos: dict[str, DiscoveredRepo] = {}

    # Fork scanning runs last because it depends on discovered repos
    ordered = [s for s in strategies if s != "fork"]
    if "fork" in strategies:
        ordered.append("fork")

    try:
        for name in ordered:
            logger.info("Discovery strategy: {}", _STRATEGY_LABELS.get(name, name))

            if name == "size":
                found = search_by_file_size(gh, stats)
            elif name == "path":
                found = search_by_path(gh, stats)
            elif name == "topic":
                found = search_by_topic(gh, stats)
            elif name == "curated":
                found = parse_curated_lists(gh, stats)
            elif name == "fork":
                top_repos = sorted(
                    all_repos.values(),
                    key=lambda r: r.stars,
                    reverse=True,
                )[:10]
                found = scan_forks(gh, [r.full_name for r in top_repos], stats)
            else:
                found = {}

            all_repos.update(found)

            # Yield only repos we haven't yielded before
            new_batch = {k: v for k, v in found.items() if k not in seen}
            seen.update(new_batch.keys())

            if new_batch:
                logger.info(
                    "Strategy '{}' found {} new repos ({} total)",
                    name,
                    len(new_batch),
                    len(all_repos),
                )
                yield new_batch
            else:
                logger.info("Strategy '{}' found 0 new repos", name)
    finally:
        gh.close()

    stats.repos_discovered = len(all_repos)


def _filter_changed_repos(
    repos: list[DiscoveredRepo],
    checkpoint: Checkpoint,
    github_token: str | None,
) -> list[DiscoveredRepo]:
    """Filter out repos whose HEAD SHA matches the checkpoint (unchanged).

    Uses the GitHub API to fetch current HEAD SHA for each previously-processed
    repo. Repos not in the checkpoint are always included.
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn

    from decision_hub.domain.tracker import fetch_latest_commit_sha

    changed: list[DiscoveredRepo] = []
    skipped = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TextColumn("{task.completed}/{task.total}"),
    ) as progress:
        task = progress.add_task("Checking for repo changes...", total=len(repos))

        for repo in repos:
            last_sha = checkpoint.get_last_sha(repo.full_name)
            if last_sha is not None:
                # Previously processed — check if HEAD changed
                parts = repo.full_name.split("/", 1)
                if len(parts) == 2:
                    try:
                        current_sha = fetch_latest_commit_sha(parts[0], parts[1], "HEAD", github_token)
                        if current_sha == last_sha:
                            skipped += 1
                            progress.advance(task)
                            continue
                    except Exception:
                        # If we can't check, process it anyway
                        pass
            changed.append(repo)
            progress.advance(task)

    if skipped:
        logger.info("{} repos unchanged since last crawl, skipping", skipped)
    # Process most-starred repos first so popular skills are indexed sooner
    changed.sort(key=lambda r: r.stars, reverse=True)
    return changed


def run_processing_phase(
    pending_repos: list[DiscoveredRepo],
    bot_user_id: str,
    github_token: str | None,
    checkpoint: Checkpoint,
    checkpoint_path: Path,
    max_skills: int | None,
    modal_app_name: str,
    stats: CrawlStats,
) -> bool:
    """Fan out repo processing to Modal containers.

    Returns True if max_skills cap was reached (caller should stop).
    """
    import modal
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    fn = modal.Function.from_name(modal_app_name, "crawl_process_repo")
    repo_dicts = [repo_to_dict(r) for r in pending_repos]

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn(
            "pub:{task.fields[pub]} fail:{task.fields[fail]} skip:{task.fields[skip]} quarantine:{task.fields[quar]}"
        ),
    ) as progress:
        task = progress.add_task(
            "Processing repos",
            total=len(repo_dicts),
            pub=stats.skills_published,
            fail=stats.skills_failed,
            skip=stats.skills_skipped,
            quar=stats.skills_quarantined,
        )

        for result in fn.map(
            repo_dicts,
            kwargs={"bot_user_id": bot_user_id, "github_token": github_token},
            return_exceptions=True,
        ):
            if isinstance(result, Exception):
                stats.errors.append(str(result)[:500])
                repo_name = "unknown"
                commit_sha = None
            else:
                stats.accumulate(result)
                repo_name = result.get("repo", "unknown")
                commit_sha = result.get("commit_sha")

            checkpoint.mark_processed(repo_name, checkpoint_path, commit_sha=commit_sha)
            progress.update(
                task,
                advance=1,
                pub=stats.skills_published,
                fail=stats.skills_failed,
                skip=stats.skills_skipped,
                quar=stats.skills_quarantined,
            )

            if max_skills is not None and stats.skills_published >= max_skills:
                logger.info("Reached --max-skills cap ({}), stopping", max_skills)
                checkpoint.flush(checkpoint_path)
                return True

    checkpoint.flush(checkpoint_path)
    return False


def run_crawler(args: argparse.Namespace) -> None:
    """Main crawler orchestrator.

    Interleaves discovery and processing: each strategy's results are
    processed via Modal immediately, so skills start publishing while
    discovery continues.
    """
    from decision_hub.logging import setup_logging
    from decision_hub.scripts.crawler.models import dict_to_repo
    from decision_hub.settings import create_settings

    os.environ.setdefault("DHUB_ENV", args.env)
    settings = create_settings(args.env)
    setup_logging(settings.log_level)

    if not args.github_token:
        logger.warning(
            "No GitHub token provided. Unauthenticated rate limit is 60 req/hr. "
            "Set $GITHUB_TOKEN or pass --github-token for higher limits."
        )

    checkpoint_path: Path = args.checkpoint

    # Handle --fresh
    if args.fresh and checkpoint_path.exists():
        checkpoint_path.unlink()
        logger.info("Deleted existing checkpoint: {}", checkpoint_path)

    # --resume: process remaining repos from a previous checkpoint
    if args.resume:
        if not checkpoint_path.exists():
            logger.error("No checkpoint file found at {}. Cannot resume.", checkpoint_path)
            sys.exit(1)
        checkpoint = Checkpoint.load(checkpoint_path)
        logger.info(
            "Resumed checkpoint: {} discovered, {} already processed",
            len(checkpoint.discovered_repos),
            len(checkpoint.processed_repos),
        )

        if args.dry_run:
            print(f"\nDiscovered {len(checkpoint.discovered_repos)} repos")
            print(f"Already processed: {len(checkpoint.processed_repos)}")
            print(f"Pending: {len(checkpoint.discovered_repos) - len(checkpoint.processed_repos)}")
            return

        all_repos = [dict_to_repo(d) for d in checkpoint.discovered_repos.values()]
        pending = _filter_changed_repos(all_repos, checkpoint, args.github_token)
        if not pending:
            logger.info("Nothing to process. All repos already handled.")
            return

        from decision_hub.infra.database import create_engine, upsert_user
        from decision_hub.scripts.crawler.processing import BOT_GITHUB_ID, BOT_USERNAME

        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            bot_user = upsert_user(conn, github_id=BOT_GITHUB_ID, username=BOT_USERNAME)
            conn.commit()

        stats = CrawlStats()
        run_processing_phase(
            pending_repos=pending,
            bot_user_id=str(bot_user.id),
            github_token=args.github_token,
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            max_skills=args.max_skills,
            modal_app_name=settings.modal_app_name,
            stats=stats,
        )
        _print_summary(stats)
        return

    # Streaming mode: discover a batch → process it → discover next batch
    checkpoint = Checkpoint.load(checkpoint_path) if checkpoint_path.exists() else Checkpoint()
    discovery_stats = CrawlStats()
    proc_stats = CrawlStats()
    bot_user_id: str | None = None

    for batch in discover_batches(args.github_token, args.strategies, discovery_stats):
        # Merge newly discovered repos into checkpoint
        for full_name, repo in batch.items():
            checkpoint.discovered_repos[full_name] = repo_to_dict(repo)
        checkpoint.save(checkpoint_path)

        if args.dry_run:
            logger.info("Dry-run: skipping processing of {} repos", len(batch))
            continue

        # Filter out already-processed / unchanged repos
        batch_repos = list(batch.values())
        pending = _filter_changed_repos(batch_repos, checkpoint, args.github_token)
        if not pending:
            continue

        # Lazy-init bot user on first batch that needs processing
        if bot_user_id is None:
            from decision_hub.infra.database import create_engine, upsert_user
            from decision_hub.scripts.crawler.processing import BOT_GITHUB_ID, BOT_USERNAME

            engine = create_engine(settings.database_url)
            with engine.connect() as conn:
                bot_user = upsert_user(conn, github_id=BOT_GITHUB_ID, username=BOT_USERNAME)
                conn.commit()
            bot_user_id = str(bot_user.id)

        logger.info("Processing batch: {} repos", len(pending))
        hit_cap = run_processing_phase(
            pending_repos=pending,
            bot_user_id=bot_user_id,
            github_token=args.github_token,
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            max_skills=args.max_skills,
            modal_app_name=settings.modal_app_name,
            stats=proc_stats,
        )
        if hit_cap:
            break

    if args.dry_run:
        print(f"\nDiscovered {len(checkpoint.discovered_repos)} repos")
        print(f"Already processed: {len(checkpoint.processed_repos)}")
        print(f"Pending: {len(checkpoint.discovered_repos) - len(checkpoint.processed_repos)}")
    else:
        _print_summary(proc_stats)


def _print_summary(stats: CrawlStats) -> None:
    print("\n--- Crawl Summary ---")
    print(f"Repos processed: {stats.repos_processed}")
    print(f"Skills published: {stats.skills_published}")
    print(f"Skills skipped:   {stats.skills_skipped}")
    print(f"Skills failed:    {stats.skills_failed}")
    print(f"Skills quarantined: {stats.skills_quarantined}")
    print(f"Orgs created:     {stats.orgs_created}")
    print(f"Metadata synced:  {stats.metadata_synced}")
    if stats.errors:
        print(f"Errors: {len(stats.errors)}")
        for err in stats.errors[:10]:
            print(f"  - {err}")


def main() -> None:
    args = parse_args()
    run_crawler(args)


if __name__ == "__main__":
    main()
