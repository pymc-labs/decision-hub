"""Tests for the topicality guard in decision_hub.infra.gemini."""

import json

import httpx
import pytest
import respx
from slow_helpers import LatencyTracker, get_default_gemini_model, load_google_api_key, timed

from decision_hub.infra.gemini import create_gemini_client, parse_query_with_guard

_DEFAULT_MODEL = get_default_gemini_model()
_GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{_DEFAULT_MODEL}:generateContent"


@pytest.fixture
def gemini_client() -> dict:
    return create_gemini_client("test-api-key")


class TestParseQueryWithGuard:
    """Unit tests for the combined parse_query_with_guard."""

    @respx.mock
    def test_on_topic_with_keywords(self, gemini_client: dict) -> None:
        """On-topic queries return is_skill_query=True with extracted keywords."""
        respx.post(_GEMINI_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": json.dumps(
                                            {
                                                "is_skill_query": True,
                                                "reason": "asks about data tools",
                                                "fts_queries": [
                                                    "data validation",
                                                    "data quality",
                                                    "validation library",
                                                ],
                                            }
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                },
            )
        )

        result = parse_query_with_guard(gemini_client, "data validation library", model=_DEFAULT_MODEL)
        assert result.is_skill_query is True
        assert result.fts_queries == ["data validation", "data quality", "validation library"]

    @respx.mock
    def test_off_topic_returns_empty_keywords(self, gemini_client: dict) -> None:
        """Off-topic queries return is_skill_query=False with empty fts_queries."""
        respx.post(_GEMINI_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": json.dumps(
                                            {
                                                "is_skill_query": False,
                                                "reason": "cooking recipe",
                                                "fts_queries": [],
                                            }
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                },
            )
        )

        result = parse_query_with_guard(gemini_client, "chocolate cake recipe", model=_DEFAULT_MODEL)
        assert result.is_skill_query is False
        assert result.fts_queries == []

    @respx.mock
    def test_fails_open_on_api_error(self, gemini_client: dict) -> None:
        """API errors fail open with fallback keywords."""
        respx.post(_GEMINI_URL).mock(return_value=httpx.Response(500))

        result = parse_query_with_guard(gemini_client, "anything useful", model=_DEFAULT_MODEL)
        assert result.is_skill_query is True
        assert result.reason == "guard_error"
        assert result.fts_queries == ["anything useful"]

    @respx.mock
    def test_on_topic_empty_keywords_falls_back_to_query(self, gemini_client: dict) -> None:
        """On-topic but empty fts_queries falls back to the raw query."""
        respx.post(_GEMINI_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": json.dumps(
                                            {
                                                "is_skill_query": True,
                                                "reason": "tool search",
                                                "fts_queries": [],
                                            }
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                },
            )
        )

        result = parse_query_with_guard(gemini_client, "find a tool", model=_DEFAULT_MODEL)
        assert result.is_skill_query is True
        assert result.fts_queries == ["find a tool"]


# ---------------------------------------------------------------------------
# Golden-set tests hitting real Gemini API
# ---------------------------------------------------------------------------

_ON_TOPIC_QUERIES = [
    "find a data validation library",
    "recommend a tool for deploying to Kubernetes",
    "what's the best skill for generating React components?",
    "compare testing frameworks for browser automation",
    "I need a CSV parser that handles large files",
]

_OFF_TOPIC_QUERIES = [
    "how do I make chocolate chip cookies?",
    "what is the capital of France?",
    "explain quantum computing in simple terms",
    "write me a poem about the ocean",
    "what's the weather like today?",
]


@pytest.mark.slow
class TestTopicalityGuardGoldenSet:
    """Real-LLM golden set tests for topicality classification.

    Skipped automatically when no GOOGLE_API_KEY is available.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        api_key = load_google_api_key()
        if not api_key:
            pytest.skip("GOOGLE_API_KEY not available")
        self.client = create_gemini_client(api_key)
        self.model = get_default_gemini_model()
        self.latency = LatencyTracker("topicality_guard", soft_p95_limit=10.0)
        yield
        print(self.latency.summary())

    @pytest.mark.parametrize("query", _ON_TOPIC_QUERIES)
    def test_on_topic(self, query: str) -> None:
        with timed(self.latency):
            result = parse_query_with_guard(self.client, query, model=self.model)
        assert result.is_skill_query is True, (
            f"Expected on-topic for '{query}', got is_skill_query=False (reason: {result.reason})"
        )
        assert len(result.fts_queries) > 0, f"On-topic query '{query}' should produce fts_queries"

    @pytest.mark.parametrize("query", _OFF_TOPIC_QUERIES)
    def test_off_topic(self, query: str) -> None:
        with timed(self.latency):
            result = parse_query_with_guard(self.client, query, model=self.model)
        assert result.is_skill_query is False, (
            f"Expected off-topic for '{query}', got is_skill_query=True (reason: {result.reason})"
        )
