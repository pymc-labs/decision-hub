"""Tests for dhub.cli.search -- ask command."""

import json
from unittest.mock import patch

import httpx
import respx
from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()

_ASK_RESPONSE = {
    "query": "analyze A/B test results",
    "answer": "Here are skills for A/B testing: acme/ab-test-analyzer is the best match.",
    "skills": [
        {
            "org_slug": "acme",
            "skill_name": "ab-test-analyzer",
            "description": "Analyze A/B test results",
            "safety_rating": "A",
            "reason": "Directly relevant to A/B testing",
        },
        {
            "org_slug": "acme",
            "skill_name": "stats-runner",
            "description": "Statistical analysis",
            "safety_rating": "B",
            "reason": "General statistics tool",
        },
    ],
    "category": None,
}


# ---------------------------------------------------------------------------
# ask_command tests
# ---------------------------------------------------------------------------


class TestAskCommand:
    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_ask_success(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.get("http://test:8000/v1/ask").mock(return_value=httpx.Response(200, json=_ASK_RESPONSE))

        result = runner.invoke(app, ["ask", "analyze A/B test results"])

        assert result.exit_code == 0
        assert "analyze A/B test results" in result.output
        assert "ab-test-analyzer" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_ask_503_not_configured(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.get("http://test:8000/v1/ask").mock(return_value=httpx.Response(503))

        result = runner.invoke(app, ["ask", "some query"])

        assert result.exit_code == 1
        assert "not available" in result.output.lower()

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value=None)
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_ask_does_not_require_auth(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """ask should work even when the user is not logged in."""
        response = {
            "query": "test query",
            "answer": "Some answer here.",
            "skills": [],
            "category": None,
        }
        respx.get("http://test:8000/v1/ask").mock(return_value=httpx.Response(200, json=response))

        result = runner.invoke(app, ["ask", "test query"])

        assert result.exit_code == 0
        assert "test query" in result.output

    def test_ask_empty_query(self) -> None:
        """Typer should reject a missing query argument."""
        result = runner.invoke(app, ["ask"])

        # Typer exits with code 2 for missing required arguments
        assert result.exit_code == 2
        assert "Missing argument" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_ask_with_category(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Category filter is forwarded as query parameter."""
        response = {
            "query": "data science",
            "answer": "Found skills in Data Science category.",
            "skills": [],
            "category": "Data Science",
        }
        route = respx.get("http://test:8000/v1/ask").mock(return_value=httpx.Response(200, json=response))

        result = runner.invoke(app, ["ask", "data science", "--category", "Data Science"])

        assert result.exit_code == 0
        # Verify the category was sent as a query parameter
        assert "category=Data+Science" in str(route.calls[0].request.url)

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_ask_json_output(self, _mock_url, _mock_token) -> None:
        respx.get("http://test:8000/v1/ask").mock(return_value=httpx.Response(200, json=_ASK_RESPONSE))
        result = runner.invoke(app, ["--output", "json", "ask", "analyze A/B test results"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["query"] == "analyze A/B test results"
        assert len(data["skills"]) == 2

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_ask_shows_skills_table(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """When skills are returned, they should be displayed in a table."""
        respx.get("http://test:8000/v1/ask").mock(return_value=httpx.Response(200, json=_ASK_RESPONSE))

        result = runner.invoke(app, ["ask", "analyze A/B test results"])

        assert result.exit_code == 0
        # The table should show skill names and grades
        assert "acme/ab-test-analyzer" in result.output
        assert "acme/stats-runner" in result.output
        assert "Referenced Skills" in result.output
