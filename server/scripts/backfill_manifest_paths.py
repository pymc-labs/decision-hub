"""Backfill manifest_path for existing skills.

For each skill with a source_repo_url but no manifest_path, clones the repo,
discovers SKILL.md files, and records the relative path.

Run from server/ with:
    DHUB_ENV=dev uv run --package decision-hub-server \
        python scripts/backfill_manifest_paths.py --github-token "$(gh auth token)"

Limit to N skills (for testing):
    DHUB_ENV=dev uv run --package decision-hub-server \
        python scripts/backfill_manifest_paths.py --limit 10 --github-token "$(gh auth token)"

Reset all manifest_path values and recompute:
    DHUB_ENV=dev uv run --package decision-hub-server \
        python scripts/backfill_manifest_paths.py --reset --github-token "$(gh auth token)"
"""

import argparse
import shutil
from collections import defaultdict
from pathlib import Path

import sqlalchemy as sa
from loguru import logger

from decision_hub.domain.repo_utils import clone_repo, discover_skills
from decision_hub.domain.skill_manifest import parse_skill_md
from decision_hub.infra.database import (
    create_engine,
    organizations_table,
    skills_table,
    update_skill_manifest_path,
)
from decision_hub.settings import create_settings, get_env


def _discover_manifest_paths(repo_root: Path) -> dict[str, str]:
    """Map skill name -> relative SKILL.md path for all skills in a repo."""
    result: dict[str, str] = {}
    skill_dirs = discover_skills(repo_root)
    for skill_dir in skill_dirs:
        try:
            manifest = parse_skill_md(skill_dir / "SKILL.md")
            rel_path = str((skill_dir / "SKILL.md").relative_to(repo_root))
            result[manifest.name] = rel_path
        except (ValueError, FileNotFoundError):
            continue
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill manifest_path for skills")
    parser.add_argument("--github-token", help="GitHub token for cloning repos")
    parser.add_argument("--limit", type=int, default=0, help="Max skills to process (0 = all)")
    parser.add_argument("--reset", action="store_true", help="Recompute ALL manifest_paths, not just empty ones")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated without writing")
    args = parser.parse_args()

    env = get_env()
    logger.info("Backfilling manifest_path in {} environment (reset={}, limit={})", env, args.reset, args.limit)

    settings = create_settings(env)
    engine = create_engine(settings.database_url)

    # Fetch skills that need manifest_path, grouped by source_repo_url
    stmt = sa.select(
        skills_table.c.id.label("skill_id"),
        skills_table.c.name.label("skill_name"),
        skills_table.c.source_repo_url,
        organizations_table.c.slug.label("org_slug"),
    ).select_from(
        skills_table.join(
            organizations_table,
            skills_table.c.org_id == organizations_table.c.id,
        )
    ).where(
        skills_table.c.source_repo_url.isnot(None),
    ).order_by(
        skills_table.c.source_repo_url,
        skills_table.c.name,
    )

    if not args.reset:
        stmt = stmt.where(skills_table.c.manifest_path.is_(None))

    if args.limit > 0:
        stmt = stmt.limit(args.limit)

    with engine.connect() as conn:
        rows = conn.execute(stmt).fetchall()

    if not rows:
        logger.info("No skills need manifest_path backfill")
        return

    logger.info("Found {} skills to backfill across repos", len(rows))

    # Group by repo URL to clone each repo only once
    repo_skills: dict[str, list] = defaultdict(list)
    for row in rows:
        repo_skills[row.source_repo_url].append(row)

    logger.info("Grouped into {} unique repos", len(repo_skills))

    updated = 0
    skipped = 0
    failed = 0

    for repo_url, skills in repo_skills.items():
        skill_names = [s.skill_name for s in skills]
        logger.info("Cloning {} ({} skills: {})", repo_url, len(skills), ", ".join(skill_names))

        repo_root = None
        try:
            repo_root = clone_repo(
                repo_url,
                github_token=args.github_token,
                timeout=120,
            )
            name_to_path = _discover_manifest_paths(repo_root)
            logger.info("  Discovered {} SKILL.md files in repo", len(name_to_path))

            for skill_row in skills:
                manifest_path = name_to_path.get(skill_row.skill_name)
                if manifest_path is None:
                    logger.warning(
                        "  {}/{}: SKILL.md not found in repo (skill may have been removed)",
                        skill_row.org_slug,
                        skill_row.skill_name,
                    )
                    skipped += 1
                    continue

                if args.dry_run:
                    logger.info("  [DRY RUN] {}/{} -> {}", skill_row.org_slug, skill_row.skill_name, manifest_path)
                    updated += 1
                    continue

                with engine.connect() as conn:
                    update_skill_manifest_path(conn, skill_row.skill_id, manifest_path)
                    conn.commit()
                logger.info("  {}/{} -> {}", skill_row.org_slug, skill_row.skill_name, manifest_path)
                updated += 1

        except RuntimeError as exc:
            logger.warning("  Clone failed for {}: {}", repo_url, exc)
            failed += len(skills)
        except Exception:
            logger.opt(exception=True).warning("  Error processing {}", repo_url)
            failed += len(skills)
        finally:
            if repo_root is not None:
                shutil.rmtree(repo_root.parent, ignore_errors=True)

    logger.info(
        "Backfill complete: updated={}, skipped={}, failed={} (total={})",
        updated,
        skipped,
        failed,
        len(rows),
    )


if __name__ == "__main__":
    main()
