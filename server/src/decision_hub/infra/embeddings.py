"""Embedding utilities for hybrid search (OpenRouter/Qwen default, Gemini fallback).

Dispatches on the client dict's ``provider`` field, mirroring the LLM
judge functions in ``infra.gemini``. Query embeddings must live in the
same vector space as the stored skill embeddings — switching providers
requires re-embedding all skills (scripts/backfill_embeddings.py).
"""

from uuid import UUID

import httpx
from loguru import logger
from sqlalchemy.engine import Connection

from decision_hub.infra.database import update_skill_embedding
from decision_hub.infra.gemini import create_gemini_client, gemini_request_with_retry
from decision_hub.infra.openrouter import create_openrouter_client, openrouter_request_with_retry
from decision_hub.settings import Settings, resolve_judge_provider

# Must match the DB column: vector(768) in the migration.
EMBEDDING_DIMENSIONS = 768


def create_embedding_client(settings: Settings, *, http_client: httpx.Client | None = None) -> tuple[dict, str] | None:
    """Build the (client, model) pair for the configured embedding backend.

    Uses the same provider resolution as the LLM judge (OpenRouter
    preferred, Gemini fallback) so one API key setting drives all LLM
    features. Returns None when no provider has an API key.
    """
    provider = resolve_judge_provider(settings)
    if provider is None:
        return None
    if provider == "openrouter":
        return (
            create_openrouter_client(settings.openrouter_api_key, http_client=http_client),
            settings.openrouter_embedding_model,
        )
    return create_gemini_client(settings.google_api_key, http_client=http_client), settings.embedding_model


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
    """Embed a single search query.

    Dispatches on the client's ``provider`` field (OpenRouter uses the
    OpenAI-compatible /embeddings endpoint; Gemini uses embedContent).
    Retries with exponential backoff on transient HTTP errors (403
    rate-limit, 429, 500, 502, 503) via the shared retry helpers.

    Args:
        client: Provider client config dict with api_key and base_url.
        text: The text to embed.
        model: Embedding model name for the client's provider.
        dimensions: Output dimensionality.
        max_retries: Number of retries on transient errors.

    Returns:
        List of floats representing the embedding vector.

    Raises:
        httpx.HTTPStatusError: On non-2xx, non-retriable response.
        httpx.TimeoutException: On timeout after all retries exhausted.
    """
    if client.get("provider") == "openrouter":
        url = f"{client['base_url']}/embeddings"
        payload = {"model": model, "input": text, "dimensions": dimensions}
        data = openrouter_request_with_retry(
            client,
            url,
            payload,
            timeout=10,
            max_retries=max_retries,
            label="OpenRouter embedding",
        )
        return data["data"][0]["embedding"]

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
    """Batch embed multiple texts.

    Dispatches on the client's ``provider`` field (OpenRouter accepts a
    list input on /embeddings; Gemini uses batchEmbedContents).

    Args:
        client: Provider client config dict with api_key and base_url.
        texts: List of texts to embed.
        model: Embedding model name for the client's provider.
        dimensions: Output dimensionality.

    Returns:
        List of embedding vectors (one per input text).

    Raises:
        httpx.HTTPStatusError: On non-2xx response.
        httpx.TimeoutException: On timeout.
    """
    if client.get("provider") == "openrouter":
        url = f"{client['base_url']}/embeddings"
        payload = {"model": model, "input": texts, "dimensions": dimensions}
        data = openrouter_request_with_retry(client, url, payload, timeout=30, label="OpenRouter embedding")
        # The API returns one entry per input with an explicit index;
        # sort defensively so output order always matches input order.
        entries = sorted(data["data"], key=lambda e: e["index"])
        return [e["embedding"] for e in entries]

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

    Builds the embedding text from skill metadata, embeds it via the
    configured provider, and stores the result in the database. Any
    failure is logged as a warning but does not raise.
    """
    embedder = create_embedding_client(settings)
    if embedder is None:
        return

    try:
        client, model = embedder
        text = build_embedding_text(name, org_slug, category, description)
        embedding = embed_query(
            client,
            text,
            model,
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
