"""Tests for dhub doctor command."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


class TestDoctorCommand:
    @respx.mock
    @patch("dhub.cli.doctor.get_optional_token", return_value="test-token")
    @patch("dhub.cli.doctor.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.doctor.load_config")
    @patch("dhub.cli.doctor.get_client_version", return_value="0.6.0")
    def test_doctor_json_authenticated(self, _mock_ver, _mock_config, _mock_url, _mock_token) -> None:
        from dhub.cli.config import CliConfig

        _mock_config.return_value = CliConfig(
            api_url="http://test:8000",
            token="test-token",
            orgs=("acme",),
            default_org="acme",
        )
        respx.get("http://test:8000/health").mock(
            return_value=httpx.Response(200, json={"status": "ok", "database": "ok"})
        )

        result = runner.invoke(app, ["--output", "json", "doctor"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["authenticated"] is True
        assert data["org"] == "acme"
        assert data["api_reachable"] is True
        assert data["cli_version"] == "0.6.0"

    @respx.mock
    @patch("dhub.cli.doctor.get_optional_token", return_value=None)
    @patch("dhub.cli.doctor.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.doctor.load_config")
    @patch("dhub.cli.doctor.get_client_version", return_value="0.6.0")
    def test_doctor_not_authenticated(self, _mock_ver, _mock_config, _mock_url, _mock_token) -> None:
        from dhub.cli.config import CliConfig

        _mock_config.return_value = CliConfig(api_url="http://test:8000")
        respx.get("http://test:8000/health").mock(
            return_value=httpx.Response(200, json={"status": "ok", "database": "ok"})
        )

        result = runner.invoke(app, ["--output", "json", "doctor"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["authenticated"] is False

    @respx.mock
    @patch("dhub.cli.doctor.get_optional_token", return_value="test-token")
    @patch("dhub.cli.doctor.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.doctor.load_config")
    @patch("dhub.cli.doctor.get_client_version", return_value="0.6.0")
    def test_doctor_text_mode(self, _mock_ver, _mock_config, _mock_url, _mock_token) -> None:
        from dhub.cli.config import CliConfig

        _mock_config.return_value = CliConfig(
            api_url="http://test:8000",
            token="test-token",
            orgs=("acme",),
            default_org="acme",
        )
        respx.get("http://test:8000/health").mock(
            return_value=httpx.Response(200, json={"status": "ok", "database": "ok"})
        )

        result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Authenticated" in result.output
        assert "API reachable" in result.output

    @respx.mock
    @patch("dhub.cli.doctor.get_optional_token", return_value=None)
    @patch("dhub.cli.doctor.get_api_url", return_value="http://unreachable:9999")
    @patch("dhub.cli.doctor.load_config")
    @patch("dhub.cli.doctor.get_client_version", return_value="0.6.0")
    def test_doctor_api_unreachable(self, _mock_ver, _mock_config, _mock_url, _mock_token) -> None:
        from dhub.cli.config import CliConfig

        _mock_config.return_value = CliConfig(api_url="http://unreachable:9999")
        respx.get("http://unreachable:9999/health").mock(side_effect=httpx.ConnectError("Connection refused"))

        result = runner.invoke(app, ["--output", "json", "doctor"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["api_reachable"] is False
        assert data["api_latency_ms"] == 0

    @respx.mock
    @patch("dhub.cli.doctor.get_optional_token", return_value="test-token")
    @patch("dhub.cli.doctor.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.doctor.load_config")
    @patch("dhub.cli.doctor.get_client_version", return_value="0.6.0")
    def test_doctor_org_from_single_org(self, _mock_ver, _mock_config, _mock_url, _mock_token) -> None:
        """When default_org is None but there's exactly one org, use it."""
        from dhub.cli.config import CliConfig

        _mock_config.return_value = CliConfig(
            api_url="http://test:8000",
            token="test-token",
            orgs=("solo-org",),
            default_org=None,
        )
        respx.get("http://test:8000/health").mock(
            return_value=httpx.Response(200, json={"status": "ok", "database": "ok"})
        )

        result = runner.invoke(app, ["--output", "json", "doctor"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["org"] == "solo-org"


@pytest.mark.parametrize("output_format", ["text", "json"])
@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, "<html>website fallback</html>"),
        (200, ""),
        (200, '{"status":'),
        (200, "[]"),
        (200, "null"),
        (200, '"ok"'),
        (200, '{"unrelated": "ok"}'),
        (200, '{"status": "ok"}'),
        (200, '{"status": "degraded", "database": "unreachable"}'),
        (200, '{"status": "ok", "database": "unreachable"}'),
        (503, '{"status": "ok", "database": "ok"}'),
        (302, '{"status": "ok", "database": "ok"}'),
    ],
)
@respx.mock
def test_doctor_rejects_invalid_health_response(monkeypatch, output_format, status, body):
    from dhub.cli.config import CliConfig

    monkeypatch.setenv("DHUB_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr("dhub.cli.doctor.get_api_url", lambda: "https://registry.example")
    monkeypatch.setattr("dhub.cli.doctor.get_optional_token", lambda: None)
    monkeypatch.setattr("dhub.cli.doctor.load_config", lambda: CliConfig())
    respx.get("https://registry.example/health").mock(return_value=httpx.Response(status, text=body))

    result = runner.invoke(app, ["--output", output_format, "doctor"])

    assert result.exit_code == 0
    if output_format == "json":
        assert json.loads(result.stdout)["api_reachable"] is False
    else:
        api_check = next(line for line in result.stdout.splitlines() if "API reachable" in line)
        assert "FAIL" in api_check
        assert "OK" not in api_check
