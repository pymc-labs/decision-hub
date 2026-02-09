"""Skill search routes -- natural language discovery via LLM."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from decision_hub.api.deps import get_connection, get_settings
from decision_hub.domain.search import build_index_entry, serialize_index
from decision_hub.infra.database import fetch_all_skills_for_index
from decision_hub.infra.gemini import create_gemini_client, search_skills_with_llm
from decision_hub.settings import Settings

router = APIRouter(prefix="/v1", tags=["search"])


class SearchResponse(BaseModel):
    """Search results from LLM-powered skill discovery."""
    query: str
    results: str
    category: str | None = None


@router.get("/search", response_model=SearchResponse)
def search_skills(
    q: str,
    category: str | None = Query(None, description="Filter results to a specific category"),
    settings: Settings = Depends(get_settings),
    conn=Depends(get_connection),
) -> SearchResponse:
    """Search for skills using natural language.

    Queries the database for all published skills, formats them as a
    JSONL index, then uses Gemini to rank and recommend matches.
    Optionally filters to a single category before sending to the LLM.
    """
    if not settings.google_api_key:
        raise HTTPException(
            status_code=503,
            detail="Search is not configured (missing GOOGLE_API_KEY)",
        )

    # Build index directly from the database (single source of truth)
    rows = fetch_all_skills_for_index(conn)
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

    # Search with Gemini
    gemini = create_gemini_client(settings.google_api_key)
    result_text = search_skills_with_llm(
        gemini, q, index_content, settings.gemini_model,
    )

    return SearchResponse(query=q, results=result_text, category=category)
