"""Tests for the topicality guard in decision_hub.infra.gemini."""

import json

import httpx
import pytest
import respx

from decision_hub.infra.gemini import check_query_topicality, create_gemini_client

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent"


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

        result = check_query_topicality(gemini_client, "data validation library", model="gemini-3-flash-preview")
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

        result = check_query_topicality(gemini_client, "chocolate cake recipe", model="gemini-3-flash-preview")
        assert result["is_skill_query"] is False
        assert result["reason"] == "cooking recipe"

    @respx.mock
    def test_guard_fails_open_on_api_error(self, gemini_client: dict) -> None:
        """API errors fail open -- query is allowed through."""
        respx.post(_GEMINI_URL).mock(return_value=httpx.Response(500))

        result = check_query_topicality(gemini_client, "anything", model="gemini-3-flash-preview")
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

        result = check_query_topicality(gemini_client, "anything", model="gemini-3-flash-preview")
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

        result = check_query_topicality(gemini_client, "write me a poem", model="gemini-3-flash-preview")
        assert result["is_skill_query"] is False
        assert result["reason"] == "poetry request"
