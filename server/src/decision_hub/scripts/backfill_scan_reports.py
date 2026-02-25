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
"""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import sqlalchemy as sa
from loguru import logger

from decision_hub.api.registry_service import store_scan_result
from decision_hub.domain.skill_scanner_bridge import scan_skill_zip
from decision_hub.infra.database import (
    create_engine,
    organizations_table,
    scan_reports_table,
    skills_table,
    versions_table,
)
from decision_hub.infra.storage import create_s3_client, download_skill_zip
from decision_hub.settings import create_settings


def _find_skills_needing_scan(engine, *, batch_size: int, offset: int):
    """Return skills whose latest version has no scan_report."""
    latest = (
        sa.select(
            versions_table.c.id.label("version_id"),
            versions_table.c.skill_id,
            versions_table.c.s3_key,
            versions_table.c.semver,
            sa.func.row_number()
            .over(
                partition_by=versions_table.c.skill_id,
                order_by=versions_table.c.created_at.desc(),
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
        .order_by(skills_table.c.created_at)
        .limit(batch_size)
        .offset(offset)
    )

    with engine.connect() as conn:
        return conn.execute(stmt).all()


def _count_skills_needing_scan(engine) -> int:
    """Count total skills whose latest version has no scan_report."""
    latest = (
        sa.select(
            versions_table.c.id.label("version_id"),
            versions_table.c.skill_id,
            sa.func.row_number()
            .over(
                partition_by=versions_table.c.skill_id,
                order_by=versions_table.c.created_at.desc(),
            )
            .label("rn"),
        )
    ).subquery("latest")

    stmt = (
        sa.select(sa.func.count())
        .select_from(
            skills_table.join(
                latest,
                sa.and_(
                    skills_table.c.id == latest.c.skill_id,
                    latest.c.rn == 1,
                ),
            ).outerjoin(
                scan_reports_table,
                scan_reports_table.c.version_id == latest.c.version_id,
            )
        )
        .where(scan_reports_table.c.id.is_(None))
    )

    with engine.connect() as conn:
        return conn.execute(stmt).scalar() or 0


def _scan_one(s3_client, bucket, settings, engine, *, version_id, s3_key, semver, org_slug, skill_name):
    """Download, scan, and store result for a single skill version."""
    zip_bytes = download_skill_zip(s3_client, bucket, s3_key)
    scan_result = scan_skill_zip(zip_bytes, settings)
    with engine.connect() as conn:
        store_scan_result(
            conn,
            scan_result,
            org_slug=org_slug,
            skill_name=skill_name,
            semver=semver,
            publisher="backfill",
            version_id=version_id,
        )
        conn.commit()
    return org_slug, skill_name, scan_result.grade


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill scan_reports for skills without one.")
    parser.add_argument("--workers", type=int, default=4, help="ThreadPoolExecutor concurrency")
    parser.add_argument("--batch-size", type=int, default=200, help="Skills fetched per DB query")
    parser.add_argument("--dry-run", action="store_true", help="Count only, don't scan")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N skills (0 = all)")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between submitting scan jobs")
    args = parser.parse_args()

    settings = create_settings()
    engine = create_engine(settings.database_url)

    total_needed = _count_skills_needing_scan(engine)
    logger.info("Skills needing scan_report: {}", total_needed)

    if args.dry_run:
        logger.info("Dry run — exiting")
        return

    if total_needed == 0:
        logger.info("Nothing to backfill")
        return

    s3_client = create_s3_client(settings.aws_region, settings.aws_access_key_id, settings.aws_secret_access_key)
    bucket = settings.s3_bucket

    processed = 0
    errors = 0
    consecutive_errors = 0
    max_consecutive_errors = 10

    while True:
        if args.limit and processed >= args.limit:
            logger.info("Reached --limit={}, stopping", args.limit)
            break

        batch = _find_skills_needing_scan(engine, batch_size=args.batch_size, offset=0)
        if not batch:
            break

        futures = {}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for row in batch:
                if args.limit and processed + len(futures) >= args.limit:
                    break

                future = pool.submit(
                    _scan_one,
                    s3_client,
                    bucket,
                    settings,
                    engine,
                    version_id=row.version_id,
                    s3_key=row.s3_key,
                    semver=row.semver,
                    org_slug=row.org_slug,
                    skill_name=row.skill_name,
                )
                futures[future] = f"{row.org_slug}/{row.skill_name}@{row.semver}"

                if args.delay > 0:
                    time.sleep(args.delay)

            for future in as_completed(futures):
                label = futures[future]
                try:
                    org_slug, skill_name, grade = future.result()
                    processed += 1
                    consecutive_errors = 0
                    logger.info(
                        "[{}/{}] {}/{}  grade={}",
                        processed,
                        total_needed,
                        org_slug,
                        skill_name,
                        grade,
                    )
                except Exception:
                    errors += 1
                    consecutive_errors += 1
                    logger.opt(exception=True).error("Failed: {}", label)

                    if consecutive_errors >= max_consecutive_errors:
                        logger.error(
                            "Circuit breaker: {} consecutive errors, aborting",
                            max_consecutive_errors,
                        )
                        break

        if consecutive_errors >= max_consecutive_errors:
            break

    logger.info("Backfill complete: processed={} errors={}", processed, errors)


if __name__ == "__main__":
    main()
