"""Tests for dhub uninstall command."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


class TestUninstallCommand:

    @patch("dhub.core.install.uninstall_skill", return_value=["claude", "cursor"])
    def test_uninstall_success_with_symlinks(self, mock_uninstall):
        result = runner.invoke(app, ["uninstall", "myorg/my-skill"])

        assert result.exit_code == 0
        assert "Uninstalled myorg/my-skill" in result.output
        assert "claude" in result.output
        assert "cursor" in result.output
        mock_uninstall.assert_called_once_with("myorg", "my-skill")

    @patch("dhub.core.install.uninstall_skill", return_value=[])
    def test_uninstall_success_no_symlinks(self, mock_uninstall):
        result = runner.invoke(app, ["uninstall", "myorg/my-skill"])

        assert result.exit_code == 0
        assert "Uninstalled myorg/my-skill" in result.output
        # No "Removed symlinks" line when no agents were linked
        assert "Removed symlinks" not in result.output

    @patch(
        "dhub.core.install.uninstall_skill",
        side_effect=FileNotFoundError("not installed"),
    )
    def test_uninstall_not_installed(self, mock_uninstall):
        result = runner.invoke(app, ["uninstall", "myorg/no-such-skill"])

        assert result.exit_code == 1
        assert "not installed" in result.output

    def test_uninstall_invalid_skill_ref(self):
        result = runner.invoke(app, ["uninstall", "no-slash"])

        assert result.exit_code == 1
        assert "org/skill format" in result.output

    def test_uninstall_missing_argument(self):
        result = runner.invoke(app, ["uninstall"])

        assert result.exit_code == 2
        assert "Missing argument" in result.output
