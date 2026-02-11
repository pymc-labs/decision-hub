"""Skill search routes -- natural language discovery via LLM."""

import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from decision_hub.api.deps import get_connection, get_current_user_optional, get_s3_client, get_settings
from decision_hub.api.rate_limit import RateLimiter
from decision_hub.domain.search import build_index_entry, serialize_index
from decision_hub.infra.database import fetch_all_skills_for_index, insert_search_log
from decision_hub.infra.gemini import check_query_topicality, create_gemini_client, search_skills_with_llm
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


@router.get(
    "/search",
    response_model=SearchResponse,
    dependencies=[Depends(_enforce_search_rate_limit)],
)
def search_skills(
    q: str,
    settings: Settings = Depends(get_settings),
    conn=Depends(get_connection),
    s3_client=Depends(get_s3_client),
    current_user: User | None = Depends(get_current_user_optional),
) -> SearchResponse:
    """Search for skills using natural language.

    Queries the database for all published skills, formats them as a
    JSONL index, then uses Gemini to rank and recommend matches.

    Logs all queries to S3 + DB for analytics (with user_id if authenticated).
    """
    if not settings.google_api_key:
        raise HTTPException(
            status_code=503,
            detail="Search is not configured (missing GOOGLE_API_KEY)",
        )

    # Intent guard: reject off-topic queries before hitting the DB or main LLM
    gemini = create_gemini_client(settings.google_api_key)
    guard = check_query_topicality(gemini, q, settings.gemini_model)
    if not guard["is_skill_query"]:
        return SearchResponse(
            query=q,
            results=(
                "This doesn't look like a skill search query. "
                "`dhub ask` searches the skill registry for tools and capabilities.\n\n"
                "**Try something like:**\n"
                "- `dhub ask 'data validation'`\n"
                "- `dhub ask 'causal inference tools'`\n"
                "- `dhub ask 'A/B test analysis'`"
            ),
        )

    start_time = time.monotonic()

    # Build index directly from the database (single source of truth)
    rows = fetch_all_skills_for_index(conn)
    if not rows:
        return SearchResponse(query=q, results="No skills in the index yet.")

    entries = [
        build_index_entry(
            org_slug=row["org_slug"],
            skill_name=row["skill_name"],
            description=row.get("description", ""),
            latest_version=row["latest_version"],
            eval_status=row["eval_status"],
            author=row.get("published_by", ""),
        )
        for row in rows
    ]
    index_content = serialize_index(entries)

    result_text = search_skills_with_llm(
        gemini,
        q,
        index_content,
        settings.gemini_model,
    )

    latency_ms = int((time.monotonic() - start_time) * 1000)

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

    return SearchResponse(query=q, results=result_text)
