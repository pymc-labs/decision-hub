"""Tests for decision_hub.api.search_routes -- search endpoint."""

from unittest.mock import MagicMock, patch

import pytest
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

    @patch("decision_hub.api.search_routes.search_skills_with_llm")
    @patch("decision_hub.api.search_routes.create_gemini_client")
    @patch("decision_hub.api.search_routes.fetch_all_skills_for_index")
    def test_search_success(
        self,
        mock_fetch: MagicMock,
        mock_create_gemini: MagicMock,
        mock_search_llm: MagicMock,
        search_client: TestClient,
    ) -> None:
        """Full search flow: DB has skills, Gemini returns recommendations."""
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
        mock_create_gemini.return_value = {"api_key": "test-key"}
        mock_search_llm.return_value = "acme/weather v1.0.0 - weather forecasting skill"

        resp = search_client.get("/v1/search", params={"q": "weather forecast"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "weather forecast"
        assert "weather" in data["results"]

        # Verify the LLM was called with index content built from DB rows
        mock_search_llm.assert_called_once()
        call_args = mock_search_llm.call_args
        assert "weather" in call_args[0][2]  # index_content contains skill data

    @patch("decision_hub.api.search_routes.fetch_all_skills_for_index")
    def test_search_empty_database(
        self,
        mock_fetch: MagicMock,
        search_client: TestClient,
    ) -> None:
        """When the database has no skills, should return a message without calling the LLM."""
        mock_fetch.return_value = []

        resp = search_client.get("/v1/search", params={"q": "anything"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "anything"
        assert "No skills" in data["results"]
