"""Skill search routes -- natural language discovery via LLM."""

import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel

from decision_hub.api.deps import get_connection, get_current_user_optional, get_s3_client, get_settings
from decision_hub.api.rate_limit import RateLimiter
from decision_hub.domain.search import build_index_entry, format_deterministic_results, serialize_index
from decision_hub.infra.database import insert_search_log, list_user_org_ids, search_skills_hybrid
from decision_hub.infra.embeddings import EMBEDDING_DIMENSIONS, embed_query
from decision_hub.infra.gemini import (
    check_query_topicality,
    create_gemini_client,
    parse_query_keywords,
    search_skills_with_llm,
)
from decision_hub.infra.storage import upload_search_log
from decision_hub.models import User
from decision_hub.settings import Settings

router = APIRouter(prefix="/v1", tags=["search"])


def _enforce_search_rate_limit(request: Request) -> None:
    """Rate-limit the search endpoint. Limiter is initialised lazily from settings."""
    state = request.app.state
    if not hasattr(state, "_search_rate_limiter"):
        settings: Settings = state.settings
        state._search_rate_limiter = RateLimiter(
            max_requests=settings.search_rate_limit,
            window_seconds=settings.search_rate_window,
        )
    state._search_rate_limiter(request)


class SearchResponse(BaseModel):
    """Search results from LLM-powered skill discovery."""

    query: str
    results: str
    category: str | None = None


@router.get(
    "/search",
    response_model=SearchResponse,
    dependencies=[Depends(_enforce_search_rate_limit)],
)
def search_skills(
    q: str = Query(..., max_length=500),
    category: str | None = Query(None, max_length=100, description="Filter results to a specific category"),
    settings: Settings = Depends(get_settings),
    conn=Depends(get_connection),
    s3_client=Depends(get_s3_client),
    current_user: User | None = Depends(get_current_user_optional),
) -> SearchResponse:
    """Search for skills using hybrid retrieval + LLM reranking.

    Pipeline:
    1. Topicality guard (Gemini) — reject off-topic queries
    2. In parallel: parse query keywords + embed query
    3. Hybrid retrieval: FTS (parsed keywords) + vector search (embedding)
    4. Gemini reranks the small candidate set
    5. Deterministic fallback if Gemini rerank fails
    """
    if not settings.google_api_key:
        raise HTTPException(
            status_code=503,
            detail="Search is not configured (missing GOOGLE_API_KEY)",
        )

    gemini = create_gemini_client(settings.google_api_key)

    # Step 1: Topicality guard (sequential — cheap, fast)
    guard = check_query_topicality(gemini, q, settings.gemini_model)
    if not guard["is_skill_query"]:
        return SearchResponse(
            query=q,
            results=(
                "This doesn't look like a skill search query. "
                "`dhub ask` searches the skill registry for AI skills and capabilities.\n\n"
                "**Try something like:**\n"
                "- `dhub ask 'help me build a Bayesian model'`\n"
                "- `dhub ask 'I need to create presentation slides'`\n"
                "- `dhub ask 'tool for writing LinkedIn posts'`\n"
                "- `dhub ask 'analyze my A/B test results'`"
            ),
        )

    start_time = time.monotonic()

    # Step 2: Parse keywords + embed query (parallel — both are independent LLM calls)
    def _do_parse() -> list[str]:
        return parse_query_keywords(gemini, q, settings.gemini_model)

    def _do_embed() -> tuple[list[float] | None, int]:
        try:
            t0 = time.monotonic()
            emb = embed_query(gemini, q, settings.embedding_model, EMBEDDING_DIMENSIONS)
            return emb, int((time.monotonic() - t0) * 1000)
        except Exception:
            logger.opt(exception=True).warning("Query embedding failed, falling back to FTS-only")
            return None, 0

    with ThreadPoolExecutor(max_workers=2) as pool:
        parse_future = pool.submit(_do_parse)
        embed_future = pool.submit(_do_embed)
        fts_queries = parse_future.result()
        query_embedding, embed_ms = embed_future.result()

    # Step 3: Hybrid retrieval
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    db_start = time.monotonic()
    candidates = search_skills_hybrid(
        conn,
        fts_queries,
        query_embedding,
        user_org_ids=user_org_ids,
        category=category,
        limit=settings.search_candidate_limit,
    )
    db_ms = int((time.monotonic() - db_start) * 1000)

    if not candidates:
        msg = f"No skills found in category '{category}'." if category else "No skills matched your query."
        return SearchResponse(query=q, results=msg, category=category)

    # Step 3: Build index entries from candidates
    entries = [
        build_index_entry(
            org_slug=row["org_slug"],
            skill_name=row["skill_name"],
            description=row.get("description", ""),
            latest_version=row["latest_version"],
            eval_status=row["eval_status"],
            author=row.get("published_by", ""),
            category=row.get("category", ""),
        )
        for row in candidates
    ]
    index_content = serialize_index(entries)

    # Step 4: Gemini rerank (fail-open to deterministic fallback)
    fallback_used = False
    try:
        llm_start = time.monotonic()
        result_text = search_skills_with_llm(
            gemini,
            q,
            index_content,
            settings.gemini_model,
        )
        llm_ms = int((time.monotonic() - llm_start) * 1000)
    except Exception:
        logger.opt(exception=True).warning("Gemini rerank failed, using deterministic fallback")
        result_text = format_deterministic_results(entries)
        llm_ms = 0
        fallback_used = True

    latency_ms = int((time.monotonic() - start_time) * 1000)

    logger.info(
        "Search q='{}' fts_queries={} candidates={} embed_ms={} db_ms={} llm_ms={} fallback={}",
        q[:80],
        fts_queries,
        len(candidates),
        embed_ms,
        db_ms,
        llm_ms,
        fallback_used,
    )

    # Log the search query to S3 + DB
    log_id = uuid4()
    log_metadata = {
        "results_count": len(entries),
        "model": settings.gemini_model,
        "latency_ms": latency_ms,
        "user_id": str(current_user.id) if current_user else None,
        "username": current_user.username if current_user else None,
    }

    s3_key = upload_search_log(
        s3_client,
        settings.s3_bucket,
        log_id,
        q,
        result_text,
        log_metadata,
    )

    insert_search_log(
        conn,
        log_id=log_id,
        query=q,
        s3_key=s3_key,
        results_count=len(entries),
        model=settings.gemini_model,
        latency_ms=latency_ms,
        user_id=current_user.id if current_user else None,
    )

    return SearchResponse(query=q, results=result_text, category=category)
