"""Backfill embeddings for skills that don't have one yet.

Usage:
    cd server && DHUB_ENV=dev uv run --package decision-hub-server \
        python -m decision_hub.scripts.backfill_embeddings --batch-size 100
"""

import argparse
import time

import sqlalchemy as sa
from loguru import logger

from decision_hub.infra.database import (
    create_engine,
    organizations_table,
    skills_table,
    update_skill_embedding,
)
from decision_hub.infra.embeddings import build_embedding_text, embed_texts_batch
from decision_hub.infra.gemini import create_gemini_client
from decision_hub.settings import create_settings


def backfill(batch_size: int = 100) -> None:
    """Backfill embeddings for all skills with embedding IS NULL."""
    settings = create_settings()
    if not settings.google_api_key:
        logger.error("GOOGLE_API_KEY not set — cannot generate embeddings")
        return

    engine = create_engine(settings.database_url)
    client = create_gemini_client(settings.google_api_key)

    total_processed = 0
    total_errors = 0

    while True:
        with engine.connect() as conn:
            # Fetch a batch of skills without embeddings
            stmt = (
                sa.select(
                    skills_table.c.id,
                    skills_table.c.name,
                    skills_table.c.description,
                    skills_table.c.category,
                    organizations_table.c.slug.label("org_slug"),
                )
                .select_from(
                    skills_table.join(
                        organizations_table,
                        skills_table.c.org_id == organizations_table.c.id,
                    )
                )
                .where(skills_table.c.embedding.is_(None))
                .limit(batch_size)
            )
            rows = conn.execute(stmt).all()

            if not rows:
                break

            # Build texts for this batch
            texts = [
                build_embedding_text(
                    name=row.name,
                    org_slug=row.org_slug,
                    category=row.category or "",
                    description=row.description or "",
                )
                for row in rows
            ]

            try:
                embeddings = embed_texts_batch(
                    client,
                    texts,
                    settings.embedding_model,
                    settings.embedding_dimensions,
                )
            except Exception:
                logger.opt(exception=True).error(
                    "Batch embedding failed at offset {}, retrying after backoff",
                    total_processed,
                )
                total_errors += 1
                if total_errors > 10:
                    logger.error("Too many errors, aborting")
                    break
                time.sleep(min(2**total_errors, 60))
                continue

            # Store embeddings
            for row, embedding in zip(rows, embeddings, strict=True):
                update_skill_embedding(conn, row.id, embedding)

            conn.commit()
            total_processed += len(rows)
            logger.info("Backfilled {}/{} skills", total_processed, total_processed)

    logger.info(
        "Backfill complete: {} skills processed, {} errors",
        total_processed,
        total_errors,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill skill embeddings")
    parser.add_argument("--batch-size", type=int, default=100, help="Skills per API call")
    args = parser.parse_args()
    backfill(batch_size=args.batch_size)


if __name__ == "__main__":
    main()
