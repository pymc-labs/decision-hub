"""Tests for `dhub env` command — display the active environment."""

import json
from unittest.mock import patch

from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


@patch("dhub.cli.env.config_file", return_value="/tmp/dhub-config-dev.json")
@patch("dhub.cli.env.get_api_url", return_value="https://hub-dev.decision.ai")
@patch("dhub.cli.env.get_env", return_value="dev")
def test_env_command_prints_env_config_url(_mock_env, _mock_url, _mock_cfg) -> None:
    """The default human-readable output contains environment, config path, and API URL."""
    result = runner.invoke(app, ["env"])

    assert result.exit_code == 0
    assert "Environment: dev" in result.output
    assert "Config: /tmp/dhub-config-dev.json" in result.output
    assert "API URL: https://hub-dev.decision.ai" in result.output


@patch("dhub.cli.env.config_file", return_value="/tmp/dhub-config-dev.json")
@patch("dhub.cli.env.get_api_url", return_value="https://hub-dev.decision.ai")
@patch("dhub.cli.env.get_env", return_value="dev")
def test_env_command_emits_json_when_output_json(_mock_env, _mock_url, _mock_cfg) -> None:
    """``--output json`` emits a parseable JSON object with the same fields."""
    result = runner.invoke(app, ["--output", "json", "env"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {
        "environment": "dev",
        "config_file": "/tmp/dhub-config-dev.json",
        "api_url": "https://hub-dev.decision.ai",
    }
