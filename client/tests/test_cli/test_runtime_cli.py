"""Tests for dhub.cli.runtime -- run command."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SKILL_MD_WITH_RUNTIME = """\
---
name: my-skill
description: A test skill
runtime:
  driver: local/uv
  entrypoint: main.py
  lockfile: uv.lock
  env: []
---
System prompt body here.
"""

_SKILL_MD_WITHOUT_RUNTIME = """\
---
name: my-skill
description: A test skill
---
System prompt body here.
"""


def _setup_skill_dir(
    base: Path,
    org: str,
    skill: str,
    skill_md_content: str,
    *,
    create_entrypoint: bool = False,
    create_lockfile: bool = False,
) -> Path:
    """Create a skill directory with the given SKILL.md and optional files."""
    skill_dir = base / org / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(skill_md_content)
    if create_entrypoint:
        (skill_dir / "main.py").write_text("print('hello')\n")
    if create_lockfile:
        (skill_dir / "uv.lock").write_text("# lockfile\n")
    return skill_dir


# ---------------------------------------------------------------------------
# run_command tests
# ---------------------------------------------------------------------------


class TestRunCommand:
    @patch("dhub.core.install.get_dhub_skill_path")
    def test_run_missing_skill(
        self,
        mock_skill_path: MagicMock,
        tmp_path: Path,
    ) -> None:
        """run should fail if the skill directory does not exist."""
        mock_skill_path.return_value = tmp_path / "org" / "nonexistent"

        result = runner.invoke(app, ["run", "org/nonexistent"])

        assert result.exit_code == 1
        assert "not installed" in result.output

    def test_run_invalid_skill_ref(self) -> None:
        """run should reject a skill reference without a slash."""
        result = runner.invoke(app, ["run", "noslash"])

        assert result.exit_code == 1
        assert "org/skill format" in result.output

    @patch("dhub.core.install.get_dhub_skill_path")
    def test_run_no_runtime_config(
        self,
        mock_skill_path: MagicMock,
        tmp_path: Path,
    ) -> None:
        """run should fail if SKILL.md has no runtime block."""
        skill_dir = _setup_skill_dir(tmp_path, "myorg", "my-skill", _SKILL_MD_WITHOUT_RUNTIME)
        mock_skill_path.return_value = skill_dir

        result = runner.invoke(app, ["run", "myorg/my-skill"])

        assert result.exit_code == 1
        assert "no runtime configuration" in result.output.lower()

    @patch("dhub.core.install.get_dhub_skill_path")
    def test_run_unsupported_language(
        self,
        mock_skill_path: MagicMock,
        tmp_path: Path,
    ) -> None:
        """run should fail for an unsupported runtime language.

        The manifest parser validates the language during parsing and raises
        a ValueError before the CLI checks it, so we expect a non-zero exit
        with the error surfaced as an exception.
        """
        # Use a language value that parse_skill_md rejects during validation
        unsupported_md = """\
---
name: my-skill
description: A test skill
runtime:
  language: ruby
  entrypoint: main.rb
  env: []
---
System prompt body here.
"""
        skill_dir = _setup_skill_dir(
            tmp_path,
            "myorg",
            "my-skill",
            unsupported_md,
            create_entrypoint=True,
            create_lockfile=True,
        )
        mock_skill_path.return_value = skill_dir

        result = runner.invoke(app, ["run", "myorg/my-skill"])

        # parse_skill_md raises ValueError for unsupported languages
        assert result.exit_code != 0
        assert result.exception is not None
        assert "Unsupported runtime language" in str(result.exception)

    @patch("dhub.cli.runtime.subprocess.run")
    @patch("dhub.core.install.get_dhub_skill_path")
    def test_run_success(
        self,
        mock_skill_path: MagicMock,
        mock_subprocess: MagicMock,
        tmp_path: Path,
    ) -> None:
        """run should sync deps and execute the entrypoint on success."""
        skill_dir = _setup_skill_dir(
            tmp_path,
            "myorg",
            "my-skill",
            _SKILL_MD_WITH_RUNTIME,
            create_entrypoint=True,
            create_lockfile=True,
        )
        mock_skill_path.return_value = skill_dir

        # First call is uv sync (check=True), second is uv run
        sync_result = MagicMock()
        run_result = MagicMock()
        run_result.returncode = 0
        mock_subprocess.side_effect = [sync_result, run_result]

        result = runner.invoke(app, ["run", "myorg/my-skill"])

        assert result.exit_code == 0

        # Verify subprocess.run was called twice (sync + run)
        assert mock_subprocess.call_count == 2

        # First call: uv sync
        sync_call = mock_subprocess.call_args_list[0]
        sync_cmd = sync_call.args[0]
        assert sync_cmd[0] == "uv"
        assert sync_cmd[1] == "sync"
        assert sync_call.kwargs["check"] is True

        # Second call: uv run
        run_call = mock_subprocess.call_args_list[1]
        run_cmd = run_call.args[0]
        assert run_cmd[0] == "uv"
        assert run_cmd[1] == "run"
        assert "main.py" in run_cmd
