"""Skill search routes -- natural language discovery via LLM."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from decision_hub.api.deps import get_connection, get_optional_user, get_settings
from decision_hub.api.rate_limit import RateLimiter
from decision_hub.domain.search import build_index_entry, serialize_index
from decision_hub.infra.database import fetch_all_skills_for_index, list_user_org_ids
from decision_hub.infra.gemini import (
    check_query_topicality,
    create_gemini_client,
    search_skills_with_llm,
)
from decision_hub.models import User
from decision_hub.settings import Settings

router = APIRouter(prefix="/v1", tags=["search"])


class SearchResponse(BaseModel):
    """Search results from LLM-powered skill discovery."""

    query: str
    results: str
    category: str | None = None


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


@router.get(
    "/search",
    response_model=SearchResponse,
    dependencies=[Depends(_enforce_search_rate_limit)],
)
def search_skills(
    q: str,
    category: str | None = Query(None, description="Filter results to a specific category"),
    settings: Settings = Depends(get_settings),
    conn=Depends(get_connection),
    current_user: User | None = Depends(get_optional_user),
) -> SearchResponse:
    """Search for skills using natural language.

    Queries the database for all published skills, formats them as a
    JSONL index, then uses Gemini to rank and recommend matches.
    Optionally filters to a single category before sending to the LLM.

    Uses optional auth: unauthenticated callers see only public skills.
    Authenticated callers also see org-private skills from their orgs.
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

    # Build index directly from the database (single source of truth)
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    rows = fetch_all_skills_for_index(conn, user_org_ids=user_org_ids)
    if not rows:
        return SearchResponse(query=q, results="No skills in the index yet.", category=category)

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
        for row in rows
    ]

    # Filter by category if specified
    if category:
        entries = [e for e in entries if e.category == category]
        if not entries:
            return SearchResponse(
                query=q,
                results=f"No skills found in category '{category}'.",
                category=category,
            )

    index_content = serialize_index(entries)

    # Search with Gemini (reuse client from guard call above)
    result_text = search_skills_with_llm(
        gemini,
        q,
        index_content,
        settings.gemini_model,
    )

    return SearchResponse(query=q, results=result_text, category=category)
