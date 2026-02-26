"""Bulk-create trackers for all crawler-published skills that lack one.

Discovers skills published by the crawler user (dhub-crawler) that have a
source_repo_url but no matching tracker, and creates one tracker per unique
(repo_url, org_slug) pair.

Usage:
    cd server && DHUB_ENV=dev uv run --package decision-hub-server \
        python -m decision_hub.scripts.activate_trackers

    # Dry-run (no DB writes):
    cd server && DHUB_ENV=dev uv run --package decision-hub-server \
        python -m decision_hub.scripts.activate_trackers --dry-run
"""

import argparse
import sys
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from decision_hub.infra.database import (
    create_engine,
    insert_skill_tracker,
    organizations_table,
    skill_trackers_table,
    skills_table,
    users_table,
)
from decision_hub.settings import create_settings

_CRAWLER_USERNAME = "dhub-crawler"


def _find_crawler_user_id(conn: sa.Connection) -> UUID | None:
    """Return the user ID for the crawler account, or None if not found."""
    stmt = sa.select(users_table.c.id).where(users_table.c.username == _CRAWLER_USERNAME)
    row = conn.execute(stmt).first()
    return row.id if row else None


def _find_repos_without_trackers(
    conn: sa.Connection,
    crawler_user_id: UUID,
) -> list[tuple[str, str]]:
    """Return (repo_url, org_slug) pairs for crawler skills missing a tracker.

    Each unique (repo_url, org_slug) appears at most once. Only skills owned
    by the crawler user's orgs are considered.
    """
    # Subquery: repo_urls that already have a tracker for this user
    tracked = (
        sa.select(skill_trackers_table.c.repo_url)
        .where(skill_trackers_table.c.user_id == crawler_user_id)
        .scalar_subquery()
    )

    stmt = (
        sa.select(
            sa.distinct(skills_table.c.source_repo_url),
            organizations_table.c.slug,
        )
        .select_from(skills_table.join(organizations_table, skills_table.c.org_id == organizations_table.c.id))
        .where(
            skills_table.c.source_repo_url.isnot(None),
            organizations_table.c.owner_id == crawler_user_id,
            skills_table.c.source_repo_url.notin_(tracked),
        )
        .order_by(skills_table.c.source_repo_url)
    )
    rows = conn.execute(stmt).all()
    return [(r[0], r[1]) for r in rows]


def _run() -> None:
    parser = argparse.ArgumentParser(description="Activate trackers for crawler-published skills.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be created without writing to DB.")
    args = parser.parse_args()

    settings = create_settings()
    engine = create_engine(settings.database_url)

    with engine.connect() as conn:
        crawler_user_id = _find_crawler_user_id(conn)
        if crawler_user_id is None:
            print(f"Crawler user '{_CRAWLER_USERNAME}' not found. Nothing to do.")
            sys.exit(0)

        missing = _find_repos_without_trackers(conn, crawler_user_id)

    if not missing:
        print("All crawler repos already have trackers. Nothing to do.")
        sys.exit(0)

    print(f"Found {len(missing)} repos without trackers (user={_CRAWLER_USERNAME}):")
    for repo_url, org_slug in missing:
        print(f"  {org_slug} | {repo_url}")

    if args.dry_run:
        print("\n[dry-run] No trackers created.")
        sys.exit(0)

    created = 0
    skipped = 0
    with engine.connect() as conn:
        for repo_url, org_slug in missing:
            try:
                insert_skill_tracker(conn, user_id=crawler_user_id, org_slug=org_slug, repo_url=repo_url)
                created += 1
            except IntegrityError:
                # Race condition or duplicate — skip
                conn.rollback()
                skipped += 1
                print(f"  [skip] already exists: {org_slug} | {repo_url}")
                continue
        conn.commit()

    print(f"\nDone. Created {created} trackers, skipped {skipped}.")


if __name__ == "__main__":
    _run()
