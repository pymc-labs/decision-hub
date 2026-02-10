"""Tests for dhub logs command."""

from unittest.mock import patch

import httpx
import respx
from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()

API_URL = "https://test-api.example.com"


def _mock_config():
    """Patch config functions to return test values."""
    return [
        patch("dhub.cli.registry.console"),
    ]


@respx.mock
@patch("dhub.cli.config.get_api_url", return_value=API_URL)
@patch("dhub.cli.config.get_token", return_value="test-token")
def test_logs_no_args_lists_runs(mock_token, mock_url):
    """dhub logs with no args lists recent runs."""
    respx.get(f"{API_URL}/v1/eval-runs").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "version_id": "11111111-2222-3333-4444-555555555555",
                    "agent": "claude",
                    "judge_model": "claude-sonnet",
                    "status": "completed",
                    "stage": "judge",
                    "current_case": "basic",
                    "current_case_index": 1,
                    "total_cases": 2,
                    "heartbeat_at": None,
                    "log_seq": 5,
                    "error_message": None,
                    "created_at": "2024-01-01T00:00:00",
                    "completed_at": "2024-01-01T00:05:00",
                }
            ],
        )
    )

    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0


@respx.mock
@patch("dhub.cli.config.get_api_url", return_value=API_URL)
@patch("dhub.cli.config.get_token", return_value="test-token")
def test_logs_follow_tails_and_exits_on_completed(mock_token, mock_url):
    """dhub logs <run-id> --follow tails events and exits when completed."""
    run_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    # First call: verify run exists
    respx.get(f"{API_URL}/v1/eval-runs/{run_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": run_id,
                "version_id": "v1",
                "agent": "claude",
                "judge_model": "m",
                "status": "completed",
                "stage": None,
                "current_case": None,
                "current_case_index": None,
                "total_cases": 1,
                "heartbeat_at": None,
                "log_seq": 2,
                "error_message": None,
                "created_at": "2024-01-01T00:00:00",
                "completed_at": "2024-01-01T00:05:00",
            },
        )
    )

    # Logs endpoint returns events then completed status
    respx.get(f"{API_URL}/v1/eval-runs/{run_id}/logs").mock(
        return_value=httpx.Response(
            200,
            json={
                "events": [
                    {"seq": 1, "type": "setup", "content": "Starting...", "ts": "2024-01-01T00:00:00Z"},
                    {
                        "seq": 2,
                        "type": "report",
                        "passed": 1,
                        "total": 1,
                        "status": "completed",
                        "total_duration_ms": 5000,
                        "ts": "2024-01-01T00:05:00Z",
                    },
                ],
                "next_cursor": 2,
                "run_status": "completed",
                "run_stage": None,
                "current_case": None,
            },
        )
    )

    result = runner.invoke(app, ["logs", run_id, "--follow"])
    assert result.exit_code == 0


@respx.mock
@patch("dhub.cli.config.get_api_url", return_value=API_URL)
@patch("dhub.cli.config.get_token", return_value="test-token")
def test_logs_no_runs_found(mock_token, mock_url):
    """dhub logs with no args and no runs shows message."""
    respx.get(f"{API_URL}/v1/eval-runs").mock(return_value=httpx.Response(200, json=[]))

    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0
