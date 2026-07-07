"""Regression tests for ``dhub install --repo`` reference parsing.

Historically ``_install_from_repo`` did ``if not repo_ref.startswith("http")``
which mangled SSH refs (``git@github.com:acme/skills``) into
``https://github.com/git@github.com:acme/skills`` — the user got an
uninformative 404 from the server with no hint that the URL was mangled.
"""

from unittest.mock import patch

from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


class TestInstallRepoRefParsing:
    """Every branch of the ref-normalization in ``_install_from_repo``."""

    @patch("dhub.cli.config.get_optional_token", return_value=None)
    def test_ssh_url_is_rejected(self, _mock_token) -> None:
        result = runner.invoke(app, ["install", "--repo", "git@github.com:acme/skills"])
        assert result.exit_code != 0
        # Rich may wrap the output, so match the discriminating tokens rather
        # than the exact phrase; either 'SSH/git' or 'supported' must appear.
        normalized = " ".join(result.output.split()).lower()
        assert "ssh/git" in normalized or "supported" in normalized

    @patch("dhub.cli.config.get_optional_token", return_value=None)
    def test_git_scheme_is_rejected(self, _mock_token) -> None:
        result = runner.invoke(app, ["install", "--repo", "git://github.com/acme/skills"])
        assert result.exit_code != 0

    @patch("dhub.cli.config.get_optional_token", return_value=None)
    def test_ssh_scheme_is_rejected(self, _mock_token) -> None:
        result = runner.invoke(app, ["install", "--repo", "ssh://git@github.com/acme/skills"])
        assert result.exit_code != 0

    @patch("dhub.cli.config.get_optional_token", return_value=None)
    def test_bare_string_is_rejected(self, _mock_token) -> None:
        # No slash, no scheme → clearly wrong.
        result = runner.invoke(app, ["install", "--repo", "just-a-word"])
        assert result.exit_code != 0
        assert "not a recognized repo reference" in result.output.lower() or "error" in result.output.lower()
