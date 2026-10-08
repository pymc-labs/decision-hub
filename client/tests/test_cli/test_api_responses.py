"""Discovery commands should explain incompatible registries without tracebacks."""

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    monkeypatch.setenv("DHUB_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr("dhub.cli.config.get_api_url", lambda: "https://registry.example")
    monkeypatch.setattr("dhub.cli.config.get_optional_token", lambda: None)


@pytest.mark.parametrize(
    ("command", "path"),
    [
        (["ask", "Bayesian modeling with PyMC"], "/v1/ask"),
        (["list", "--org", "pymc-labs"], "/v1/skills"),
        (["info", "pymc-labs/pymc-modeling"], "/v1/skills/pymc-labs/pymc-modeling/summary"),
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
    route = respx.get(f"https://registry.example{path}").mock(return_value=httpx.Response(200, text=body))

    result = runner.invoke(app, ["--output", output_format, *command])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert route.call_count == 1
    assert "dhub env" in " ".join(result.stderr.split())
    assert "DHUB_API_URL" in result.stderr
    assert "private server diagnostics" not in result.output
    if output_format == "json":
        assert result.stdout == ""
        error = json.loads(result.stderr)
        assert error["code"] == "INVALID_RESPONSE"
        assert error["status"] == 200


@pytest.mark.parametrize("output_format", ["text", "json"])
@respx.mock
def test_list_rejects_missing_pagination_fields(output_format):
    respx.get("https://registry.example/v1/skills").mock(return_value=httpx.Response(200, json={"items": []}))

    result = runner.invoke(app, ["--output", output_format, "list"])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "dhub env" in " ".join(result.stderr.split())
