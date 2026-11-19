"""CLI regression tests for local skill inventory."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import respx
from typer.testing import CliRunner

from dhub.cli.app import app
from dhub.core import install

runner = CliRunner()


@pytest.fixture
def skills_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".dhub" / "skills"
    monkeypatch.setattr(install, "get_skills_root", lambda: root)
    monkeypatch.setattr(
        install,
        "AGENT_SKILL_PATHS",
        {name: tmp_path / name / "skills" for name in ("cursor", "codex")},
    )
    monkeypatch.setenv("DHUB_NO_UPDATE_CHECK", "1")
    return root


@respx.mock
def test_installed_lists_local_versions_and_current_links(skills_root: Path) -> None:
    for ref in ("team/model", "labs/model", "labs/forecast"):
        path = skills_root / ref
        path.mkdir(parents=True)
        (path / "SKILL.md").touch()
    install.save_installed_version("labs", "model", "1.2.3")
    (skills_root / "labs/forecast/.dhub-version").write_text("0.9.0\n")
    install.link_skill_to_agent("team", "model", "codex")
    install.link_skill_to_agent("labs", "model", "codex")
    install.link_skill_to_agent("labs", "model", "cursor")

    result = runner.invoke(app, ["--output", "json", "installed"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [
        {"ref": "labs/forecast", "version": "0.9.0", "agents": []},
        {"ref": "labs/model", "version": "1.2.3", "agents": ["codex", "cursor"]},
        {"ref": "team/model", "version": None, "agents": []},
    ]

    result = runner.invoke(app, ["installed"])
    assert result.exit_code == 0, result.output
    rows = result.stdout.splitlines()
    assert any("labs/model" in row and "1.2.3" in row and "codex, cursor" in row for row in rows)
    assert any("team/model" in row and "unknown" in row and "none" in row for row in rows)
    assert not respx.calls


@respx.mock
def test_installed_empty_state(skills_root: Path) -> None:
    with patch("dhub.cli.version_check.show_update_notice") as update_check:
        result = runner.invoke(app, ["installed"])
    update_check.assert_not_called()
    assert result.exit_code == 0, result.output
    assert "No skills installed." in result.stdout
    assert not skills_root.exists()

    (skills_root / "team" / "partial").mkdir(parents=True)
    result = runner.invoke(app, ["--output", "json", "installed"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []
    assert not respx.calls


@pytest.mark.parametrize("metadata", ["null", "{}", '{"version": 7}', "not-a-version"])
def test_installed_shows_unknown_for_unreadable_version_metadata(skills_root: Path, metadata: str) -> None:
    path = skills_root / "team" / "model"
    path.mkdir(parents=True)
    (path / "SKILL.md").touch()
    (path / ".dhub-version").write_text(metadata)

    result = runner.invoke(app, ["--output", "json", "installed"])

    assert result.exit_code == 0, result.exception
    assert json.loads(result.stdout) == [{"ref": "team/model", "version": None, "agents": []}]
