"""Tests for backfill_org_metadata's token-resolution behaviour.

Regression coverage for the CLAUDE.md "Sanitize subprocess credentials"
rule: the GitHub PAT must be sourced from an environment variable so it
never appears in ``ps auxww`` output or shell history. The old script
required ``--github-token "$(gh auth token)"`` on argv.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from decision_hub.scripts.backfill_org_metadata import _resolve_github_token


class TestResolveGithubToken:
    def test_env_var_wins_over_argv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When both are set, the env var wins so operators can migrate
        callers piecemeal without leaking the argv value while they do."""
        monkeypatch.setenv("GITHUB_TOKEN", "from-env")
        assert _resolve_github_token("from-argv") == "from-env"

    def test_gh_token_env_var_also_recognised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """gh CLI users often have ``GH_TOKEN`` set instead — accept either
        so ``GH_TOKEN=$(gh auth token) …`` works with no extra plumbing."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "gh-token-value")
        assert _resolve_github_token(None) == "gh-token-value"

    def test_falls_back_to_argv_with_warning(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The legacy ``--github-token`` flag still works so nothing breaks
        on the first pass of the migration, but MUST warn so operators
        move off it before the argv path becomes the only failure mode."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        assert _resolve_github_token("legacy-argv") == "legacy-argv"
        out = capsys.readouterr().out
        assert "deprecated" in out.lower()

    def test_no_token_anywhere_exits_nonzero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Missing the token entirely must be a hard failure — silently
        making calls without one would immediately trip GitHub's
        unauthenticated rate limit."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            _resolve_github_token(None)
        assert exc_info.value.code == 2
        assert "GITHUB_TOKEN" in capsys.readouterr().out

    def test_does_not_pass_token_via_argv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Belt-and-braces: --github-token must not be marked ``required`` in
        the argparse setup, otherwise operators can't invoke the script at
        all without passing the token on argv (defeating the whole point).
        """
        from decision_hub.scripts import backfill_org_metadata

        # If parse_args() with no argv succeeded and args.github_token is
        # None, that proves the arg is optional.
        monkeypatch.setattr("sys.argv", ["backfill_org_metadata"])
        with patch("decision_hub.scripts.backfill_org_metadata.sys.argv", ["backfill_org_metadata"]):
            args = backfill_org_metadata.parse_args([])
        assert args.github_token is None
