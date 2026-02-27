"""Tests for the topicality guard in decision_hub.infra.gemini."""

import json

import httpx
import pytest
import respx

from decision_hub.infra.gemini import check_query_topicality, create_gemini_client, parse_query_with_guard

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


@pytest.fixture
def gemini_client() -> dict:
    return create_gemini_client("test-api-key")


class TestTopicalityGuard:
    """Unit tests for check_query_topicality."""

    @respx.mock
    def test_on_topic_query(self, gemini_client: dict) -> None:
        """On-topic queries return is_skill_query=True."""
        respx.post(_GEMINI_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": json.dumps({"is_skill_query": True, "reason": "asks about data tools"})}
                                ]
                            }
                        }
                    ]
                },
            )
        )

        result = check_query_topicality(gemini_client, "data validation library", model="gemini-2.5-flash")
        assert result["is_skill_query"] is True

    @respx.mock
    def test_off_topic_query(self, gemini_client: dict) -> None:
        """Off-topic queries return is_skill_query=False with reason preserved."""
        respx.post(_GEMINI_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": json.dumps({"is_skill_query": False, "reason": "cooking recipe"})}]
                            }
                        }
                    ]
                },
            )
        )

        result = check_query_topicality(gemini_client, "chocolate cake recipe", model="gemini-2.5-flash")
        assert result["is_skill_query"] is False
        assert result["reason"] == "cooking recipe"

    @respx.mock
    def test_guard_fails_open_on_api_error(self, gemini_client: dict) -> None:
        """API errors fail open -- query is allowed through."""
        respx.post(_GEMINI_URL).mock(return_value=httpx.Response(500))

        result = check_query_topicality(gemini_client, "anything", model="gemini-2.5-flash")
        assert result["is_skill_query"] is True
        assert result["reason"] == "guard_error"

    @respx.mock
    def test_guard_fails_open_on_malformed_json(self, gemini_client: dict) -> None:
        """Malformed JSON fails open -- query is allowed through."""
        respx.post(_GEMINI_URL).mock(
            return_value=httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "not valid json at all"}]}}]},
            )
        )

        result = check_query_topicality(gemini_client, "anything", model="gemini-2.5-flash")
        assert result["is_skill_query"] is True
        assert result["reason"] == "guard_error"

    @respx.mock
    def test_guard_strips_markdown_fences(self, gemini_client: dict) -> None:
        """JSON wrapped in markdown code fences is parsed correctly."""
        fenced = '```json\n{"is_skill_query": false, "reason": "poetry request"}\n```'
        respx.post(_GEMINI_URL).mock(
            return_value=httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": fenced}]}}]},
            )
        )

        result = check_query_topicality(gemini_client, "write me a poem", model="gemini-2.5-flash")
        assert result["is_skill_query"] is False
        assert result["reason"] == "poetry request"


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

        result = parse_query_with_guard(gemini_client, "data validation library", model="gemini-2.5-flash")
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

        result = parse_query_with_guard(gemini_client, "chocolate cake recipe", model="gemini-2.5-flash")
        assert result.is_skill_query is False
        assert result.fts_queries == []

    @respx.mock
    def test_fails_open_on_api_error(self, gemini_client: dict) -> None:
        """API errors fail open with fallback keywords."""
        respx.post(_GEMINI_URL).mock(return_value=httpx.Response(500))

        result = parse_query_with_guard(gemini_client, "anything useful", model="gemini-2.5-flash")
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

        result = parse_query_with_guard(gemini_client, "find a tool", model="gemini-2.5-flash")
        assert result.is_skill_query is True
        assert result.fts_queries == ["find a tool"]
