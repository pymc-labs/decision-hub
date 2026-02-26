"""Backfill trackers for crawled skills that have a source_repo_url but no tracker.

Run from server/ with:
    DHUB_ENV=dev uv run --package decision-hub-server python scripts/backfill_trackers.py

For production:
    DHUB_ENV=prod uv run --package decision-hub-server python scripts/backfill_trackers.py

Only creates trackers owned by the dhub-crawler bot user. Existing trackers
(same user_id + repo_url + branch) are skipped via ON CONFLICT DO NOTHING.
"""

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.dialects.postgresql import insert as pg_insert

from decision_hub.infra.database import (
    create_engine,
    organizations_table,
    skill_trackers_table,
    skills_table,
    upsert_user,
)
from decision_hub.scripts.crawler.processing import BOT_GITHUB_ID, BOT_USERNAME
from decision_hub.settings import create_settings, get_env


def main() -> None:
    env = get_env()
    logger.info("Backfilling trackers in {} environment", env)

    settings = create_settings(env)
    engine = create_engine(settings.database_url)

    # Ensure the bot user exists and get their ID
    with engine.connect() as conn:
        bot_user = upsert_user(conn, github_id=BOT_GITHUB_ID, username=BOT_USERNAME)
        conn.commit()

    logger.info("Bot user: id={} username={}", bot_user.id, BOT_USERNAME)

    # Find all distinct (source_repo_url, org_slug) pairs from skills
    # that have a source_repo_url but no matching tracker for this bot user.
    existing_trackers = (
        sa.select(skill_trackers_table.c.repo_url).where(skill_trackers_table.c.user_id == bot_user.id)
    ).subquery("existing_trackers")

    stmt = (
        sa.select(
            skills_table.c.source_repo_url.label("repo_url"),
            organizations_table.c.slug.label("org_slug"),
        )
        .select_from(
            skills_table.join(
                organizations_table,
                skills_table.c.org_id == organizations_table.c.id,
            )
        )
        .where(
            sa.and_(
                skills_table.c.source_repo_url.isnot(None),
                skills_table.c.source_repo_url != "",
                skills_table.c.source_repo_url.notin_(sa.select(existing_trackers.c.repo_url)),
            )
        )
        .distinct()
    )

    with engine.connect() as conn:
        rows = conn.execute(stmt).fetchall()

    logger.info("Found {} repo/org pairs needing trackers", len(rows))

    if not rows:
        logger.info("Nothing to backfill")
        return

    # Create trackers in bulk using ON CONFLICT DO NOTHING
    # to handle any race conditions or duplicates gracefully
    created = 0
    skipped = 0

    with engine.connect() as conn:
        for row in rows:
            repo_url = row.repo_url
            org_slug = row.org_slug

            insert_stmt = (
                pg_insert(skill_trackers_table)
                .values(
                    user_id=bot_user.id,
                    org_slug=org_slug,
                    repo_url=repo_url,
                    branch="main",
                    poll_interval_minutes=60,
                )
                .on_conflict_do_nothing(
                    constraint="skill_trackers_user_id_repo_url_branch_key",
                )
                .returning(skill_trackers_table.c.id)
            )
            result = conn.execute(insert_stmt)
            tracker_row = result.first()

            if tracker_row is not None:
                created += 1
                logger.info("Created tracker for {} (org={})", repo_url, org_slug)
            else:
                skipped += 1
                logger.debug("Skipped existing tracker for {} (org={})", repo_url, org_slug)

        conn.commit()

    logger.info("Backfill complete: {} created, {} skipped", created, skipped)


if __name__ == "__main__":
    main()
