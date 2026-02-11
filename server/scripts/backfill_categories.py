"""Backfill categories for existing skills.

Run from server/ with:
    DHUB_ENV=dev uv run --package decision-hub-server python scripts/backfill_categories.py

Steps:
1. Fetch all skills with an empty category.
2. For each, download the zip from S3, extract SKILL.md, and classify.
3. Update the skill record with the new category.
"""

import io
import zipfile

import sqlalchemy as sa
from loguru import logger

from decision_hub.api.registry_service import classify_skill_category
from decision_hub.domain.skill_manifest import extract_body, extract_description
from decision_hub.infra.database import (
    create_engine,
    organizations_table,
    skills_table,
    versions_table,
)
from decision_hub.infra.storage import create_s3_client, download_skill_zip
from decision_hub.settings import create_settings, get_env


def _extract_skill_md_from_zip(zip_bytes: bytes) -> str | None:
    """Pull SKILL.md content out of a zip archive."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                basename = name.rsplit("/", 1)[-1] if "/" in name else name
                if basename == "SKILL.md":
                    return zf.read(name).decode()
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError) as exc:
        logger.warning("Failed to read zip: {}", exc)
    return None


def main() -> None:
    env = get_env()
    logger.info("Backfilling categories in {} environment", env)

    settings = create_settings(env)
    engine = create_engine(settings.database_url)

    # Fetch skills with empty category and their latest version S3 key
    latest_version = (
        sa.select(
            versions_table.c.skill_id,
            versions_table.c.s3_key,
            sa.func.row_number()
            .over(
                partition_by=versions_table.c.skill_id,
                order_by=versions_table.c.created_at.desc(),
            )
            .label("rn"),
        )
    ).subquery("latest_version")

    stmt = (
        sa.select(
            skills_table.c.id.label("skill_id"),
            skills_table.c.name.label("skill_name"),
            skills_table.c.description,
            organizations_table.c.slug.label("org_slug"),
            latest_version.c.s3_key,
        )
        .select_from(
            skills_table.join(
                organizations_table,
                skills_table.c.org_id == organizations_table.c.id,
            ).join(
                latest_version,
                sa.and_(
                    skills_table.c.id == latest_version.c.skill_id,
                    latest_version.c.rn == 1,
                ),
            )
        )
        .where(sa.or_(skills_table.c.category == "", skills_table.c.category.is_(None)))
    )

    s3_client = create_s3_client(
        region=settings.aws_region,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
    )

    with engine.connect() as conn:
        rows = conn.execute(stmt).fetchall()
        logger.info("Found {} skills to backfill", len(rows))

    # Classify and update each skill
    updated = 0
    for row in rows:
        skill_id = row.skill_id
        skill_name = row.skill_name
        org_slug = row.org_slug
        s3_key = row.s3_key
        description = row.description or ""

        logger.info("Processing {}/{} (s3={})", org_slug, skill_name, s3_key)

        # Download zip and extract SKILL.md body
        body = ""
        try:
            zip_bytes = download_skill_zip(s3_client, settings.s3_bucket, s3_key)
            skill_md = _extract_skill_md_from_zip(zip_bytes)
            if skill_md:
                body = extract_body(skill_md)
                if not description:
                    description = extract_description(skill_md)
        except (OSError, ValueError) as exc:
            logger.warning("Could not download/extract {}: {}", s3_key, exc)

        # Classify
        category = classify_skill_category(skill_name, description, body, settings)
        logger.info("  -> classified as: {}", category)

        # Update
        with engine.connect() as conn:
            conn.execute(sa.update(skills_table).where(skills_table.c.id == skill_id).values(category=category))
            conn.commit()
        updated += 1

    logger.info("Backfill complete: {}/{} skills updated", updated, len(rows))


if __name__ == "__main__":
    main()
