"""Conversational ask routes -- natural language Q&A with structured skill links."""

import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel

from decision_hub.api.deps import get_connection, get_current_user_optional, get_settings
from decision_hub.api.rate_limit import RateLimiter
from decision_hub.domain.search import build_index_entry, serialize_index
from decision_hub.infra.database import list_user_org_ids, search_skills_hybrid
from decision_hub.infra.embeddings import EMBEDDING_DIMENSIONS, embed_query
from decision_hub.infra.gemini import (
    ask_conversational,
    check_query_topicality,
    create_gemini_client,
    parse_query_keywords,
)
from decision_hub.models import User
from decision_hub.settings import Settings

router = APIRouter(prefix="/v1", tags=["ask"])


def _enforce_ask_rate_limit(request: Request) -> None:
    """Rate-limit the ask endpoint. Reuses search rate-limit settings."""
    state = request.app.state
    if not hasattr(state, "_ask_rate_limiter"):
        settings: Settings = state.settings
        state._ask_rate_limiter = RateLimiter(
            max_requests=settings.search_rate_limit,
            window_seconds=settings.search_rate_window,
        )
    state._ask_rate_limiter(request)


class AskSkillRef(BaseModel):
    """A skill referenced in the conversational answer."""

    org_slug: str
    skill_name: str
    description: str
    safety_rating: str
    reason: str


class AskResponse(BaseModel):
    """Conversational answer with structured skill links."""

    query: str
    answer: str
    skills: list[AskSkillRef]


@router.get(
    "/ask",
    response_model=AskResponse,
    dependencies=[Depends(_enforce_ask_rate_limit)],
)
def ask_skills(
    q: str = Query(..., max_length=500),
    settings: Settings = Depends(get_settings),
    conn=Depends(get_connection),
    current_user: User | None = Depends(get_current_user_optional),
) -> AskResponse:
    """Answer a natural language question with conversational response and skill links.

    Pipeline:
    1. Topicality guard (Gemini) -- reject off-topic queries
    2. In parallel: parse query keywords + embed query
    3. Hybrid retrieval: FTS + vector search
    4. Gemini generates conversational answer with structured skill references
    """
    if not settings.google_api_key:
        raise HTTPException(
            status_code=503,
            detail="Ask is not configured (missing GOOGLE_API_KEY)",
        )

    gemini = create_gemini_client(settings.google_api_key)

    # Step 1: Topicality guard
    guard = check_query_topicality(gemini, q, settings.gemini_model)
    if not guard["is_skill_query"]:
        return AskResponse(
            query=q,
            answer=(
                "This doesn't look like a skill-related question. "
                "I can help you find AI skills and capabilities in the Decision Hub registry.\n\n"
                "**Try asking something like:**\n"
                "- \"Help me build a Bayesian model\"\n"
                "- \"I need to create presentation slides\"\n"
                "- \"What tools are available for writing LinkedIn posts?\"\n"
                "- \"How can I analyze my A/B test results?\""
            ),
            skills=[],
        )

    start_time = time.monotonic()

    # Step 2: Parse keywords + embed query in parallel
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
        limit=settings.search_candidate_limit,
    )
    db_ms = int((time.monotonic() - db_start) * 1000)

    if not candidates:
        return AskResponse(
            query=q,
            answer="I couldn't find any skills matching your question. Try rephrasing or broadening your search.",
            skills=[],
        )

    # Build index for LLM context
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

    # Build a lookup map for enriching LLM skill refs with metadata
    candidate_map: dict[tuple[str, str], dict] = {}
    for row in candidates:
        candidate_map[(row["org_slug"], row["skill_name"])] = row

    # Step 4: Conversational answer with structured output
    try:
        llm_start = time.monotonic()
        llm_result = ask_conversational(
            gemini,
            q,
            index_content,
            settings.gemini_model,
        )
        llm_ms = int((time.monotonic() - llm_start) * 1000)
    except Exception:
        logger.opt(exception=True).warning("Conversational ask failed, using fallback")
        # Fallback: return a simple list
        skill_refs = []
        for entry in entries[:5]:
            row = candidate_map.get((entry.org_slug, entry.skill_name), {})
            skill_refs.append(
                AskSkillRef(
                    org_slug=entry.org_slug,
                    skill_name=entry.skill_name,
                    description=entry.description,
                    safety_rating=row.get("eval_status", ""),
                    reason="Matched your search query.",
                )
            )
        return AskResponse(
            query=q,
            answer="Here are the most relevant skills I found:",
            skills=skill_refs,
        )

    latency_ms = int((time.monotonic() - start_time) * 1000)
    logger.info(
        "Ask q='{}' candidates={} embed_ms={} db_ms={} llm_ms={} total_ms={}",
        q[:80],
        len(candidates),
        embed_ms,
        db_ms,
        llm_ms,
        latency_ms,
    )

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
                    safety_rating=row.get("eval_status", ""),
                    reason=ref.get("reason", ""),
                )
            )

    return AskResponse(
        query=q,
        answer=llm_result.get("answer", ""),
        skills=skill_refs,
    )
