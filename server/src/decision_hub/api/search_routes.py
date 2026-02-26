"""Skill ask route -- natural language discovery via LLM."""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.engine import Connection

from decision_hub.api.deps import get_connection, get_current_user_optional, get_s3_client, get_settings
from decision_hub.api.rate_limit import RateLimiter
from decision_hub.domain.search import build_index_entry, format_trust_score, resolve_author_display, serialize_index
from decision_hub.infra.database import insert_search_log, list_user_org_ids, search_skills_hybrid
from decision_hub.infra.embeddings import EMBEDDING_DIMENSIONS, embed_query
from decision_hub.infra.gemini import (
    ask_conversational,
    check_query_topicality,
    create_gemini_client,
    parse_query_keywords,
)
from decision_hub.infra.storage import upload_search_log
from decision_hub.models import SkillIndexEntry, User
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


# ---------------------------------------------------------------------------
# Shared retrieval pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalResult:
    """Output of the shared retrieval pipeline."""

    candidates: tuple[dict, ...]
    entries: tuple[SkillIndexEntry, ...]
    index_content: str
    embed_ms: int
    db_ms: int


def _run_retrieval(
    gemini: dict,
    query: str,
    conn: Connection,
    settings: Settings,
    user_id: UUID | None,
    category: str | None = None,
) -> RetrievalResult | None:
    """Parse keywords, embed query, run hybrid search, build index.

    Returns None when the candidate set is empty.
    """

    # Parse keywords + embed query in parallel
    def _do_parse() -> list[str]:
        return parse_query_keywords(gemini, query, settings.gemini_model)

    def _do_embed() -> tuple[list[float] | None, int]:
        try:
            t0 = time.monotonic()
            emb = embed_query(gemini, query, settings.embedding_model, EMBEDDING_DIMENSIONS)
            return emb, int((time.monotonic() - t0) * 1000)
        except Exception:
            logger.opt(exception=True).warning("Query embedding failed, falling back to FTS-only")
            return None, 0

    with ThreadPoolExecutor(max_workers=2) as pool:
        parse_future = pool.submit(_do_parse)
        embed_future = pool.submit(_do_embed)
        fts_queries = parse_future.result()
        query_embedding, embed_ms = embed_future.result()

    # Hybrid retrieval
    user_org_ids = list_user_org_ids(conn, user_id) if user_id else None
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
        return None

    entries = tuple(
        build_index_entry(
            org_slug=row["org_slug"],
            skill_name=row["skill_name"],
            description=row.get("description", ""),
            latest_version=row["latest_version"],
            eval_status=row["eval_status"],
            author=resolve_author_display(row.get("published_by", "")),
            category=row.get("category", ""),
            download_count=row.get("download_count", 0),
            source_repo_url=row.get("source_repo_url"),
            gauntlet_summary=row.get("gauntlet_summary"),
        )
        for row in candidates
    )
    index_content = serialize_index(list(entries))

    return RetrievalResult(
        candidates=tuple(candidates),
        entries=entries,
        index_content=index_content,
        embed_ms=embed_ms,
        db_ms=db_ms,
    )


# ---------------------------------------------------------------------------
# GET /v1/ask -- structured conversational answer with skill links
# ---------------------------------------------------------------------------

_OFF_TOPIC_ANSWER = (
    "This doesn't look like a skill-related question. "
    "I can help you find AI skills and capabilities in the Decision Hub registry.\n\n"
    "**Try asking something like:**\n"
    '- "Help me build a Bayesian model"\n'
    '- "I need to create presentation slides"\n'
    '- "What tools are available for writing LinkedIn posts?"\n'
    '- "How can I analyze my A/B test results?"'
)


class AskSkillRef(BaseModel):
    """A skill referenced in the conversational answer."""

    org_slug: str
    skill_name: str
    description: str
    safety_rating: str
    reason: str
    author: str = ""
    category: str = ""
    download_count: int = 0
    latest_version: str = ""
    source_repo_url: str | None = None
    gauntlet_summary: str | None = None


class AskResponse(BaseModel):
    """Conversational answer with structured skill links."""

    query: str
    answer: str
    skills: list[AskSkillRef]
    category: str | None = None


