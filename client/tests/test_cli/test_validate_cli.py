"""CLI contracts for offline SKILL.md validation."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()
VALID_MANIFEST = "---\nname: forecast\ndescription: Forecast demand: daily totals\n---\nRun the forecast.\n"


def test_validate_defaults_to_current_directory_offline(tmp_path, monkeypatch, respx_mock):
    monkeypatch.chdir(tmp_path)
    Path("SKILL.md").write_text(VALID_MANIFEST)

    with patch("dhub.cli.version_check.show_update_notice") as update_check:
        result = runner.invoke(app, ["validate"])

    assert result.exit_code == 0
    assert "forecast" in result.stdout
    assert "SKILL.md" in result.stdout
    assert result.stderr == ""
    update_check.assert_not_called()
    assert not respx_mock.calls


@pytest.mark.parametrize("source", ["skill", "skill/SKILL.md"])
def test_validate_json_success(tmp_path, monkeypatch, source):
    monkeypatch.chdir(tmp_path)
    Path("skill").mkdir()
    Path("skill/SKILL.md").write_text(VALID_MANIFEST)

    result = runner.invoke(app, ["--output", "json", "validate", source])

    assert result.exit_code == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == {"valid": True, "name": "forecast", "path": "skill/SKILL.md"}


@pytest.mark.parametrize(
    ("content", "diagnostic"),
    [
        ("# No frontmatter", "must start with ---"),
        ("---\nname: forecast\n---\nBody", "Required field 'description'"),
        ("---\nname: [unterminated\n---\nBody", "line"),
        ("---\nname: forecast\ndescription: Demand\n---\n", "Body (system prompt)"),
    ],
)
def test_validate_json_parser_error(tmp_path, content, diagnostic):
    path = tmp_path / "SKILL.md"
    path.write_text(content)

    result = runner.invoke(app, ["--output", "json", "validate", str(path)])

    assert result.exit_code == 1
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["error"] is True
    assert error["code"] == "VALIDATION_ERROR"
    assert str(path) in error["message"]
    assert diagnostic in error["message"]


def test_validate_text_preserves_parser_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("SKILL.md").write_text("---\nname: '[bold]'\ndescription: Demand\n---\nBody")

    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "SKILL.md" in result.stderr
    assert "Invalid name '[bold]'" in result.stderr


@pytest.mark.parametrize(
    ("source", "code", "expected_path"),
    [
        ("empty", "NOT_FOUND", "empty/SKILL.md"),
        ("missing", "NOT_FOUND", "missing"),
        ("README.md", "VALIDATION_ERROR", "README.md"),
    ],
)
def test_validate_json_path_error(tmp_path, monkeypatch, source, code, expected_path):
    monkeypatch.chdir(tmp_path)
    Path("empty").mkdir()
    Path("README.md").write_text(VALID_MANIFEST)

    result = runner.invoke(app, ["--output", "json", "validate", source])

    assert result.exit_code == 1
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["error"] is True
    assert error["code"] == code
    assert expected_path in error["message"]
