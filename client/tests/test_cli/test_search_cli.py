"""Tests for dhub.cli.search -- ask command."""

from unittest.mock import patch

import httpx
import respx
from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# ask_command tests
# ---------------------------------------------------------------------------


class TestAskCommand:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_ask_success(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.get("http://test:8000/v1/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "query": "analyze A/B test results",
                    "results": "Found 3 matching skills:\n- ab-test-analyzer\n- stats-runner\n- experiment-tools",
                },
            )
        )

        result = runner.invoke(app, ["ask", "analyze A/B test results"])

        assert result.exit_code == 0
        assert "analyze A/B test results" in result.output
        assert "ab-test-analyzer" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_ask_503_not_configured(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.get("http://test:8000/v1/search").mock(return_value=httpx.Response(503))

        result = runner.invoke(app, ["ask", "some query"])

        assert result.exit_code == 1
        assert "not available" in result.output.lower()

    def test_ask_empty_query(self) -> None:
        """Typer should reject a missing query argument."""
        result = runner.invoke(app, ["ask"])

        # Typer exits with code 2 for missing required arguments
        assert result.exit_code == 2
        assert "Missing argument" in result.output
