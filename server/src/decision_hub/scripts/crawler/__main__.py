"""CLI entry point for the GitHub skills crawler.

Usage:
    DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler [OPTIONS]
"""

import argparse
import os
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

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
        default=os.environ.get("DHUB_ENV", "dev"),
        help="Decision Hub environment (default: $DHUB_ENV or dev)",
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

    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing checkpoint (skip discovery)",
    )
    source_group.add_argument(
        "--fresh",
        action="store_true",
        help="Delete checkpoint and start over",
    )
    source_group.add_argument(
        "--repos",
        nargs="+",
        metavar="REPO",
        help=(
            "Process specific repos instead of running discovery. "
            "Accepts owner/repo, https://github.com/owner/repo, "
            "or git@github.com:owner/repo.git"
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run discovery only, print stats, do not process",
    )
    parser.add_argument(
        "--no-set-tracker",
        dest="set_tracker",
        action="store_false",
        default=True,
        help="Skip creating trackers for published skills (default: trackers are created)",
    )
    parser.add_argument(
        "--trusted-only",
        action="store_true",
        default=False,
        help="Only search TRUSTED_ORGS, skip all other discovery strategies",
    )
    return parser.parse_args(argv)


def discover_batches(
    github_token: str | None,
    strategies: list[str],
    stats: CrawlStats,
) -> Generator[dict[str, DiscoveredRepo], None, None]:
    """Yield small batches of newly-discovered repos as they are found.

    Each strategy is a generator that yields sub-batches (e.g. one per size
    range, one per topic). This function deduplicates across batches and yields
    immediately so the caller can start processing without waiting for an
    entire strategy to complete.
    """
    from decision_hub.scripts.crawler.discovery import (
        GitHubClient,
        parse_curated_lists,
        scan_forks,
        search_by_file_size,
        search_by_path,
        search_by_topic,
        search_trusted_orgs,
        tag_trusted_repos,
    )

    gh = GitHubClient(github_token)
    seen: set[str] = set()
    all_repos: dict[str, DiscoveredRepo] = {}

    def _yield_sub_batches(
        sub_batches: Generator[dict[str, DiscoveredRepo], None, None],
    ) -> Generator[dict[str, DiscoveredRepo], None, None]:
        for found in sub_batches:
            all_repos.update(found)
            new_batch = {k: v for k, v in found.items() if k not in seen}
            seen.update(new_batch.keys())
            if new_batch:
                tag_trusted_repos(new_batch)
                trusted_count = sum(1 for r in new_batch.values() if r.is_trusted)
                logger.info(
                    "Discovered {} new repos ({} trusted, {} total so far)",
                    len(new_batch),
                    trusted_count,
                    len(all_repos),
                )
                yield new_batch

    # Curated lists run second (right after trusted orgs) and fork runs last.
    # Everything else preserves the caller-supplied order.
    ordered = [s for s in strategies if s not in ("curated", "fork")]
    if "curated" in strategies:
        ordered.insert(0, "curated")
    if "fork" in strategies:
        ordered.append("fork")

    try:
        # Always search trusted orgs first — fast, high-value repos
        logger.info("Discovery strategy: Trusted organizations")
        yield from _yield_sub_batches(search_trusted_orgs(gh, stats))

        for name in ordered:
            logger.info("Discovery strategy: {}", _STRATEGY_LABELS.get(name, name))

            if name == "size":
                sub_batches = search_by_file_size(gh, stats)
            elif name == "path":
                sub_batches = search_by_path(gh, stats)
            elif name == "topic":
                sub_batches = search_by_topic(gh, stats)
            elif name == "curated":
                sub_batches = parse_curated_lists(gh, stats)
            elif name == "fork":
                top_repos = sorted(
                    all_repos.values(),
                    key=lambda r: r.stars,
                    reverse=True,
                )[:10]
                sub_batches = scan_forks(gh, [r.full_name for r in top_repos], stats)
            else:
                continue

            yield from _yield_sub_batches(sub_batches)
    finally:
        gh.close()

    stats.repos_discovered = len(all_repos)


def _filter_changed_repos(
    repos: list[DiscoveredRepo],
    checkpoint: Checkpoint,
    github_token: str | None,
) -> list[DiscoveredRepo]:
    """Filter out repos whose HEAD SHA matches the checkpoint (unchanged).

    Uses concurrent GitHub API calls to check HEAD SHA for previously-processed
    repos. Repos not in the checkpoint are always included.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from rich.progress import Progress, SpinnerColumn, TextColumn

    from decision_hub.domain.tracker import fetch_latest_commit_sha

    # Split into new repos (no SHA check needed) and known repos (need check)
    new_repos: list[DiscoveredRepo] = []
    needs_check: list[DiscoveredRepo] = []
    for repo in repos:
        if checkpoint.get_last_sha(repo.full_name) is None:
            new_repos.append(repo)
        else:
            needs_check.append(repo)

    if not needs_check:
        changed = new_repos
    else:
        changed = list(new_repos)

        def _check_sha(repo: DiscoveredRepo) -> tuple[DiscoveredRepo, bool]:
            """Return (repo, has_changed)."""
            last_sha = checkpoint.get_last_sha(repo.full_name)
            parts = repo.full_name.split("/", 1)
            if len(parts) == 2:
                try:
                    current = fetch_latest_commit_sha(parts[0], parts[1], "HEAD", github_token)
                    if current == last_sha:
                        return repo, False
                except Exception:
                    pass
            return repo, True

        interactive = _is_interactive()
        check_total = len(needs_check)
        checked = 0
        skipped = 0

        if interactive:
            from rich.progress import Progress, SpinnerColumn, TextColumn

            progress_mgr: Any = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TextColumn("{task.completed}/{task.total}"),
            )
        else:
            from contextlib import nullcontext

            progress_mgr = nullcontext()
            print(f"Checking {check_total} repos for changes...", flush=True)

        with progress_mgr as progress, ThreadPoolExecutor(max_workers=10) as pool:
            task = progress.add_task("Checking for repo changes...", total=check_total) if interactive else None
            futures = {pool.submit(_check_sha, r): r for r in needs_check}
            for future in as_completed(futures):
                repo, has_changed = future.result()
                if has_changed:
                    changed.append(repo)
                else:
                    skipped += 1
                checked += 1
                if interactive and task is not None:
                    progress.advance(task)
                elif checked % 100 == 0 or checked == check_total:
                    print(f"  SHA check: {checked}/{check_total} (skipped {skipped})", flush=True)

            if skipped:
                logger.info("{} repos unchanged since last crawl, skipping", skipped)

    # Trusted orgs first, then by stars within each group
    changed.sort(key=lambda r: (r.is_trusted, r.stars), reverse=True)
    return changed


PROCESSING_CHUNK_SIZE = 30


def _is_interactive() -> bool:
    """Return True if stderr is a terminal (Rich progress bars render there)."""
    import sys

    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


# How often to emit a text-mode progress line (every N repos).
_TEXT_PROGRESS_INTERVAL = 30


def run_processing_phase(
    pending_repos: list[DiscoveredRepo],
    bot_user_id: str,
    github_token: str | None,
    checkpoint: Checkpoint,
    checkpoint_path: Path,
    max_skills: int | None,
    modal_app_name: str,
    stats: CrawlStats,
    set_tracker: bool = True,
) -> bool:
    """Fan out repo processing to Modal containers in small chunks.

    Processes repos in chunks of PROCESSING_CHUNK_SIZE so we can stop early
    when the max_skills cap is reached without wasting Modal compute on
    hundreds of repos that won't be needed.

    When stderr is not a TTY (e.g. output redirected to a file), emits
    periodic text progress lines so ``tail -f`` shows live progress.

    Returns True if max_skills cap was reached (caller should stop).
    """
    import modal

    fn = modal.Function.from_name(modal_app_name, "crawl_process_repo")
    interactive = _is_interactive()
    completed = 0
    total = len(pending_repos)

    def _emit_text_progress(repo_name: str) -> None:
        """Print a plain-text progress line (non-TTY mode)."""
        pct = completed * 100 // total if total else 0
        print(
            f"[{completed}/{total} {pct}%] pub:{stats.skills_published} "
            f"fail:{stats.skills_failed} skip:{stats.skills_skipped} "
            f"quar:{stats.skills_quarantined} — {repo_name}",
            flush=True,
        )

    def _process_repos() -> bool:
        nonlocal completed
        for chunk_start in range(0, len(pending_repos), PROCESSING_CHUNK_SIZE):
            chunk = pending_repos[chunk_start : chunk_start + PROCESSING_CHUNK_SIZE]
            chunk_dicts = [repo_to_dict(r) for r in chunk]

            for result in fn.map(
                chunk_dicts,
                kwargs={"bot_user_id": bot_user_id, "github_token": github_token, "set_tracker": set_tracker},
                return_exceptions=True,
                wrap_returned_exceptions=False,
            ):
                if isinstance(result, BaseException):
                    stats.errors.append(str(result)[:500])
                    repo_name = "unknown"
                    commit_sha = None
                else:
                    stats.accumulate(result)
                    repo_name = result.get("repo", "unknown")
                    commit_sha = result.get("commit_sha")

                checkpoint.mark_processed(repo_name, checkpoint_path, commit_sha=commit_sha)
                completed += 1

                if interactive and progress_task is not None:
                    progress_ctx.update(  # type: ignore[union-attr]
                        progress_task,
                        advance=1,
                        pub=stats.skills_published,
                        fail=stats.skills_failed,
                        skip=stats.skills_skipped,
                        quar=stats.skills_quarantined,
                    )
                elif completed % _TEXT_PROGRESS_INTERVAL == 0 or completed == total:
                    _emit_text_progress(repo_name)

            if max_skills is not None and stats.skills_published >= max_skills:
                logger.info("Reached --max-skills cap ({}), stopping", max_skills)
                checkpoint.flush(checkpoint_path)
                return True

        checkpoint.flush(checkpoint_path)
        return False

    if interactive:
        from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

        progress_ctx = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn(
                "pub:{task.fields[pub]} fail:{task.fields[fail]} "
                "skip:{task.fields[skip]} quarantine:{task.fields[quar]}"
            ),
        )
        with progress_ctx:
            progress_task = progress_ctx.add_task(
                "Processing repos",
                total=total,
                pub=stats.skills_published,
                fail=stats.skills_failed,
                skip=stats.skills_skipped,
                quar=stats.skills_quarantined,
            )
            return _process_repos()
    else:
        progress_ctx = None  # type: ignore[assignment]
        progress_task = None
        print(f"Processing {total} repos (text mode — progress every {_TEXT_PROGRESS_INTERVAL} repos)", flush=True)
        return _process_repos()


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
            set_tracker=args.set_tracker,
        )
        _print_summary(stats)
        return

    # --repos: skip discovery, resolve specific repos and process them
    if args.repos:
        from decision_hub.scripts.crawler.discovery import GitHubClient, resolve_repos

        gh = GitHubClient(args.github_token)
        try:
            resolve_stats = CrawlStats()
            resolved = resolve_repos(gh, args.repos, resolve_stats)
        finally:
            gh.close()

        if not resolved:
            logger.error("No repos could be resolved. Nothing to process.")
            sys.exit(1)

        if args.dry_run:
            print(f"\nResolved {len(resolved)} repos:")
            for r in resolved.values():
                trusted = " [trusted]" if r.is_trusted else ""
                print(f"  {r.full_name} ({r.stars}★){trusted}")
            return

        checkpoint = Checkpoint.load(checkpoint_path) if checkpoint_path.exists() else Checkpoint()
        for full_name, repo in resolved.items():
            checkpoint.discovered_repos[full_name] = repo_to_dict(repo)
        checkpoint.save(checkpoint_path)

        pending = list(resolved.values())

        from decision_hub.infra.database import create_engine, upsert_user
        from decision_hub.scripts.crawler.processing import BOT_GITHUB_ID, BOT_USERNAME

        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            bot_user = upsert_user(conn, github_id=BOT_GITHUB_ID, username=BOT_USERNAME)
            conn.commit()

        proc_stats = CrawlStats()
        run_processing_phase(
            pending_repos=pending,
            bot_user_id=str(bot_user.id),
            github_token=args.github_token,
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            max_skills=args.max_skills,
            modal_app_name=settings.modal_app_name,
            stats=proc_stats,
            set_tracker=args.set_tracker,
        )
        _print_summary(proc_stats)
        return

    # Streaming mode: discover a batch → process it → discover next batch
    checkpoint = Checkpoint.load(checkpoint_path) if checkpoint_path.exists() else Checkpoint()
    discovery_stats = CrawlStats()
    proc_stats = CrawlStats()
    bot_user_id: str | None = None

    strategies = [] if args.trusted_only else args.strategies
    for batch in discover_batches(args.github_token, strategies, discovery_stats):
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
            set_tracker=args.set_tracker,
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
