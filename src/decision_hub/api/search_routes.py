"""Skill search routes -- natural language discovery via LLM."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from decision_hub.api.deps import get_connection, get_s3_client, get_settings
from decision_hub.domain.search import build_index_entry, serialize_index
from decision_hub.infra.gemini import create_gemini_client, search_skills_with_llm
from decision_hub.settings import Settings

router = APIRouter(prefix="/v1", tags=["search"])


class SearchResponse(BaseModel):
    """Search results from LLM-powered skill discovery."""
    query: str
    results: str


class RefreshResponse(BaseModel):
    """Confirmation that the index was refreshed."""
    entry_count: int


@router.get("/search", response_model=SearchResponse)
def search_skills(
    q: str,
    settings: Settings = Depends(get_settings),
    conn=Depends(get_connection),
    s3_client=Depends(get_s3_client),
) -> SearchResponse:
    """Search for skills using natural language.

    Fetches the skill index from S3, then uses Gemini to rank and
    recommend skills matching the query.
    """
    if not settings.google_api_key:
        raise HTTPException(
            status_code=503,
            detail="Search is not configured (missing GOOGLE_API_KEY)",
        )

    # Fetch index from S3
    from decision_hub.infra.storage import download_index
    index_content = download_index(s3_client, settings.s3_bucket)

    if not index_content:
        return SearchResponse(query=q, results="No skills in the index yet.")

    # Search with Gemini
    gemini = create_gemini_client(settings.google_api_key)
    result_text = search_skills_with_llm(
        gemini, q, index_content, settings.gemini_model,
    )

    return SearchResponse(query=q, results=result_text)


@router.post("/index/refresh", response_model=RefreshResponse)
def refresh_index(
    conn=Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
) -> RefreshResponse:
    """Rebuild the skill search index from the database and upload to S3.

    Fetches all published skills with their latest versions and eval
    statuses, builds index entries, serializes to JSONL, and uploads.
    """
    from decision_hub.infra.database import fetch_all_skills_for_index
    from decision_hub.infra.storage import upload_index

    rows = fetch_all_skills_for_index(conn)
    entries = [
        build_index_entry(
            org_slug=row["org_slug"],
            skill_name=row["skill_name"],
            description=row.get("description", ""),
            latest_version=row["latest_version"],
            eval_status=row["eval_status"],
        )
        for row in rows
    ]

    index_content = serialize_index(entries)
    upload_index(s3_client, settings.s3_bucket, index_content)

    return RefreshResponse(entry_count=len(entries))
