"""Discovery commands should explain incompatible registries without tracebacks."""

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from dhub.cli.app import app
from dhub.cli.output import OutputFormat, set_format

runner = CliRunner()

REGISTRY = "https://registry.example"
SUMMARY_PATH = "/v1/skills/pymc-labs/pymc-modeling/summary"


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    monkeypatch.setenv("DHUB_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr("dhub.cli.config.get_api_url", lambda: REGISTRY)
    monkeypatch.setattr("dhub.cli.config.get_optional_token", lambda: None)
    yield
    # The output format is process-global; don't leak JSON mode into later tests.
    set_format(OutputFormat.text)


def _assert_invalid_response(result, output_format: str, status: int = 200) -> None:
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "dhub env" in " ".join(result.stderr.split())
    assert "DHUB_API_URL" in result.stderr
    if output_format == "json":
        assert result.stdout == ""
        error = json.loads(result.stderr)
        assert error["code"] == "INVALID_RESPONSE"
        assert error["status"] == status


@pytest.mark.parametrize(
    ("command", "path"),
    [
        (["ask", "Bayesian modeling with PyMC"], "/v1/ask"),
        (["list", "--org", "pymc-labs"], "/v1/skills"),
        (["info", "pymc-labs/pymc-modeling"], SUMMARY_PATH),
    ],
)
@pytest.mark.parametrize("output_format", ["text", "json"])
@pytest.mark.parametrize(
    "body",
    [
        "<html>private server diagnostics</html>",
        "",
        '{"incomplete":',
        "[]",
        "null",
        '"unexpected string"',
    ],
)
@respx.mock
def test_discovery_rejects_invalid_response(command, path, output_format, body):
    route = respx.get(f"{REGISTRY}{path}").mock(return_value=httpx.Response(200, text=body))

    result = runner.invoke(app, ["--output", output_format, *command])

    assert route.call_count == 1
    _assert_invalid_response(result, output_format)
    assert "private server diagnostics" not in result.output


@pytest.mark.parametrize("output_format", ["text", "json"])
@pytest.mark.parametrize(
    "payload",
    [
        {"items": []},
        {"items": None, "total": 1, "total_pages": 1},
        {"items": [], "total": 1, "total_pages": None},
        {"items": [], "total": "1", "total_pages": 1},
    ],
)
@respx.mock
def test_list_rejects_missing_or_mistyped_pagination_fields(output_format, payload):
    respx.get(f"{REGISTRY}/v1/skills").mock(return_value=httpx.Response(200, json=payload))

    result = runner.invoke(app, ["--output", output_format, "list"])

    _assert_invalid_response(result, output_format)


@pytest.mark.parametrize("output_format", ["text", "json"])
@pytest.mark.parametrize(
    "payload",
    [
        {"query": "q"},
        {"query": "q", "answer": None, "skills": []},
        {"answer": "a", "skills": []},
    ],
)
@respx.mock
def test_ask_rejects_missing_or_mistyped_fields(output_format, payload):
    respx.get(f"{REGISTRY}/v1/ask").mock(return_value=httpx.Response(200, json=payload))

    result = runner.invoke(app, ["--output", output_format, "ask", "q"])

    _assert_invalid_response(result, output_format)


@pytest.mark.parametrize(("command", "path"), [(["ask", "q"], "/v1/ask"), (["list"], "/v1/skills")])
@pytest.mark.parametrize("output_format", ["text", "json"])
@respx.mock
def test_discovery_endpoint_404_means_incompatible_registry(command, path, output_format):
    respx.get(f"{REGISTRY}{path}").mock(return_value=httpx.Response(404, json={"detail": "Not Found"}))

    result = runner.invoke(app, ["--output", output_format, *command])

    _assert_invalid_response(result, output_format, status=404)


@respx.mock
def test_ask_503_is_structured_in_json_mode():
    respx.get(f"{REGISTRY}/v1/ask").mock(return_value=httpx.Response(503))

    result = runner.invoke(app, ["--output", "json", "ask", "q"])

    assert result.exit_code == 1
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["code"] == "SERVICE_UNAVAILABLE"
    assert error["status"] == 503


@respx.mock
def test_info_404_is_structured_in_json_mode():
    respx.get(f"{REGISTRY}{SUMMARY_PATH}").mock(return_value=httpx.Response(404))

    result = runner.invoke(app, ["--output", "json", "info", "pymc-labs/pymc-modeling"])

    assert result.exit_code == 1
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["code"] == "NOT_FOUND"
    assert error["status"] == 404


@pytest.mark.parametrize(
    "body",
    ["<html>fallback</html>", "[]", '"unexpected string"'],
)
@pytest.mark.parametrize("output_format", ["text", "json"])
@respx.mock
def test_info_degrades_when_optional_sections_are_incompatible(body, output_format):
    """Audit-log and eval-report are best-effort: odd bodies must not abort ``info``."""
    respx.get(f"{REGISTRY}{SUMMARY_PATH}").mock(
        return_value=httpx.Response(200, json={"latest_version": "1.0.0", "download_count": 1})
    )
    base = f"{REGISTRY}/v1/skills/pymc-labs/pymc-modeling"
    respx.get(f"{base}/audit-log").mock(return_value=httpx.Response(200, text=body))
    respx.get(f"{base}/eval-report").mock(return_value=httpx.Response(200, text=body))

    result = runner.invoke(app, ["--output", output_format, "info", "pymc-labs/pymc-modeling"])

    assert result.exit_code == 0, result.output
    if output_format == "json":
        data = json.loads(result.stdout)
        assert data["audit_log"] is None
        assert data["eval_report"] is None


@respx.mock
def test_info_json_stdout_stays_parseable_when_optional_fetch_fails():
    respx.get(f"{REGISTRY}{SUMMARY_PATH}").mock(return_value=httpx.Response(200, json={"latest_version": "1.0.0"}))
    base = f"{REGISTRY}/v1/skills/pymc-labs/pymc-modeling"
    respx.get(f"{base}/audit-log").mock(side_effect=httpx.ConnectError("boom"))
    respx.get(f"{base}/eval-report").mock(side_effect=httpx.ConnectError("boom"))

    result = runner.invoke(app, ["--output", "json", "info", "pymc-labs/pymc-modeling"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["audit_log"] is None
    assert data["eval_report"] is None
