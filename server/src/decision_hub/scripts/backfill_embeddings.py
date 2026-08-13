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
from decision_hub.infra.embeddings import (
    EMBEDDING_DIMENSIONS,
    build_embedding_text,
    create_embedding_client,
    embed_texts_batch,
)
from decision_hub.settings import create_settings


def backfill(batch_size: int = 100, *, reembed_all: bool = False) -> None:
    """Backfill embeddings for skills.

    By default only fills skills with embedding IS NULL. With
    ``reembed_all`` every skill is re-embedded — required after switching
    the embedding provider, since query and stored vectors must come
    from the same model.
    """
    settings = create_settings()
    embedder = create_embedding_client(settings)
    if embedder is None:
        logger.error("No LLM API key set — cannot generate embeddings")
        return
    client, model = embedder
    logger.info("Embedding with provider={} model={}", client.get("provider", "gemini"), model)

    engine = create_engine(settings.database_url)
    last_id = None

    total_processed = 0
    total_errors = 0  # cumulative errors for final summary
    consecutive_errors = 0  # circuit breaker: abort if too many in a row

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
                .limit(batch_size)
            )
            if reembed_all:
                # Keyset pagination: "embedding IS NULL" can't track progress
                # when every row already has an embedding to replace.
                if last_id is not None:
                    stmt = stmt.where(skills_table.c.id > last_id)
                stmt = stmt.order_by(skills_table.c.id)
            else:
                stmt = stmt.where(skills_table.c.embedding.is_(None))
            rows = conn.execute(stmt).all()

            if not rows:
                break
            if reembed_all:
                last_id = max(row.id for row in rows)

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
                    model,
                    EMBEDDING_DIMENSIONS,
                )
            except Exception:
                logger.opt(exception=True).error(
                    "Batch embedding failed at offset {}, retrying after backoff",
                    total_processed,
                )
                total_errors += 1
                consecutive_errors += 1
                if consecutive_errors > 10:
                    logger.error("Too many consecutive errors, aborting")
                    break
                time.sleep(min(2**consecutive_errors, 60))
                continue

            # Store embeddings
            for row, embedding in zip(rows, embeddings, strict=True):
                update_skill_embedding(conn, row.id, embedding)

            conn.commit()
            total_processed += len(rows)
            consecutive_errors = 0  # reset circuit breaker on success
            logger.info("Backfilled {}/{} skills", total_processed, total_processed)

    logger.info(
        "Backfill complete: {} skills processed, {} errors",
        total_processed,
        total_errors,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill skill embeddings")
    parser.add_argument("--batch-size", type=int, default=100, help="Skills per API call")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Re-embed every skill (required after switching embedding provider)",
    )
    args = parser.parse_args()
    backfill(batch_size=args.batch_size, reembed_all=args.all)


if __name__ == "__main__":
    main()
