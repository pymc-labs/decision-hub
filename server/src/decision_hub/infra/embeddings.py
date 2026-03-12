"""Gemini embedding utilities for hybrid search."""

from uuid import UUID

import httpx
from loguru import logger
from sqlalchemy.engine import Connection

from decision_hub.infra.database import update_skill_embedding
from decision_hub.infra.gemini import gemini_request_with_retry
from decision_hub.settings import Settings

# Must match the DB column: vector(768) in the migration.
EMBEDDING_DIMENSIONS = 768


def build_embedding_text(
    name: str,
    org_slug: str,
    category: str,
    description: str,
) -> str:
    """Format skill metadata into a single string for embedding.

    Joins non-empty fields with ' | ' to give the embedding model
    structured context about the skill.
    """
    parts = [name]
    if org_slug:
        parts.append(org_slug)
    if category:
        parts.append(category)
    if description:
        parts.append(description)
    return " | ".join(parts)


def embed_query(
    client: dict,
    text: str,
    model: str,
    dimensions: int,
    *,
    max_retries: int = 3,
) -> list[float]:
    """Embed a single search query via Gemini.

    Retries with exponential backoff on transient HTTP errors (403 rate-limit,
    429, 500, 502, 503) via the shared ``gemini_request_with_retry`` helper.

    Args:
        client: Gemini client config dict with api_key and base_url.
        text: The text to embed.
        model: Gemini embedding model name.
        dimensions: Output dimensionality.
        max_retries: Number of retries on transient errors.

    Returns:
        List of floats representing the embedding vector.

    Raises:
        httpx.HTTPStatusError: On non-2xx, non-retriable response.
        httpx.TimeoutException: On timeout after all retries exhausted.
    """
    url = f"{client['base_url']}/{model}:embedContent"
    payload = {
        "model": f"models/{model}",
        "content": {"parts": [{"text": text}]},
        "outputDimensionality": dimensions,
    }
    data = gemini_request_with_retry(
        client,
        url,
        payload,
        timeout=10,
        max_retries=max_retries,
        label="Gemini embedding",
    )
    return data["embedding"]["values"]


def embed_texts_batch(
    client: dict,
    texts: list[str],
    model: str,
    dimensions: int,
) -> list[list[float]]:
    """Batch embed multiple texts via Gemini batchEmbedContents.

    Args:
        client: Gemini client config dict with api_key and base_url.
        texts: List of texts to embed.
        model: Gemini embedding model name.
        dimensions: Output dimensionality.

    Returns:
        List of embedding vectors (one per input text).

    Raises:
        httpx.HTTPStatusError: On non-2xx response.
        httpx.TimeoutException: On timeout.
    """
    url = f"{client['base_url']}/{model}:batchEmbedContents"
    requests = [
        {
            "model": f"models/{model}",
            "content": {"parts": [{"text": t}]},
            "outputDimensionality": dimensions,
        }
        for t in texts
    ]
    payload = {"requests": requests}
    with httpx.Client(timeout=30) as http_client:
        resp = http_client.post(
            url,
            params={"key": client["api_key"]},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return [e["values"] for e in data["embeddings"]]


def generate_and_store_skill_embedding(
    conn: Connection,
    skill_id: UUID,
    name: str,
    org_slug: str,
    category: str,
    description: str,
    settings: Settings,
) -> None:
    """Generate and store an embedding for a skill. Fail-open: never blocks publish.

    Builds the embedding text from skill metadata, calls Gemini to embed it,
    and stores the result in the database. Any failure is logged as a warning
    but does not raise.
    """
    if not settings.google_api_key:
        return

    try:
        from decision_hub.infra.gemini import create_gemini_client

        client = create_gemini_client(settings.google_api_key)
        text = build_embedding_text(name, org_slug, category, description)
        embedding = embed_query(
            client,
            text,
            settings.embedding_model,
            EMBEDDING_DIMENSIONS,
        )
        # Use a savepoint so a DB error doesn't poison the outer transaction.
        nested = conn.begin_nested()
        try:
            update_skill_embedding(conn, skill_id, embedding)
            nested.commit()
        except Exception:
            nested.rollback()
            raise
    except Exception:
        logger.opt(exception=True).warning(
            "Failed to generate embedding for skill={} ({}/{})",
            skill_id,
            org_slug,
            name,
        )
