"""Tests for infra/anthropic_client.py -- LLM judge for agent evals."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx

from decision_hub.infra.anthropic_client import _parse_judge_response, judge_eval_output


class TestParseJudgeResponse:
    def test_valid_pass(self):
        raw = json.dumps({"verdict": "pass", "reasoning": "Agent did well"})
        result = _parse_judge_response(raw)
        assert result["verdict"] == "pass"
        assert result["reasoning"] == "Agent did well"

    def test_valid_fail(self):
        raw = json.dumps({"verdict": "fail", "reasoning": "Agent missed checks"})
        result = _parse_judge_response(raw)
        assert result["verdict"] == "fail"

    def test_invalid_json(self):
        result = _parse_judge_response("not json at all")
        assert result["verdict"] == "error"
        assert "Failed to parse" in result["reasoning"]

    def test_invalid_verdict(self):
        raw = json.dumps({"verdict": "maybe", "reasoning": "unclear"})
        result = _parse_judge_response(raw)
        assert result["verdict"] == "error"
        assert "Invalid verdict" in result["reasoning"]

    def test_missing_verdict(self):
        raw = json.dumps({"reasoning": "no verdict field"})
        result = _parse_judge_response(raw)
        assert result["verdict"] == "error"


class TestJudgeEvalOutput:
    @respx.mock
    def test_successful_judge_call(self) -> None:
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"text": json.dumps({"verdict": "pass", "reasoning": "Good output"})}],
                },
            )
        )

        result = judge_eval_output(
            api_key="test-api-key",
            model="claude-sonnet-4-5-20250929",
            eval_case_name="test-case",
            eval_criteria="PASS: has output\nFAIL: no output",
            agent_output="The analysis shows...",
        )

        assert result["verdict"] == "pass"
        assert result["reasoning"] == "Good output"

        # Verify the real request was built correctly
        request = route.calls[0].request
        assert request.headers["x-api-key"] == "test-api-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        payload = json.loads(request.content)
        assert payload["model"] == "claude-sonnet-4-5-20250929"
        assert payload["system"] is not None
        assert "test-case" in payload["messages"][0]["content"]

    @respx.mock
    def test_truncates_long_output(self) -> None:
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"text": json.dumps({"verdict": "pass", "reasoning": "ok"})}],
                },
            )
        )

        long_output = "x" * 20000

        judge_eval_output(
            api_key="test-key",
            model="test-model",
            eval_case_name="test",
            eval_criteria="criteria",
            agent_output=long_output,
        )

        # Verify output was truncated in the request
        payload = json.loads(route.calls[0].request.content)
        user_content = payload["messages"][0]["content"]
        assert "truncated" in user_content
        assert len(user_content) < 15000

    @respx.mock
    def test_api_error_propagates(self) -> None:
        """httpx errors should propagate up after retries are exhausted."""
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(500, text="Server Error")
        )

        with patch("decision_hub.infra.anthropic_client.time.sleep"), pytest.raises(httpx.HTTPStatusError):
            judge_eval_output(
                api_key="test-key",
                model="test-model",
                eval_case_name="test",
                eval_criteria="criteria",
                agent_output="output",
            )
        # Retry attempts: 1 initial + 3 retries = 4 total requests.
        assert route.call_count == 4

    @respx.mock
    def test_retries_on_429_then_succeeds(self) -> None:
        """A transient rate-limit response should not fail the judge case."""
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            side_effect=[
                httpx.Response(429, text="Rate limited"),
                httpx.Response(
                    200,
                    json={
                        "content": [{"text": json.dumps({"verdict": "pass", "reasoning": "ok"})}],
                    },
                ),
            ]
        )

        with patch("decision_hub.infra.anthropic_client.time.sleep") as mock_sleep:
            result = judge_eval_output(
                api_key="test-key",
                model="test-model",
                eval_case_name="test",
                eval_criteria="criteria",
                agent_output="output",
            )

        assert result["verdict"] == "pass"
        assert route.call_count == 2
        mock_sleep.assert_called_once()

    @respx.mock
    def test_non_retriable_status_returns_immediately(self) -> None:
        """A 400 must not consume the retry budget — fail fast."""
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(400, text="Bad request")
        )

        with (
            patch("decision_hub.infra.anthropic_client.time.sleep") as mock_sleep,
            pytest.raises(httpx.HTTPStatusError),
        ):
            judge_eval_output(
                api_key="test-key",
                model="test-model",
                eval_case_name="test",
                eval_criteria="criteria",
                agent_output="output",
            )
        assert route.call_count == 1
        mock_sleep.assert_not_called()
