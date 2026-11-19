"""CLI contract for looking up skills related to a published skill."""

import json

import httpx
import pytest
from typer.testing import CliRunner

from dhub.cli.app import app
from dhub.cli.config import get_client_version
from dhub.cli.output import OutputFormat, set_format

runner = CliRunner()
REGISTRY = "https://registry.example"
REF = "acme/forecast"
URL = f"{REGISTRY}/v1/skills/{REF}/similar"
MATCHES = [
    {
        "org_slug": "tools",
        "skill_name": "time-series",
        "description": "Fit a [seasonal] model.",
        "safety_rating": "A",
        "category": "Statistics",
        "download_count": 9,
    },
    {
        "org_slug": "acme",
        "skill_name": "regression",
        "description": "Fit a trend.",
        "safety_rating": "B",
        "category": "",
        "download_count": 30,
    },
]


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DHUB_API_URL", REGISTRY)
    monkeypatch.setenv("DHUB_NO_UPDATE_CHECK", "1")
    monkeypatch.delenv("DHUB_TOKEN", raising=False)
    monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
    yield
    set_format(OutputFormat.text)


def test_similar_text_shows_ranked_commands_and_descriptions(respx_mock):
    route = respx_mock.get(URL).respond(json=MATCHES)

    result = runner.invoke(app, ["similar", REF])

    assert result.exit_code == 0, result.output
    assert result.stdout.index("dhub info tools/time-series") < result.stdout.index("dhub info acme/regression")
    assert MATCHES[0]["description"] in result.stdout
    assert route.call_count == 1
    headers = route.calls.last.request.headers
    assert "authorization" not in headers
    assert headers["X-DHub-Client-Version"] == get_client_version()


def test_similar_json_preserves_registry_order_and_fields(respx_mock, monkeypatch):
    monkeypatch.setenv("DHUB_TOKEN", "test-token")
    route = respx_mock.get(URL).respond(json=MATCHES)

    result = runner.invoke(app, ["--output", "json", "similar", REF])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == MATCHES
    assert result.stderr == ""
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-token"


@pytest.mark.parametrize("output_format", ["text", "json"])
def test_similar_empty_result_is_success(respx_mock, output_format):
    respx_mock.get(URL).respond(json=[])

    result = runner.invoke(app, ["--output", output_format, "similar", REF])

    assert result.exit_code == 0, result.output
    if output_format == "json":
        assert json.loads(result.stdout) == []
    else:
        assert "no similar skills" in result.stdout.lower()
        assert REF in result.stdout


@pytest.mark.parametrize("ref", ["forecast", "acme/", "/forecast", "acme/forecast/extra"])
def test_similar_rejects_invalid_ref_before_request(respx_mock, ref):
    result = runner.invoke(app, ["--output", "json", "similar", ref])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr)["code"] == "VALIDATION_ERROR"
    assert not respx_mock.calls


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "AUTH_REQUIRED"),
        (403, "PERMISSION_DENIED"),
        (404, "NOT_FOUND"),
        (426, "UPGRADE_REQUIRED"),
        (429, "SERVICE_UNAVAILABLE"),
        (503, "SERVICE_UNAVAILABLE"),
    ],
)
def test_similar_http_error(respx_mock, status, code):
    respx_mock.get(URL).respond(status, text="private diagnostics")

    result = runner.invoke(app, ["--output", "json", "similar", REF])

    assert result.exit_code == 1
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert (error["code"], error["status"]) == (code, status)
    assert "private diagnostics" not in result.stderr


@pytest.mark.parametrize("body", ["<html>fallback</html>", '{"items":[]}', '[{"skill_name":"x"}]', "[null]"])
@pytest.mark.parametrize("output_format", ["text", "json"])
def test_similar_rejects_incompatible_response(respx_mock, body, output_format):
    respx_mock.get(URL).respond(text=body)

    result = runner.invoke(app, ["--output", output_format, "similar", REF])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "dhub env" in " ".join(result.stderr.split())
    if output_format == "json":
        assert json.loads(result.stderr)["code"] == "INVALID_RESPONSE"


def test_similar_connection_error(respx_mock):
    respx_mock.get(URL).mock(side_effect=httpx.ConnectError("private diagnostics"))

    result = runner.invoke(app, ["--output", "json", "similar", REF])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr)["code"] == "SERVICE_UNAVAILABLE"
    assert "private diagnostics" not in result.stderr
