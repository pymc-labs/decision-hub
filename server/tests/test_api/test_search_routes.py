"""Tests for decision_hub.api.search_routes -- search endpoint."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from decision_hub.api.search_routes import router as search_router

# ---------------------------------------------------------------------------
# Fixtures -- search routes need their own app since the shared conftest
# test_app does not include the search_router.
# ---------------------------------------------------------------------------

_GUARD_PASS = {"is_skill_query": True, "reason": ""}

_SAMPLE_CANDIDATES = [
    {
        "org_slug": "acme",
        "is_personal_org": False,
        "skill_name": "weather",
        "description": "Weather forecasting",
        "download_count": 10,
        "category": "Data Science",
        "visibility": "public",
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
        "latest_version": "2.1.0",
        "eval_status": "pending",
        "created_at": None,
        "published_by": "bob",
    },
]

_FIXED_EMBEDDING = [0.1] * 768


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
    settings.embedding_dimensions = 768
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
# GET /v1/search
# ---------------------------------------------------------------------------


class TestSearchSkills:
    """GET /v1/search?q=... -- LLM-powered skill discovery."""

    def test_search_no_api_key(self, search_app: FastAPI) -> None:
        """Should return 503 when google_api_key is not configured."""
        search_app.state.settings.google_api_key = ""

        client = TestClient(search_app)
        resp = client.get("/v1/search", params={"q": "find me a tool"})

        assert resp.status_code == 503
        assert "GOOGLE_API_KEY" in resp.json()["detail"]

    @respx.mock
    @patch("decision_hub.api.search_routes.check_query_topicality", return_value=_GUARD_PASS)
    @patch("decision_hub.api.search_routes.embed_query", return_value=_FIXED_EMBEDDING)
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    def test_search_success(
        self,
        mock_hybrid: MagicMock,
        _mock_embed: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """End-to-end: hybrid retrieval returns candidates, Gemini reranks them."""
        mock_hybrid.return_value = _SAMPLE_CANDIDATES

        gemini_answer = "1. acme/weather v1.0.0 [A] - Weather forecasting\n2. acme/translate v2.1.0 [C] - Translation"
        gemini_route = respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "candidates": [{"content": {"parts": [{"text": gemini_answer}]}}],
                },
            )
        )

        resp = search_client.get("/v1/search", params={"q": "weather forecast"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "weather forecast"
        assert "acme/weather" in data["results"]
        assert "acme/translate" in data["results"]

        # Verify the candidate index was sent to Gemini
        sent_payload = gemini_route.calls[0].request.content.decode()
        assert "weather" in sent_payload
        assert "translate" in sent_payload

    @patch("decision_hub.api.search_routes.check_query_topicality", return_value=_GUARD_PASS)
    @patch("decision_hub.api.search_routes.embed_query", return_value=_FIXED_EMBEDDING)
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    def test_search_empty_database(
        self,
        mock_hybrid: MagicMock,
        _mock_embed: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """When hybrid retrieval returns no candidates, should return a message without calling the LLM."""
        mock_hybrid.return_value = []

        resp = search_client.get("/v1/search", params={"q": "anything"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "anything"
        assert "No skills matched" in data["results"]

    @patch(
        "decision_hub.api.search_routes.check_query_topicality",
        return_value={"is_skill_query": False, "reason": "cooking recipe"},
    )
    def test_search_off_topic_rejected(
        self,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """Off-topic queries get a friendly rejection without hitting the DB."""
        resp = search_client.get("/v1/search", params={"q": "chocolate cake recipe"})

        assert resp.status_code == 200
        data = resp.json()
        assert "doesn't look like a skill search" in data["results"]
        assert "dhub ask" in data["results"]

    @patch(
        "decision_hub.api.search_routes.check_query_topicality",
        return_value={"is_skill_query": False, "reason": "cooking recipe"},
    )
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    def test_search_off_topic_skips_db(
        self,
        mock_hybrid: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """Off-topic queries short-circuit before the DB query."""
        resp = search_client.get("/v1/search", params={"q": "chocolate cake recipe"})

        assert resp.status_code == 200
        mock_hybrid.assert_not_called()

    @patch("decision_hub.api.search_routes.check_query_topicality", return_value=_GUARD_PASS)
    @patch("decision_hub.api.search_routes.embed_query", side_effect=Exception("API down"))
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    @patch("decision_hub.api.search_routes.search_skills_with_llm", return_value="Gemini result")
    def test_search_embedding_failure_degrades_to_fts(
        self,
        _mock_llm: MagicMock,
        mock_hybrid: MagicMock,
        _mock_embed: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """When embedding fails, search still works with FTS-only (query_embedding=None)."""
        mock_hybrid.return_value = _SAMPLE_CANDIDATES

        resp = search_client.get("/v1/search", params={"q": "weather forecast"})

        assert resp.status_code == 200
        # Verify hybrid was called with query_embedding=None
        call_kwargs = mock_hybrid.call_args
        assert call_kwargs[0][2] is None  # third positional arg is query_embedding

    @patch("decision_hub.api.search_routes.check_query_topicality", return_value=_GUARD_PASS)
    @patch("decision_hub.api.search_routes.embed_query", return_value=_FIXED_EMBEDDING)
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    @patch("decision_hub.api.search_routes.search_skills_with_llm", side_effect=Exception("Gemini down"))
    def test_search_gemini_failure_returns_deterministic(
        self,
        _mock_llm: MagicMock,
        mock_hybrid: MagicMock,
        _mock_embed: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """When Gemini rerank fails, returns deterministic markdown results."""
        mock_hybrid.return_value = _SAMPLE_CANDIDATES

        resp = search_client.get("/v1/search", params={"q": "weather forecast"})

        assert resp.status_code == 200
        data = resp.json()
        # Deterministic fallback uses numbered markdown
        assert "1." in data["results"]
        assert "acme/weather" in data["results"]
        assert "acme/translate" in data["results"]

    @patch("decision_hub.api.search_routes.check_query_topicality", return_value=_GUARD_PASS)
    @patch("decision_hub.api.search_routes.embed_query", return_value=_FIXED_EMBEDDING)
    @patch("decision_hub.api.search_routes.search_skills_hybrid")
    @patch("decision_hub.api.search_routes.search_skills_with_llm", return_value="result")
    def test_search_candidate_limit_passed(
        self,
        _mock_llm: MagicMock,
        mock_hybrid: MagicMock,
        _mock_embed: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
        search_settings: MagicMock,
    ) -> None:
        """Verify search_candidate_limit from settings is forwarded to hybrid search."""
        mock_hybrid.return_value = _SAMPLE_CANDIDATES
        search_settings.search_candidate_limit = 15

        resp = search_client.get("/v1/search", params={"q": "weather"})

        assert resp.status_code == 200
        call_kwargs = mock_hybrid.call_args
        assert call_kwargs[1]["limit"] == 15

    def test_search_rate_limited(self, search_app: FastAPI) -> None:
        """Exceeding the rate limit returns HTTP 429."""
        search_app.state.settings.search_rate_limit = 2
        search_app.state.settings.search_rate_window = 60
        client = TestClient(search_app)

        with patch(
            "decision_hub.api.search_routes.check_query_topicality",
            return_value={"is_skill_query": False, "reason": "off-topic"},
        ):
            # First two requests should succeed (off-topic but allowed by rate limiter)
            for _ in range(2):
                resp = client.get("/v1/search", params={"q": "cake"})
                assert resp.status_code == 200

            # Third request should be rate limited
            resp = client.get("/v1/search", params={"q": "cake"})
            assert resp.status_code == 429
            assert "Rate limit exceeded" in resp.json()["detail"]
