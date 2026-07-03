"""Tests for infra/anthropic_client.py -- LLM judge for agent evals."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx

from decision_hub.infra.anthropic_client import (
    _first_text_block,
    _parse_judge_response,
    judge_eval_output,
)


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


class TestFirstTextBlock:
    def test_returns_text_from_text_block(self):
        assert _first_text_block({"content": [{"type": "text", "text": "hello"}]}) == "hello"

    def test_skips_non_text_blocks(self):
        # Response blocks may include tool_use / thinking — the judge only
        # cares about the first genuine text block.
        data = {
            "content": [
                {"type": "tool_use", "id": "toolu_1"},
                {"type": "text", "text": "verdict-here"},
            ],
        }
        assert _first_text_block(data) == "verdict-here"

    def test_returns_none_when_absent(self):
        assert _first_text_block({"content": [{"type": "tool_use"}]}) is None
        assert _first_text_block({"content": []}) is None


class TestJudgeEvalOutput:
    @respx.mock
    def test_successful_judge_call(self) -> None:
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": json.dumps({"verdict": "pass", "reasoning": "Good output"})}],
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
                    "content": [{"type": "text", "text": json.dumps({"verdict": "pass", "reasoning": "ok"})}],
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
        """5xx errors are retried, but eventually raise HTTPStatusError once the
        retry budget is exhausted. Sleep is patched so the test stays fast."""
        respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(500, text="Server Error"))

        with patch("decision_hub.infra.anthropic_client.time.sleep"), pytest.raises(httpx.HTTPStatusError):
            judge_eval_output(
                api_key="test-key",
                model="test-model",
                eval_case_name="test",
                eval_criteria="criteria",
                agent_output="output",
            )

    @respx.mock
    def test_retries_on_429_then_succeeds(self) -> None:
        """Bursty judge loads hitting 429 should transparently retry rather
        than surfacing verdict='error' rows the way the code used to."""
        good = {"content": [{"type": "text", "text": json.dumps({"verdict": "pass", "reasoning": "ok"})}]}
        responses = [
            httpx.Response(429, headers={"retry-after": "0"}),
            httpx.Response(200, json=good),
        ]
        respx.post("https://api.anthropic.com/v1/messages").mock(side_effect=responses)

        with patch("decision_hub.infra.anthropic_client.time.sleep") as sleep_mock:
            result = judge_eval_output(
                api_key="test-key",
                model="test-model",
                eval_case_name="test",
                eval_criteria="criteria",
                agent_output="output",
            )
        assert result["verdict"] == "pass"
        # Ensure we honored the Retry-After header (slept exactly once before
        # the retry).
        assert sleep_mock.call_count == 1

    @respx.mock
    def test_no_text_block_returns_error_verdict(self) -> None:
        """A response with only tool_use / thinking blocks used to crash on
        `content[0]['text']`; now it returns a graceful error verdict."""
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json={"content": [{"type": "tool_use"}]}),
        )
        result = judge_eval_output(
            api_key="test-key",
            model="test-model",
            eval_case_name="test",
            eval_criteria="criteria",
            agent_output="output",
        )
        assert result["verdict"] == "error"