@router.get(
    "/ask",
    response_model=AskResponse,
    dependencies=[Depends(_enforce_search_rate_limit)],
)
def ask_skills(
    q: str = Query(..., max_length=500),
    category: str | None = Query(None, max_length=100, description="Filter results to a specific category"),
    settings: Settings = Depends(get_settings),
    conn=Depends(get_connection),
    s3_client=Depends(get_s3_client),
    current_user: User | None = Depends(get_current_user_optional),
) -> AskResponse:
    """Answer a natural language question with conversational response and skill links.

    Uses hybrid retrieval (FTS + embedding) and Gemini to generate a structured
    conversational answer with explicit skill references that both the CLI and
    the frontend can render.
    """
    if not settings.google_api_key:
        raise HTTPException(
            status_code=503,
            detail="Ask is not configured (missing GOOGLE_API_KEY)",
        )

    gemini = create_gemini_client(settings.google_api_key)

    guard = check_query_topicality(gemini, q, settings.gemini_model)
    if not guard["is_skill_query"]:
        return AskResponse(query=q, answer=_OFF_TOPIC_ANSWER, skills=[])

    start_time = time.monotonic()

    result = _run_retrieval(
        gemini,
        q,
        conn,
        settings,
        user_id=current_user.id if current_user else None,
        category=category,
    )

    if result is None:
        msg = (
            f"No skills found in category '{category}'."
            if category
            else "I couldn't find any skills matching your question. Try rephrasing or broadening your search."
        )
        return AskResponse(query=q, answer=msg, skills=[], category=category)

    # Build lookup map for enriching LLM skill refs with DB metadata
    candidate_map: dict[tuple[str, str], dict] = {
        (row["org_slug"], row["skill_name"]): row for row in result.candidates
    }

    # Conversational answer with structured output
    try:
        llm_start = time.monotonic()
        llm_result = ask_conversational(
            gemini,
            q,
            result.index_content,
            settings.gemini_model,
        )
        llm_ms = int((time.monotonic() - llm_start) * 1000)
    except Exception:
        logger.opt(exception=True).warning("Conversational ask failed, using fallback")
        fallback_latency_ms = int((time.monotonic() - start_time) * 1000)
        skill_refs = [
            AskSkillRef(
                org_slug=e.org_slug,
                skill_name=e.skill_name,
                description=e.description,
                safety_rating=format_trust_score(
                    candidate_map.get((e.org_slug, e.skill_name), {}).get("eval_status", "")
                ),
                reason="Matched your search query.",
                author=e.author,
                category=e.category,
                download_count=e.download_count,
                latest_version=e.latest_version,
                source_repo_url=e.source_repo_url,
                gauntlet_summary=e.gauntlet_summary,
            )
            for e in result.entries[:5]
        ]
        try:
            log_id = uuid4()
            s3_key = upload_search_log(
                s3_client,
                settings.s3_bucket,
                log_id,
                q,
                "",
                {
                    "results_count": len(result.entries),
                    "model": settings.gemini_model,
                    "latency_ms": fallback_latency_ms,
                    "user_id": str(current_user.id) if current_user else None,
                    "username": current_user.username if current_user else None,
                    "fallback": True,
                },
            )
            insert_search_log(
                conn,
                log_id=log_id,
                query=q,
                s3_key=s3_key,
                results_count=len(result.entries),
                model=settings.gemini_model,
                latency_ms=fallback_latency_ms,
                user_id=current_user.id if current_user else None,
            )
        except Exception:
            logger.opt(exception=True).warning("Analytics logging failed for fallback ask q='{}'", q[:80])
        return AskResponse(
            query=q,
            answer="Here are the most relevant skills I found:",
            skills=skill_refs,
            category=category,
        )

    latency_ms = int((time.monotonic() - start_time) * 1000)
    logger.info(
        "Ask q='{}' candidates={} embed_ms={} db_ms={} llm_ms={} total_ms={}",
        q[:80],
        len(result.candidates),
        result.embed_ms,
        result.db_ms,
        llm_ms,
        latency_ms,
    )

    # Log to S3 + DB (non-critical, must not block the response)
    try:
        log_id = uuid4()
        log_metadata = {
            "results_count": len(result.entries),
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
            llm_result.get("answer", ""),
            log_metadata,
        )

        insert_search_log(
            conn,
            log_id=log_id,
            query=q,
            s3_key=s3_key,
            results_count=len(result.entries),
            model=settings.gemini_model,
            latency_ms=latency_ms,
            user_id=current_user.id if current_user else None,
        )
    except Exception:
        logger.opt(exception=True).warning("Analytics logging failed for ask q='{}'", q[:80])

    # Enrich LLM skill references with metadata from DB candidates
    skill_refs = []
    for ref in llm_result.get("referenced_skills", []):
        key = (ref["org_slug"], ref["skill_name"])
        row = candidate_map.get(key)
        if row:
            skill_refs.append(
                AskSkillRef(
                    org_slug=ref["org_slug"],
                    skill_name=ref["skill_name"],
                    description=row.get("description", ""),
                    safety_rating=format_trust_score(row.get("eval_status", "")),
                    reason=ref.get("reason", ""),
                    author=resolve_author_display(row.get("published_by", "")),
                    category=row.get("category", ""),
                    download_count=row.get("download_count", 0),
                    latest_version=row.get("latest_version", ""),
                    source_repo_url=row.get("source_repo_url"),
                    gauntlet_summary=row.get("gauntlet_summary"),
                )
            )

    return AskResponse(
        query=q,
        answer=llm_result.get("answer", ""),
        skills=skill_refs,
        category=category,
    )
