"""Tests for decision_hub.api.search_routes -- ask endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from decision_hub.api.search_routes import router as search_router
from decision_hub.infra.gemini import GuardAndParseResult

# ---------------------------------------------------------------------------
# Fixtures -- search routes need their own app since the shared conftest
# test_app does not include the search_router.
# ---------------------------------------------------------------------------

_GUARD_PASS = GuardAndParseResult(
    is_skill_query=True,
    reason="",
    fts_queries=["weather forecast"],
)

_GUARD_OFF_TOPIC = GuardAndParseResult(
    is_skill_query=False,
    reason="cooking recipe",
    fts_queries=[],
)

_SAMPLE_CANDIDATES = [
    {
        "org_slug": "acme",
        "is_personal_org": False,
        "skill_name": "weather",
        "description": "Weather forecasting",
        "download_count": 10,
        "category": "Data Science",
        "visibility": "public",
        "source_repo_url": "https://github.com/acme/weather-skill",
        "latest_version": "1.0.0",
        "eval_status": "passed",
        "created_at": None,
        "published_by": "alice",
    },
    {
        "org_slug": "acme",
        "is_personal_org": False,
        "skill_name": "translate",
        "description": "Language translation",
        "download_count": 5,
        "category": "Content & Writing",
        "visibility": "public",
        "source_repo_url": None,
        "latest_version": "2.1.0",
        "eval_status": "pending",
        "created_at": None,
        "published_by": "bob",
    },
]

_FIXED_EMBEDDING = [0.1] * 768

_LLM_RESULT = {
    "answer": "Here are the matching skills: acme/weather for forecasting and acme/translate for translation.",
    "referenced_skills": [
        {"org_slug": "acme", "skill_name": "weather", "reason": "Weather forecasting skill"},
        {"org_slug": "acme", "skill_name": "translate", "reason": "Translation skill"},
    ],
}


@pytest.fixture
def search_settings() -> MagicMock:
    """Mocked Settings with google_api_key and gemini_model configured."""
    settings = MagicMock()
    settings.google_api_key = "test-google-api-key"
    settings.gemini_model = "gemini-pro"
    settings.s3_bucket = "test-bucket"
    settings.search_rate_limit = 100
    settings.search_rate_window = 60
    settings.search_candidate_limit = 20
    settings.embedding_model = "gemini-embedding-001"
    return settings


@pytest.fixture
def search_app(search_settings: MagicMock) -> FastAPI:
    """FastAPI test app with only the search router included."""
    app = FastAPI()
    app.state.settings = search_settings
    app.state.engine = MagicMock()
    app.state.s3_client = MagicMock()
    app.include_router(search_router)
    return app


@pytest.fixture
def search_client(search_app: FastAPI) -> TestClient:
    return TestClient(search_app)


# ---------------------------------------------------------------------------
# GET /v1/ask
# ---------------------------------------------------------------------------


class TestAskSkills:
    """GET /v1/ask?q=... -- conversational skill discovery."""

    def test_ask_no_api_key(self, search_app: FastAPI) -> None:
        """Should return 503 when google_api_key is not configured."""
        search_app.state.settings.google_api_key = ""

        client = TestClient(search_app)
        resp = client.get("/v1/ask", params={"q": "find me a tool"})

        assert resp.status_code == 503
        assert "GOOGLE_API_KEY" in resp.json()["detail"]

    @patch("decision_hub.api.search_routes.parse_query_with_guard", return_value=_GUARD_PASS)
    @patch("decision_hub.api.search_routes.embed_query", return_value=_FIXED_EMBEDDING)
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    @patch("decision_hub.api.search_routes.ask_conversational")
    def test_ask_success(
        self,
        mock_llm: MagicMock,
        mock_hybrid: MagicMock,
        _mock_embed: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """End-to-end: hybrid retrieval returns candidates, Gemini generates structured response."""
        mock_hybrid.return_value = _SAMPLE_CANDIDATES
        mock_llm.return_value = _LLM_RESULT

        resp = search_client.get("/v1/ask", params={"q": "weather forecast"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "weather forecast"
        assert "acme/weather" in data["answer"]
        assert len(data["skills"]) == 2
        assert data["skills"][0]["org_slug"] == "acme"
        assert data["skills"][0]["skill_name"] == "weather"
        # Verify enrichment from DB (description comes from candidates, not LLM)
        assert data["skills"][0]["description"] == "Weather forecasting"
        assert data["skills"][0]["safety_rating"] == "A"
        # Verify additional metadata fields are present
        assert data["skills"][0]["author"] == "alice"
        assert data["skills"][0]["category"] == "Data Science"
        assert data["skills"][0]["download_count"] == 10
        assert data["skills"][0]["latest_version"] == "1.0.0"
        assert data["skills"][0]["source_repo_url"] == "https://github.com/acme/weather-skill"

    @patch("decision_hub.api.search_routes.parse_query_with_guard", return_value=_GUARD_PASS)
    @patch("decision_hub.api.search_routes.embed_query", return_value=_FIXED_EMBEDDING)
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    def test_ask_empty_database(
        self,
        mock_hybrid: MagicMock,
        _mock_embed: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """When hybrid retrieval returns no candidates, should return a message without calling the LLM."""
        mock_hybrid.return_value = []

        resp = search_client.get("/v1/ask", params={"q": "anything"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "anything"
        assert "couldn't find any skills" in data["answer"]
        assert data["skills"] == []

    @patch("decision_hub.api.search_routes.parse_query_with_guard", return_value=_GUARD_OFF_TOPIC)
    def test_ask_off_topic_rejected(
        self,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """Off-topic queries get a friendly rejection with empty skills."""
        resp = search_client.get("/v1/ask", params={"q": "chocolate cake recipe"})

        assert resp.status_code == 200
        data = resp.json()
        assert "doesn't look like a skill" in data["answer"]
        assert data["skills"] == []

    @patch("decision_hub.api.search_routes.parse_query_with_guard", return_value=_GUARD_OFF_TOPIC)
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    def test_ask_off_topic_skips_db(
        self,
        mock_hybrid: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """Off-topic queries short-circuit before the DB query."""
        resp = search_client.get("/v1/ask", params={"q": "chocolate cake recipe"})

        assert resp.status_code == 200
        mock_hybrid.assert_not_called()

    @patch("decision_hub.api.search_routes.parse_query_with_guard", return_value=_GUARD_PASS)
    @patch("decision_hub.api.search_routes.embed_query", return_value=_FIXED_EMBEDDING)
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    @patch("decision_hub.api.search_routes.ask_conversational", side_effect=Exception("Gemini down"))
    def test_ask_gemini_failure_returns_fallback(
        self,
        _mock_llm: MagicMock,
        mock_hybrid: MagicMock,
        _mock_embed: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """When Gemini fails, returns fallback with top-5 skills from retrieval."""
        mock_hybrid.return_value = _SAMPLE_CANDIDATES

        resp = search_client.get("/v1/ask", params={"q": "weather forecast"})

        assert resp.status_code == 200
        data = resp.json()
        assert "most relevant skills" in data["answer"]
        assert len(data["skills"]) == 2
        assert data["skills"][0]["org_slug"] == "acme"
        assert data["skills"][0]["skill_name"] == "weather"

    @patch("decision_hub.api.search_routes.parse_query_with_guard", return_value=_GUARD_PASS)
    @patch("decision_hub.api.search_routes.embed_query", return_value=_FIXED_EMBEDDING)
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    @patch("decision_hub.api.search_routes.ask_conversational")
    def test_ask_category_param_forwarded(
        self,
        mock_llm: MagicMock,
        mock_hybrid: MagicMock,
        _mock_embed: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """Category parameter is forwarded to hybrid search and included in response."""
        mock_hybrid.return_value = _SAMPLE_CANDIDATES
        mock_llm.return_value = _LLM_RESULT

        resp = search_client.get("/v1/ask", params={"q": "weather", "category": "Data Science"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "Data Science"
        # Verify category was forwarded to hybrid search
        call_kwargs = mock_hybrid.call_args
        assert call_kwargs[1]["category"] == "Data Science"

    def test_ask_rate_limited(self, search_app: FastAPI) -> None:
        """Exceeding the rate limit returns HTTP 429."""
        search_app.state.settings.search_rate_limit = 2
        search_app.state.settings.search_rate_window = 60
        client = TestClient(search_app)

        with patch(
            "decision_hub.api.search_routes.parse_query_with_guard",
            return_value=_GUARD_OFF_TOPIC,
        ):
            # First two requests should succeed (off-topic but allowed by rate limiter)
            for _ in range(2):
                resp = client.get("/v1/ask", params={"q": "cake"})
                assert resp.status_code == 200

            # Third request should be rate limited
            resp = client.get("/v1/ask", params={"q": "cake"})
            assert resp.status_code == 429
            assert "Rate limit exceeded" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /v1/ask
# ---------------------------------------------------------------------------


class TestAskSkillsPost:
    """POST /v1/ask -- multi-turn conversational skill discovery."""

    @patch("decision_hub.api.search_routes.parse_query_with_guard", return_value=_GUARD_PASS)
    @patch("decision_hub.api.search_routes.embed_query", return_value=_FIXED_EMBEDDING)
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    @patch("decision_hub.api.search_routes.ask_conversational")
    def test_post_ask_success(
        self,
        mock_llm: MagicMock,
        mock_hybrid: MagicMock,
        _mock_embed: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """POST with history passes conversation context to LLM."""
        mock_hybrid.return_value = _SAMPLE_CANDIDATES
        mock_llm.return_value = _LLM_RESULT

        resp = search_client.post(
            "/v1/ask",
            json={
                "query": "I need the drafting one",
                "history": [
                    {"role": "user", "content": "linkedin post tools"},
                    {"role": "assistant", "content": "Here are my top picks..."},
                ],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "I need the drafting one"
        assert len(data["skills"]) == 2
        # POST intentionally omits category (no category filter param)
        assert data.get("category") is None
        # Verify history was passed to ask_conversational
        call_kwargs = mock_llm.call_args
        assert call_kwargs[1]["history"] is not None
        assert len(call_kwargs[1]["history"]) == 2

    @patch("decision_hub.api.search_routes.parse_query_with_guard", return_value=_GUARD_PASS)
    @patch("decision_hub.api.search_routes.embed_query", return_value=_FIXED_EMBEDDING)
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    @patch("decision_hub.api.search_routes.ask_conversational")
    def test_post_ask_empty_history(
        self,
        mock_llm: MagicMock,
        mock_hybrid: MagicMock,
        _mock_embed: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """POST with empty history works like GET (single-shot)."""
        mock_hybrid.return_value = _SAMPLE_CANDIDATES
        mock_llm.return_value = _LLM_RESULT

        resp = search_client.post(
            "/v1/ask",
            json={
                "query": "weather forecast",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "weather forecast"
        assert len(data["skills"]) == 2

    @patch("decision_hub.api.search_routes.parse_query_with_guard", return_value=_GUARD_OFF_TOPIC)
    def test_post_ask_off_topic_rejected(
        self,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """Off-topic queries via POST get a friendly rejection with empty skills."""
        resp = search_client.post("/v1/ask", json={"query": "chocolate cake recipe"})

        assert resp.status_code == 200
        data = resp.json()
        assert "doesn't look like a skill" in data["answer"]
        assert data["skills"] == []

    def test_post_ask_validates_query_length(self, search_client: TestClient) -> None:
        """Query longer than 500 chars is rejected."""
        resp = search_client.post(
            "/v1/ask",
            json={
                "query": "x" * 501,
            },
        )
        assert resp.status_code == 422


class TestLogAskAnalyticsOrdering:
    """_log_ask_analytics must write the DB row before uploading to S3.

    Regression: previously the S3 upload ran first, so an insert failure
    (unique-violation, DB down, constraint change) left an orphaned blob
    in the search-logs prefix with nothing pointing to it. Order matters
    for the whole reverse-lookup / cleanup story to work.
    """

    def _run_log(self, *, upload_side_effect=None, insert_side_effect=None):
        """Invoke _log_ask_analytics with mocked collaborators and return the recording mocks."""
        from unittest.mock import MagicMock, patch
        from uuid import uuid4

        from decision_hub.api.search_routes import _log_ask_analytics

        engine = MagicMock()
        s3_client = MagicMock()
        log_id = uuid4()
        recorder = MagicMock()

        def _insert(*args, **kwargs):
            recorder("insert_search_log")
            if insert_side_effect is not None:
                raise insert_side_effect

        def _upload(*args, **kwargs):
            recorder("upload_search_log")
            if upload_side_effect is not None:
                raise upload_side_effect
            return "search-logs/2026-07-28/fake.json"

        with (
            patch("decision_hub.api.search_routes.insert_search_log", side_effect=_insert) as mock_insert,
            patch("decision_hub.api.search_routes.upload_search_log", side_effect=_upload) as mock_upload,
        ):
            _log_ask_analytics(
                engine=engine,
                s3_client=s3_client,
                s3_bucket="test-bucket",
                log_id=log_id,
                query="test",
                answer="answer",
                results_count=3,
                model="gemini-pro",
                latency_ms=42,
                user_id=None,
                username=None,
            )
        return mock_insert, mock_upload, recorder

    def test_insert_runs_before_upload_on_happy_path(self) -> None:
        _mock_insert, _mock_upload, recorder = self._run_log()

        names = [c.args[0] for c in recorder.call_args_list]
        assert names == ["insert_search_log", "upload_search_log"], (
            "DB insert must precede the S3 upload so a failed insert never leaves an orphan blob"
        )

    def test_upload_is_not_called_when_insert_fails(self) -> None:
        """A DB insert failure must prevent the S3 upload entirely — otherwise
        we produce the orphaned blob this ordering exists to avoid."""
        _mock_insert, mock_upload, _recorder = self._run_log(
            insert_side_effect=RuntimeError("insert failed"),
        )
        mock_upload.assert_not_called()

    def test_upload_failure_does_not_prevent_insert(self) -> None:
        """A failure on the S3 upload leaves the DB row in place — the row
        still points to a well-formed s3_key that can be re-uploaded later,
        which is the recoverable failure mode we want to keep."""
        mock_insert, _mock_upload, _recorder = self._run_log(
            upload_side_effect=RuntimeError("S3 unreachable"),
        )
        mock_insert.assert_called_once()
        # The s3_key argument must be present and non-empty even before upload.
        _args, kwargs = mock_insert.call_args
        assert kwargs["s3_key"], "s3_key must be pre-computed and persisted before upload"
