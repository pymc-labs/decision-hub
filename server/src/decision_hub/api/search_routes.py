"""Skill search routes -- natural language discovery via LLM."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from decision_hub.api.deps import get_connection, get_optional_user, get_settings
from decision_hub.domain.search import build_index_entry, serialize_index
from decision_hub.infra.database import fetch_all_skills_for_index, list_user_org_ids
from decision_hub.infra.gemini import create_gemini_client, search_skills_with_llm
from decision_hub.models import User
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
    current_user: User | None = Depends(get_optional_user),
) -> SearchResponse:
    """Search for skills using natural language.

    Uses optional auth: unauthenticated callers see only public skills.
    Authenticated callers also see org-private skills from their orgs.
    """
    if not settings.google_api_key:
        raise HTTPException(
            status_code=503,
            detail="Search is not configured (missing GOOGLE_API_KEY)",
        )

    # Build index directly from the database (single source of truth)
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    rows = fetch_all_skills_for_index(conn, user_org_ids=user_org_ids)
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

    # Search with Gemini
    gemini = create_gemini_client(settings.google_api_key)
    result_text = search_skills_with_llm(
        gemini, q, index_content, settings.gemini_model,
    )

    return SearchResponse(query=q, results=result_text)
