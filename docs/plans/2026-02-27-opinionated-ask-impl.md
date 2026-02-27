# Opinionated Ask Endpoint — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the ask endpoint recommend max 5 skills with opinionated ranking, mention runners-up briefly, suggest what context would help — and add real multi-turn support for the web modal via POST.

**Architecture:** Prompt-only change for recommendation quality (both surfaces). New POST endpoint alongside GET for multi-turn (web only). Client sends conversation history in POST body; server stays stateless.

**Tech Stack:** FastAPI, Gemini API, React, TypeScript

**Issue:** [#211](https://github.com/pymc-labs/decision-hub/issues/211)

---

### Task 1: Add github_stars and github_forks to SkillIndexEntry and serialize_index

**Files:**
- Modify: `server/src/decision_hub/models.py:308-322`
- Modify: `server/src/decision_hub/domain/search.py:8-49` (build_index_entry)
- Modify: `server/src/decision_hub/domain/search.py:79-108` (serialize_index)
- Modify: `server/src/decision_hub/api/search_routes.py:107-121` (_run_retrieval call)
- Test: `server/tests/test_domain/test_search.py`

**Step 1: Write the failing test**

Add to `server/tests/test_domain/test_search.py`:

```python
def test_serialize_index_includes_github_stars_and_forks():
    entries = [
        build_index_entry(
            "org1", "skill1", "Desc 1", "1.0.0", "passed",
            github_stars=150, github_forks=30,
        ),
        build_index_entry(
            "org2", "skill2", "Desc 2", "0.1.0", "pending",
            github_stars=None, github_forks=None,
        ),
    ]
    jsonl = serialize_index(entries)
    lines = jsonl.strip().split("\n")
    assert '"github_stars": 150' in lines[0]
    assert '"github_forks": 30' in lines[0]
    # Omitted when None
    assert "github_stars" not in lines[1]
    assert "github_forks" not in lines[1]
```

**Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_domain/test_search.py::test_serialize_index_includes_github_stars_and_forks -v`
Expected: FAIL — `build_index_entry` doesn't accept `github_stars`/`github_forks` yet.

**Step 3: Implement**

3a. Add fields to `SkillIndexEntry` in `server/src/decision_hub/models.py`:

```python
@dataclass(frozen=True)
class SkillIndexEntry:
    """Entry in the search index."""

    org_slug: str
    skill_name: str
    description: str
    latest_version: str
    eval_status: str
    trust_score: str
    author: str = ""
    category: str = ""
    download_count: int = 0
    source_repo_url: str | None = None
    gauntlet_summary: str | None = None
    github_stars: int | None = None
    github_forks: int | None = None
```

3b. Add params to `build_index_entry()` in `server/src/decision_hub/domain/search.py`:

```python
def build_index_entry(
    org_slug: str,
    skill_name: str,
    description: str,
    latest_version: str,
    eval_status: str,
    author: str = "",
    category: str = "",
    download_count: int = 0,
    source_repo_url: str | None = None,
    gauntlet_summary: str | None = None,
    github_stars: int | None = None,
    github_forks: int | None = None,
) -> SkillIndexEntry:
    return SkillIndexEntry(
        org_slug=org_slug,
        skill_name=skill_name,
        description=description,
        latest_version=latest_version,
        eval_status=eval_status,
        trust_score=format_trust_score(eval_status),
        author=author,
        category=category,
        download_count=download_count,
        source_repo_url=source_repo_url,
        gauntlet_summary=gauntlet_summary,
        github_stars=github_stars,
        github_forks=github_forks,
    )
```

3c. Add to `serialize_index()` in `server/src/decision_hub/domain/search.py` — after the `gauntlet_summary` block:

```python
        if entry.github_stars is not None:
            obj["github_stars"] = entry.github_stars
        if entry.github_forks is not None:
            obj["github_forks"] = entry.github_forks
```

3d. Pass through in `_run_retrieval()` in `server/src/decision_hub/api/search_routes.py` — add to the `build_index_entry()` call:

```python
            github_stars=row.get("github_stars"),
            github_forks=row.get("github_forks"),
```

**Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_domain/test_search.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add server/src/decision_hub/models.py server/src/decision_hub/domain/search.py server/src/decision_hub/api/search_routes.py server/tests/test_domain/test_search.py
git commit -m "feat: include github_stars and github_forks in ask LLM context (#211)"
```

---

### Task 2: Rewrite the system prompt to be opinionated

**Files:**
- Modify: `server/src/decision_hub/infra/gemini.py:305-353`
- Test: `server/tests/test_api/test_search_routes.py` (existing tests should still pass — prompt change is transparent to the API contract)

**Step 1: Replace the system prompt**

Replace the `system_prompt` variable in `ask_conversational()` (`server/src/decision_hub/infra/gemini.py:305-353`) with:

```python
    system_prompt = (
        "You are a helpful assistant for Decision Hub, an AI skill registry. "
        "Given a user's question and a set of candidate skills (JSONL format), "
        "provide an opinionated recommendation that helps the user choose the "
        "right skill for their needs.\n\n"
        "RECOMMENDATION RULES:\n"
        "1. Recommend at most 5 skills in referenced_skills. Be opinionated — "
        "pick the BEST matches, don't list everything that's vaguely related.\n"
        "2. Rank by RELEVANCE to the user's query first. A skill that precisely "
        "matches what the user asked for always beats a tangentially related one.\n"
        "3. When skills are equally relevant, break ties using: trust grade "
        "(A > B > C), passed evals over pending, GitHub stars & forks "
        "(community validation), then download count (usage).\n"
        "4. After your top picks, briefly mention any runners-up by name only "
        "(org/skill format) in a single sentence — e.g. 'Also available: "
        "org/skill-a, org/skill-b.' Do NOT include runners-up in "
        "referenced_skills.\n"
        "5. End your answer with a short note about what additional context "
        "would help you make a more precise recommendation — e.g. "
        "'If you tell me whether you need to draft posts from scratch or "
        "reformat existing content, I can narrow this down further.'\n"
        "6. For each recommended skill, explain WHY it's a good fit for this "
        "specific query, not just what the skill does.\n\n"
        "Each skill entry includes metadata: org, skill name, description, "
        "version, eval_status, trust grade, author, category, download count, "
        "github_stars, github_forks, source_repo_url (when available), and "
        "safety_notes (when the grade is not A). Use all available metadata.\n\n"
        "SECURITY GRADES: The 'trust' field is a security grade from the "
        "gauntlet safety scanner:\n"
        "- A = all checks passed, no elevated permissions — safest.\n"
        "- B = all checks passed but uses elevated permissions (shell, "
        "network, filesystem) — safe, but runs with more access.\n"
        "- C = warnings — the skill could not be fully scanned. "
        "Installing it carries security risk.\n"
        "- F = rejected — dangerous patterns confirmed. Won't appear in results.\n"
        "- ? = not yet graded.\n\n"
        "USING safety_notes: When a skill has a 'safety_notes' field, distill "
        "it into a short, user-friendly remark. Do NOT dump raw safety_notes "
        "verbatim. ALWAYS prefer grade A and B skills. If recommending a "
        "grade C skill, briefly explain the risk using safety_notes.\n\n"
        "Adapt your response depth to the query:\n"
        '- For simple lookups ("find a tool for X"), give a concise answer.\n'
        '- For analytical queries ("compare", "best", "differences"), '
        "provide detailed analysis with comparisons and clear recommendations.\n\n"
        "Always mention skills by name (org/skill format). "
        "Order referenced_skills by relevance. "
        "If no skills match, say so clearly and leave referenced_skills empty."
    )
```

**Step 2: Run existing tests to verify nothing breaks**

Run: `cd server && uv run pytest tests/test_api/test_search_routes.py -v`
Expected: ALL PASS (prompt change doesn't affect mock-based tests)

**Step 3: Commit**

```bash
git add server/src/decision_hub/infra/gemini.py
git commit -m "feat: rewrite ask prompt to be opinionated with max 5 picks (#211)"
```

---

### Task 3: Add POST /v1/ask endpoint with conversation history

**Files:**
- Modify: `server/src/decision_hub/api/search_routes.py` (add request models + POST handler)
- Modify: `server/src/decision_hub/infra/gemini.py:283-288` (add `history` param to `ask_conversational`)
- Test: `server/tests/test_api/test_search_routes.py`

**Step 1: Write the failing tests**

Add to `server/tests/test_api/test_search_routes.py`:

```python
class TestAskSkillsPost:
    """POST /v1/ask -- multi-turn conversational skill discovery."""

    @patch("decision_hub.api.search_routes.check_query_topicality", return_value=_GUARD_PASS)
    @patch("decision_hub.api.search_routes.parse_query_keywords", return_value=_PARSED_KEYWORDS)
    @patch("decision_hub.api.search_routes.embed_query", return_value=_FIXED_EMBEDDING)
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    @patch("decision_hub.api.search_routes.ask_conversational")
    def test_post_ask_success(
        self,
        mock_llm: MagicMock,
        mock_hybrid: MagicMock,
        _mock_embed: MagicMock,
        _mock_parse: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """POST with history passes conversation context to LLM."""
        mock_hybrid.return_value = _SAMPLE_CANDIDATES
        mock_llm.return_value = _LLM_RESULT

        resp = search_client.post("/v1/ask", json={
            "query": "I need the drafting one",
            "history": [
                {"role": "user", "content": "linkedin post tools"},
                {"role": "assistant", "content": "Here are my top picks..."},
            ],
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "I need the drafting one"
        assert len(data["skills"]) == 2
        # Verify history was passed to ask_conversational
        call_kwargs = mock_llm.call_args
        assert call_kwargs[1]["history"] is not None
        assert len(call_kwargs[1]["history"]) == 2

    @patch("decision_hub.api.search_routes.check_query_topicality", return_value=_GUARD_PASS)
    @patch("decision_hub.api.search_routes.parse_query_keywords", return_value=_PARSED_KEYWORDS)
    @patch("decision_hub.api.search_routes.embed_query", return_value=_FIXED_EMBEDDING)
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    @patch("decision_hub.api.search_routes.ask_conversational")
    def test_post_ask_empty_history(
        self,
        mock_llm: MagicMock,
        mock_hybrid: MagicMock,
        _mock_embed: MagicMock,
        _mock_parse: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """POST with empty history works like GET (single-shot)."""
        mock_hybrid.return_value = _SAMPLE_CANDIDATES
        mock_llm.return_value = _LLM_RESULT

        resp = search_client.post("/v1/ask", json={
            "query": "weather forecast",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "weather forecast"
        assert len(data["skills"]) == 2

    def test_post_ask_validates_query_length(self, search_client: TestClient) -> None:
        """Query longer than 500 chars is rejected."""
        resp = search_client.post("/v1/ask", json={
            "query": "x" * 501,
        })
        assert resp.status_code == 422
```

**Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_api/test_search_routes.py::TestAskSkillsPost -v`
Expected: FAIL — POST endpoint doesn't exist yet.

**Step 3: Implement**

3a. Add request models to `server/src/decision_hub/api/search_routes.py` (after the `AskResponse` model, around line 171):

```python
class AskMessage(BaseModel):
    """A single message in the conversation history."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=5000)


class AskRequest(BaseModel):
    """Request body for POST /v1/ask."""

    query: str = Field(max_length=500)
    history: list[AskMessage] = Field(default_factory=list, max_length=20)
```

Add `Literal` to the imports from `typing`.

3b. Add `history` parameter to `ask_conversational()` in `server/src/decision_hub/infra/gemini.py`:

Change the signature from:
```python
def ask_conversational(
    client: dict,
    query: str,
    index: str,
    model: str,
) -> dict:
```
to:
```python
def ask_conversational(
    client: dict,
    query: str,
    index: str,
    model: str,
    history: list[dict] | None = None,
) -> dict:
```

Change the `user_message` construction (line 355) from:
```python
    user_message = f"User question: {query}\n\nAvailable skills:\n{index}"
```
to:
```python
    # Build user message with optional conversation history
    parts = []
    if history:
        parts.append("Conversation so far:")
        for msg in history:
            role_label = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"{role_label}: {msg['content']}")
        parts.append("")  # blank line separator
    parts.append(f"User question: {query}")
    parts.append(f"\nAvailable skills:\n{index}")
    user_message = "\n".join(parts)
```

3c. Refactor: extract the shared ask logic into a `_handle_ask()` helper in `search_routes.py` and wire both GET and POST to it.

Move the body of the current `ask_skills()` into:
```python
def _handle_ask(
    q: str,
    category: str | None,
    history: list[dict] | None,
    settings: Settings,
    conn,
    s3_client,
    current_user: User | None,
) -> AskResponse:
```

The only change inside is passing `history=history` to `ask_conversational()`:
```python
        llm_result = ask_conversational(
            gemini,
            q,
            result.index_content,
            settings.gemini_model,
            history=history,
        )
```

Update the GET handler to delegate:
```python
@router.get(
    "/ask",
    response_model=AskResponse,
    dependencies=[Depends(_enforce_search_rate_limit)],
)
def ask_skills(
    q: str = Query(..., max_length=500),
    category: str | None = Query(None, max_length=100),
    settings: Settings = Depends(get_settings),
    conn=Depends(get_connection),
    s3_client=Depends(get_s3_client),
    current_user: User | None = Depends(get_current_user_optional),
) -> AskResponse:
    """Answer a natural language question with conversational response and skill links."""
    return _handle_ask(q=q, category=category, history=None, settings=settings, conn=conn, s3_client=s3_client, current_user=current_user)
```

Add the POST handler:
```python
@router.post(
    "/ask",
    response_model=AskResponse,
    dependencies=[Depends(_enforce_search_rate_limit)],
)
def ask_skills_post(
    body: AskRequest,
    settings: Settings = Depends(get_settings),
    conn=Depends(get_connection),
    s3_client=Depends(get_s3_client),
    current_user: User | None = Depends(get_current_user_optional),
) -> AskResponse:
    """Multi-turn conversational skill discovery.

    Accepts conversation history so follow-up questions have context.
    The web modal uses this; CLI uses GET for single-shot queries.
    """
    history = [{"role": m.role, "content": m.content} for m in body.history] if body.history else None
    return _handle_ask(q=body.query, category=None, history=history, settings=settings, conn=conn, s3_client=s3_client, current_user=current_user)
```

**Step 4: Run all tests**

Run: `cd server && uv run pytest tests/test_api/test_search_routes.py -v`
Expected: ALL PASS (both old GET tests and new POST tests)

**Step 5: Commit**

```bash
git add server/src/decision_hub/api/search_routes.py server/src/decision_hub/infra/gemini.py server/tests/test_api/test_search_routes.py
git commit -m "feat: add POST /v1/ask with conversation history for multi-turn (#211)"
```

---

### Task 4: Update web modal to use POST with history

**Files:**
- Modify: `frontend/src/api/client.ts:134-138`
- Modify: `frontend/src/components/AskModal.tsx:65-93`
- Modify: `frontend/src/types/api.ts` (add AskMessage type)

**Step 1: Add types**

In `frontend/src/types/api.ts`, add after `AskResponse`:

```typescript
export interface AskMessage {
  role: "user" | "assistant";
  content: string;
}
```

**Step 2: Add POST client function**

In `frontend/src/api/client.ts`, add after the existing `askQuestion`:

```typescript
export async function askQuestionWithHistory(
  query: string,
  history: AskMessage[]
): Promise<AskResponse> {
  return fetchJSON<AskResponse>("/v1/ask", {
    method: "POST",
    body: JSON.stringify({ query, history }),
  });
}
```

Add `AskMessage` to the imports from `../types/api`.

**Step 3: Update AskModal to send history**

In `frontend/src/components/AskModal.tsx`:

Change the import from:
```typescript
import { askQuestion } from "../api/client";
```
to:
```typescript
import { askQuestionWithHistory } from "../api/client";
```

In `handleSubmit`, replace:
```typescript
        const response: AskResponse = await askQuestion(trimmed);
```
with:
```typescript
        // Build history from previous messages (only role + content, no skills)
        const history = messages.map((msg) => ({
          role: msg.role,
          content: msg.content,
        }));
        const response: AskResponse = await askQuestionWithHistory(trimmed, history);
```

**Step 4: Run frontend tests and type check**

Run: `make test-frontend && make lint-frontend`
Expected: PASS

**Step 5: Manual verification**

Start local dev server and test the modal:
1. Open web modal, type "tools for writing linkedin posts" — should get max 5 recommendations with runners-up and context hints
2. Follow up with "I need one for drafting from scratch" — the response should reference the previous conversation

**Step 6: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/api/client.ts frontend/src/components/AskModal.tsx
git commit -m "feat: web modal sends conversation history for multi-turn ask (#211)"
```

---

### Task 5: Run full test suite and verify

**Step 1: Run all tests**

```bash
make test-server && make test-frontend && make lint-frontend
```

Expected: ALL PASS

**Step 2: Run linting**

```bash
make lint && make typecheck
```

Expected: ALL PASS

**Step 3: Final commit (if any fixups needed)**

Only if previous steps revealed issues that needed fixing.
