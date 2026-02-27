# Opinionated Ask Endpoint

**Issue:** [#211](https://github.com/pymc-labs/decision-hub/issues/211)
**Date:** 2026-02-27

## Problem

Broad queries like "find tools to write linkedin post" return 10+ matching skills with no clear recommendation. The LLM lists everything that matches rather than being opinionated. This affects both the web chat modal and the CLI (`dhub ask`).

## Design

### 1. System Prompt Overhaul

Rewrite the recommendation/ranking portion of `ask_conversational()` in `gemini.py`.

**Ranking rules (in priority order):**

1. **Relevance to query** (primary) — how well does this skill match what the user asked?
2. **Trust grade** (tiebreaker) — A > B > C
3. **Eval status** (tiebreaker) — passed > pending > failed
4. **GitHub stars & forks** (tiebreaker) — community validation
5. **Downloads** (tiebreaker) — usage as social proof

**Output structure:**

- **Top picks (max 5):** Include in `referenced_skills`. For each, explain *why* it's the best fit for this specific query.
- **Runners-up:** Mention by name only in the `answer` markdown ("Also available: org/skill-a, org/skill-b"). Not in `referenced_skills` — no cards rendered.
- **Context hints:** End with what additional context would help narrow the recommendation. E.g. "If you tell me whether you're drafting from scratch or reformatting existing content, I can narrow this down."

### 2. Serialize Stars & Forks to LLM

In `serialize_index()` (`domain/search.py`), add `github_stars` and `github_forks` to the JSONL objects sent to Gemini. Only include when non-null (same pattern as `source_repo_url`).

### 3. POST Endpoint for Multi-Turn (Web Only)

Add `POST /v1/ask` alongside the existing GET.

**Request body:**

```python
class AskMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=5000)

class AskRequest(BaseModel):
    query: str = Field(max_length=500)
    history: list[AskMessage] = Field(default_factory=list, max_length=20)
```

**Server behavior:**

- Pass `history` as conversation context to Gemini (prepend to the user message)
- Retrieval still runs on the latest `query` only — history is for LLM context, not for search
- GET stays unchanged, internally equivalent to POST with empty history
- Rate limiting applied identically to both GET and POST
- No DB storage, no sessions — purely client-driven

### 4. Web Modal Changes

- `AskModal.tsx`: Send accumulated `messages` array as `history` with each request. Strip `skills` from history (only send `role` + `content`).
- `api/client.ts`: Add `askQuestionWithHistory(query, history)` that calls `POST /v1/ask`.

## Files Changed

| File | Change |
|------|--------|
| `server/src/decision_hub/infra/gemini.py` | Rewrite system prompt; accept `history` param in `ask_conversational()` |
| `server/src/decision_hub/domain/search.py` | Add stars/forks to `serialize_index()` |
| `server/src/decision_hub/api/search_routes.py` | Add `POST /v1/ask` endpoint, `AskRequest`/`AskMessage` models |
| `frontend/src/api/client.ts` | Add `askQuestionWithHistory()` |
| `frontend/src/components/AskModal.tsx` | Send history on each request |
| Tests | Update existing ask tests, add POST/history tests |

## Not Changed

- CLI (`client/`) — stays single-shot via GET
- GET `/v1/ask` — backward compatible, untouched
- `AskResponse` / `AskSkillRef` response models
- Retrieval pipeline (hybrid search)
- DB schema
