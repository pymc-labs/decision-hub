"""Skill search routes -- natural language discovery via LLM."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from decision_hub.api.deps import get_connection, get_settings
from decision_hub.domain.search import build_index_entry, serialize_index
from decision_hub.infra.database import fetch_all_skills_for_index
from decision_hub.infra.gemini import (
    check_query_topicality,
    create_gemini_client,
    search_skills_with_llm,
)
from decision_hub.settings import Settings

router = APIRouter(prefix="/v1", tags=["search"])


class SearchResponse(BaseModel):
    """Search results from LLM-powered skill discovery."""
    query: str
    results: str


@router.get("/search", response_model=SearchResponse)
def search_skills(
    q: str,
    settings: Settings = Depends(get_settings),
    conn=Depends(get_connection),
) -> SearchResponse:
    """Search for skills using natural language.

    Queries the database for all published skills, formats them as a
    JSONL index, then uses Gemini to rank and recommend matches.
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

    # Search with Gemini (reuse client from guard call above)
    result_text = search_skills_with_llm(
        gemini, q, index_content, settings.gemini_model,
    )

    return SearchResponse(query=q, results=result_text)
