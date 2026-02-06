"""Tests for infra/anthropic_client.py -- LLM judge for agent evals."""

import json
from unittest.mock import MagicMock, patch

import pytest

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

    @patch("decision_hub.infra.anthropic_client.httpx.post")
    def test_successful_judge_call(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "content": [{"text": json.dumps({"verdict": "pass", "reasoning": "Good output"})}],
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = judge_eval_output(
            api_key="test-api-key",
            model="claude-sonnet-4-5-20250929",
            eval_case_name="test-case",
            eval_criteria="PASS: has output\nFAIL: no output",
            agent_output="The analysis shows...",
        )

        assert result["verdict"] == "pass"
        assert result["reasoning"] == "Good output"

        # Verify the API was called correctly
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["headers"]["x-api-key"] == "test-api-key"
        payload = call_kwargs.kwargs["json"]
        assert payload["model"] == "claude-sonnet-4-5-20250929"

    @patch("decision_hub.infra.anthropic_client.httpx.post")
    def test_truncates_long_output(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "content": [{"text": json.dumps({"verdict": "pass", "reasoning": "ok"})}],
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        long_output = "x" * 20000

        judge_eval_output(
            api_key="test-key",
            model="test-model",
            eval_case_name="test",
            eval_criteria="criteria",
            agent_output=long_output,
        )

        # Verify output was truncated in the request
        call_kwargs = mock_post.call_args
        user_content = call_kwargs.kwargs["json"]["messages"][0]["content"]
        assert "truncated" in user_content
        # Should be much less than 20000 chars
        assert len(user_content) < 15000

    @patch("decision_hub.infra.anthropic_client.httpx.post")
    def test_api_error_propagates(self, mock_post: MagicMock) -> None:
        """httpx errors should propagate up."""
        import httpx
        mock_post.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock()
        )

        with pytest.raises(httpx.HTTPStatusError):
            judge_eval_output(
                api_key="test-key",
                model="test-model",
                eval_case_name="test",
                eval_criteria="criteria",
                agent_output="output",
            )
