"""Tests for dhub.cli.keys -- API key management commands."""

from unittest.mock import patch

import httpx
import respx
from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


class TestAddKey:
    @respx.mock
    @patch("dhub.cli.keys.typer.prompt", return_value="sk-secret-value")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_add_key_success(self, _mock_url, _mock_token, _mock_prompt):
        route = respx.post("http://test:8000/v1/keys").mock(return_value=httpx.Response(201, json={}))
        result = runner.invoke(app, ["keys", "add", "MY_KEY"])
        assert result.exit_code == 0
        assert "Added key: MY_KEY" in result.output
        assert route.called
        request = route.calls.last.request
        assert b"MY_KEY" in request.content
        assert b"sk-secret-value" in request.content

    @respx.mock
    @patch("dhub.cli.keys.typer.prompt", return_value="sk-secret-value")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_add_key_409_conflict(self, _mock_url, _mock_token, _mock_prompt):
        respx.post("http://test:8000/v1/keys").mock(return_value=httpx.Response(409))
        result = runner.invoke(app, ["keys", "add", "MY_KEY"])
        assert result.exit_code == 1
        assert "already exists" in result.output


class TestListKeys:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_keys_with_results(self, _mock_url, _mock_token):
        keys = [
            {"key_name": "OPENAI_API_KEY", "created_at": "2025-01-15T10:00:00Z"},
            {"key_name": "ANTHROPIC_KEY", "created_at": "2025-01-16T12:00:00Z"},
        ]
        respx.get("http://test:8000/v1/keys").mock(return_value=httpx.Response(200, json=keys))
        result = runner.invoke(app, ["keys", "list"])
        assert result.exit_code == 0
        assert "OPENAI_API_KEY" in result.output
        assert "ANTHROPIC_KEY" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_keys_empty(self, _mock_url, _mock_token):
        respx.get("http://test:8000/v1/keys").mock(return_value=httpx.Response(200, json=[]))
        result = runner.invoke(app, ["keys", "list"])
        assert result.exit_code == 0
        assert "No API keys stored" in result.output


class TestRemoveKey:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_remove_key_success(self, _mock_url, _mock_token):
        respx.delete("http://test:8000/v1/keys/MY_KEY").mock(return_value=httpx.Response(204))
        result = runner.invoke(app, ["keys", "remove", "MY_KEY"])
        assert result.exit_code == 0
        assert "Removed key: MY_KEY" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_remove_key_404(self, _mock_url, _mock_token):
        respx.delete("http://test:8000/v1/keys/MY_KEY").mock(return_value=httpx.Response(404))
        result = runner.invoke(app, ["keys", "remove", "MY_KEY"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()
