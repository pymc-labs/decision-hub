"""Tests for dhub.cli.org -- organization management commands."""

from unittest.mock import patch

import httpx
import respx
from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# org list
# ---------------------------------------------------------------------------


class TestListOrgs:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_orgs_with_results(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        orgs = [
            {"slug": "alpha-org"},
            {"slug": "beta-org"},
        ]
        respx.get("http://test:8000/v1/orgs").mock(return_value=httpx.Response(200, json=orgs))

        result = runner.invoke(app, ["org", "list"])

        assert result.exit_code == 0
        assert "alpha-org" in result.output
        assert "beta-org" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_orgs_empty(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.get("http://test:8000/v1/orgs").mock(return_value=httpx.Response(200, json=[]))

        result = runner.invoke(app, ["org", "list"])

        assert result.exit_code == 0
        assert "No namespaces available" in result.output
