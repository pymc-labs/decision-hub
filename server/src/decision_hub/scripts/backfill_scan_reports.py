"""Backfill scan_reports for skills that have no scan report yet.

Finds the latest version of each skill that lacks a scan_report row,
downloads the zip from S3, runs the scanner, and stores the result.

Usage:
    cd server && DHUB_ENV=dev uv run --package decision-hub-server \
        python -m decision_hub.scripts.backfill_scan_reports --workers 4

    # Dry run (count only)
    ... --dry-run

    # Test on 5 skills first
    ... --limit 5 --workers 1

    # Resume after a crash (skips already-scanned skills)
    ... --workers 4 --resume
"""

import argparse
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

import sqlalchemy as sa
from loguru import logger

from decision_hub.domain.skill_scanner_bridge import scan_skill_zip, store_scan_result
from decision_hub.infra.database import (
    create_engine,
    organizations_table,
    scan_reports_table,
    skills_table,
    versions_table,
)
from decision_hub.infra.storage import create_s3_client, download_skill_zip
from decision_hub.settings import create_settings

# Alias — the FK target is named differently in the migration vs SA metadata
skill_versions_table = versions_table

MAX_CONSECUTIVE_ERRORS = 10


def _find_skills_needing_scan(engine: sa.engine.Engine, *, limit: int | None) -> list[dict]:
    """Return skills whose latest version has no scan_report."""
    latest = (
        sa.select(
            skill_versions_table.c.id.label("version_id"),
            skill_versions_table.c.skill_id,
            skill_versions_table.c.s3_key,
            skill_versions_table.c.semver,
            sa.func.row_number()
            .over(
                partition_by=skill_versions_table.c.skill_id,
                order_by=skill_versions_table.c.created_at.desc(),
            )
            .label("rn"),
        )
    ).subquery("latest")

    stmt = (
        sa.select(
            latest.c.version_id,
            latest.c.s3_key,
            latest.c.semver,
            organizations_table.c.slug.label("org_slug"),
            skills_table.c.name.label("skill_name"),
        )
        .select_from(
            skills_table.join(
                organizations_table,
                skills_table.c.org_id == organizations_table.c.id,
            )
            .join(
                latest,
                sa.and_(
                    skills_table.c.id == latest.c.skill_id,
                    latest.c.rn == 1,
                ),
            )
            .outerjoin(
                scan_reports_table,
                scan_reports_table.c.version_id == latest.c.version_id,
            )
        )
        .where(scan_reports_table.c.id.is_(None))
        .order_by(organizations_table.c.slug, skills_table.c.name)
    )
    if limit:
        stmt = stmt.limit(limit)

    with engine.connect() as conn:
        rows = conn.execute(stmt).all()
    return [dict(row._mapping) for row in rows]


def _scan_one(skill: dict, settings: object, s3_client: object, bucket: str) -> dict:
    """Download zip and run scanner. Returns scan_data dict."""
    zip_bytes = download_skill_zip(s3_client, bucket, skill["s3_key"])
    return scan_skill_zip(zip_bytes, settings)  # type: ignore[arg-type]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill scan reports for existing skills")
    parser.add_argument("--limit", type=int, default=None, help="Max skills to scan")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers")
    parser.add_argument("--dry-run", action="store_true", help="Count only, don't scan")
    parser.add_argument("--resume", action="store_true", help="Skip already-scanned (default behavior)")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds to wait between submitting scans")
    args = parser.parse_args()

    settings = create_settings()
    engine = create_engine(settings.database_url)
    s3_client = create_s3_client(
        region=settings.aws_region,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
        endpoint_url=settings.s3_endpoint_url,
    )

    logger.info("Finding skills needing scan reports...")
    skills = _find_skills_needing_scan(engine, limit=args.limit)
    logger.info("Found {} skills needing scan reports", len(skills))

    if args.dry_run:
        for s in skills[:20]:
            logger.info("  {}/{} v{}", s["org_slug"], s["skill_name"], s["semver"])
        if len(skills) > 20:
            logger.info("  ... and {} more", len(skills) - 20)
        return

    consecutive_errors = 0
    scanned = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures: dict[Future, dict] = {}

        for skill in skills:
            if args.delay > 0:
                time.sleep(args.delay)
            future = pool.submit(_scan_one, skill, settings, s3_client, settings.s3_bucket)
            futures[future] = skill

        for future in as_completed(futures):
            skill = futures[future]
            slug = f"{skill['org_slug']}/{skill['skill_name']}"

            try:
                scan_data = future.result()

                with engine.connect() as conn:
                    store_scan_result(
                        conn,
                        scan_data,
                        version_id=skill["version_id"],
                        org_slug=skill["org_slug"],
                        skill_name=skill["skill_name"],
                        semver=skill["semver"],
                    )
                    conn.commit()

                scanned += 1
                consecutive_errors = 0
                logger.info(
                    "[{}/{}] {} v{}: {} severity={} findings={}",
                    scanned + failed,
                    len(skills),
                    slug,
                    skill["semver"],
                    "SAFE" if scan_data["is_safe"] else "UNSAFE",
                    scan_data["max_severity"],
                    scan_data["findings_count"],
                )
            except Exception:
                logger.opt(exception=True).error("Failed to scan {}", slug)
                failed += 1
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error("Circuit breaker: {} consecutive errors, aborting", consecutive_errors)
                    break

    logger.info("Backfill complete: {} scanned, {} failed out of {} total", scanned, failed, len(skills))


if __name__ == "__main__":
    main()
