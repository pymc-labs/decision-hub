"""Backfill embeddings for skills that don't have one yet.

Usage:
    cd server && DHUB_ENV=dev uv run --package decision-hub-server \
        python -m decision_hub.scripts.backfill_embeddings --batch-size 100
"""

import argparse
import time

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.exc import OperationalError

from decision_hub.infra.database import (
    create_engine,
    organizations_table,
    skills_table,
    update_skill_embeddings_bulk,
)
from decision_hub.infra.embeddings import (
    EMBEDDING_DIMENSIONS,
    build_embedding_text,
    create_embedding_client,
    embed_texts_batch,
)
from decision_hub.settings import create_settings


class _EmbedBatchError(Exception):
    """Embedding API failed for a batch; the caller backs off and retries."""


def _process_batch(
    engine,
    client: dict,
    model: str,
    batch_size: int,
    *,
    reembed_all: bool,
    last_id,
) -> tuple[int, object] | None:
    """Fetch, embed, and store one batch. Returns (count, new_last_id), or None when done.

    Raises OperationalError on DB connection failure and _EmbedBatchError on
    embedding API failure — the caller owns backoff and the circuit breaker.
    The keyset cursor is returned (not mutated) only after a successful
    commit, so a failed batch is retried, never skipped.
    """
    with engine.connect() as conn:
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
            # ORDER BY id is required per CLAUDE.md: LIMIT without a
            # unique tiebreaker is nondeterministic. Without it a
            # retry after a failing batch could pick a different set
            # of rows and loop forever.
            .order_by(skills_table.c.id)
            .limit(batch_size)
        )
        if reembed_all:
            # Keyset pagination: "embedding IS NULL" can't track progress
            # when every row already has an embedding to replace.
            if last_id is not None:
                stmt = stmt.where(skills_table.c.id > last_id)
        else:
            stmt = stmt.where(skills_table.c.embedding.is_(None))
        rows = conn.execute(stmt).all()

        if not rows:
            return None

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
        except Exception as exc:
            logger.opt(exception=True).error("Batch embedding failed, retrying after backoff")
            raise _EmbedBatchError from exc

        # One statement for the whole batch: per-row UPDATEs cost a full
        # round trip each and dominated runtime (~1s/row vs 3s/100 to embed).
        update_skill_embeddings_bulk(conn, list(zip((r.id for r in rows), embeddings, strict=True)))
        conn.commit()

        return len(rows), max(row.id for row in rows)


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
        try:
            result = _process_batch(
                engine,
                client,
                model,
                batch_size,
                reembed_all=reembed_all,
                last_id=last_id,
            )
        except OperationalError:
            # The engine uses NullPool (PgBouncer transaction mode), so every
            # batch opens a fresh connection and any DB drop surfaces here as
            # a raw OperationalError. Dispose, back off, and retry — the
            # keyset cursor only advances after a successful commit, so
            # nothing is skipped.
            engine.dispose()
            total_errors += 1
            consecutive_errors += 1
            logger.opt(exception=True).warning(
                "DB connection dropped after {} skills — reconnecting (consecutive failure {})",
                total_processed,
                consecutive_errors,
            )
            if consecutive_errors > 10:
                logger.error("Too many consecutive errors, aborting")
                break
            time.sleep(min(2**consecutive_errors, 60))
            continue
        except _EmbedBatchError:
            total_errors += 1
            consecutive_errors += 1
            if consecutive_errors > 10:
                logger.error("Too many consecutive errors, aborting")
                break
            time.sleep(min(2**consecutive_errors, 60))
            continue

        if result is None:
            break
        processed, last_id = result
        total_processed += processed
        consecutive_errors = 0  # reset circuit breaker on success
        logger.info("Backfilled {} skills", total_processed)

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
