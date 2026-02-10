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


@pytest.fixture
def search_settings() -> MagicMock:
    """Mocked Settings with google_api_key and gemini_model configured."""
    settings = MagicMock()
    settings.google_api_key = "test-google-api-key"
    settings.gemini_model = "gemini-pro"
    settings.s3_bucket = "test-bucket"
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
    @patch("decision_hub.api.search_routes.check_query_topicality", return_value={"is_skill_query": True, "reason": ""})
    @patch("decision_hub.api.search_routes.fetch_all_skills_for_index")
    def test_search_success(
        self,
        mock_fetch: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """End-to-end ask flow: canned DB rows through real domain logic and Gemini response parsing."""
        mock_fetch.return_value = [
            {
                "org_slug": "acme",
                "skill_name": "weather",
                "description": "Weather forecasting",
                "latest_version": "1.0.0",
                "eval_status": "passed",
                "published_by": "alice",
            },
            {
                "org_slug": "acme",
                "skill_name": "translate",
                "description": "Language translation",
                "latest_version": "2.1.0",
                "eval_status": "pending",
                "published_by": "bob",
            },
        ]

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

        # Verify the real index was built and sent to Gemini
        sent_payload = gemini_route.calls[0].request.content.decode()
        assert "weather" in sent_payload
        assert "translate" in sent_payload

    @respx.mock
    @patch("decision_hub.api.search_routes.check_query_topicality", return_value={"is_skill_query": True, "reason": ""})
    @patch("decision_hub.api.search_routes.fetch_all_skills_for_index")
    def test_search_gemini_empty_candidates(
        self,
        mock_fetch: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """When Gemini returns no candidates, the fallback message propagates through the route."""
        mock_fetch.return_value = [
            {
                "org_slug": "acme",
                "skill_name": "weather",
                "description": "Weather forecasting",
                "latest_version": "1.0.0",
                "eval_status": "passed",
                "published_by": "alice",
            },
        ]
        respx.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent").mock(
            return_value=httpx.Response(200, json={"candidates": []})
        )

        resp = search_client.get("/v1/search", params={"q": "something obscure"})

        assert resp.status_code == 200
        assert "No recommendations found" in resp.json()["results"]

    @patch("decision_hub.api.search_routes.check_query_topicality", return_value={"is_skill_query": True, "reason": ""})
    @patch("decision_hub.api.search_routes.fetch_all_skills_for_index")
    def test_search_empty_database(
        self,
        mock_fetch: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """When the database has no skills, should return a message without calling the LLM."""
        mock_fetch.return_value = []

        resp = search_client.get("/v1/search", params={"q": "anything"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "anything"
        assert "No skills" in data["results"]

    @patch("decision_hub.api.search_routes.check_query_topicality", return_value={"is_skill_query": False, "reason": "off-topic"})
    def test_search_off_topic_rejected(
        self,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """Off-topic queries are rejected before hitting the DB or main LLM."""
        resp = search_client.get(
            "/v1/search", params={"q": "chocolate cake recipe"}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "chocolate cake recipe"
        assert "doesn't look like a skill search" in data["results"]
        assert "dhub ask" in data["results"]

    @patch("decision_hub.api.search_routes.check_query_topicality", return_value={"is_skill_query": False, "reason": "off-topic"})
    @patch("decision_hub.api.search_routes.fetch_all_skills_for_index")
    def test_search_off_topic_skips_db(
        self,
        mock_fetch: MagicMock,
        _mock_guard: MagicMock,
        search_client: TestClient,
    ) -> None:
        """Off-topic rejection must not query the database at all."""
        search_client.get("/v1/search", params={"q": "tell me a joke"})

        mock_fetch.assert_not_called()


class TestTopicalityGuard:
    """Unit tests for check_query_topicality Gemini guard."""

    @respx.mock
    def test_on_topic_query(self) -> None:
        from decision_hub.infra.gemini import check_query_topicality, create_gemini_client

        respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        ).mock(return_value=httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": '{"is_skill_query": true, "reason": "asks about data tools"}'}]}}],
        }))

        client = create_gemini_client("fake-key")
        result = check_query_topicality(client, "data validation library")

        assert result["is_skill_query"] is True

    @respx.mock
    def test_off_topic_query(self) -> None:
        from decision_hub.infra.gemini import check_query_topicality, create_gemini_client

        respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        ).mock(return_value=httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": '{"is_skill_query": false, "reason": "cooking recipe"}'}]}}],
        }))

        client = create_gemini_client("fake-key")
        result = check_query_topicality(client, "chocolate cake recipe")

        assert result["is_skill_query"] is False
        assert "cooking" in result["reason"]

    @respx.mock
    def test_guard_fails_open_on_api_error(self) -> None:
        """When the guard API call fails, queries should pass through (fail-open)."""
        from decision_hub.infra.gemini import check_query_topicality, create_gemini_client

        respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        ).mock(return_value=httpx.Response(500))

        client = create_gemini_client("fake-key")
        result = check_query_topicality(client, "anything")

        assert result["is_skill_query"] is True
        assert result["reason"] == "guard_error"

    @respx.mock
    def test_guard_fails_open_on_malformed_json(self) -> None:
        """When the guard returns unparseable JSON, queries should pass through."""
        from decision_hub.infra.gemini import check_query_topicality, create_gemini_client

        respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        ).mock(return_value=httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "not valid json at all"}]}}],
        }))

        client = create_gemini_client("fake-key")
        result = check_query_topicality(client, "anything")

        assert result["is_skill_query"] is True
        assert result["reason"] == "guard_error"

    @respx.mock
    def test_guard_strips_markdown_fences(self) -> None:
        """Guard should handle responses wrapped in markdown code fences."""
        from decision_hub.infra.gemini import check_query_topicality, create_gemini_client

        respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        ).mock(return_value=httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": '```json\n{"is_skill_query": false, "reason": "off-topic"}\n```'}]}}],
        }))

        client = create_gemini_client("fake-key")
        result = check_query_topicality(client, "write me a poem")

        assert result["is_skill_query"] is False
