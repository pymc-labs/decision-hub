"""Regression tests for ``dhub.cli.auth._prompt_default_org``.

These pin the fixes made after two production issues:

1. ``token_data["orgs"] is None`` used to crash the login command with
   ``TypeError: 'NoneType' is not iterable`` on the ``tuple(orgs)`` line.
2. ``_prompt_default_org`` used to (a) block on stdin in non-TTY contexts
   like CI, and (b) silently pick the first org when the user hit Enter
   with no input, contradicting the ``(none)`` hint in the prompt.
"""

from unittest.mock import patch

from dhub.cli.auth import _prompt_default_org


class TestPromptDefaultOrgTTY:
    """Behaviour when running from a terminal."""

    @patch("dhub.cli.auth.sys.stdin.isatty", return_value=True)
    @patch("dhub.cli.auth.console.input", return_value="")
    def test_empty_input_returns_none(self, _mock_input, _mock_tty) -> None:
        """Blank Enter must NOT silently pick the first org."""
        assert _prompt_default_org(("acme", "beta")) is None

    @patch("dhub.cli.auth.sys.stdin.isatty", return_value=True)
    @patch("dhub.cli.auth.console.input", return_value="none")
    def test_literal_none_returns_none(self, _mock_input, _mock_tty) -> None:
        """Typing 'none' must map to no-default."""
        assert _prompt_default_org(("acme", "beta")) is None

    @patch("dhub.cli.auth.sys.stdin.isatty", return_value=True)
    @patch("dhub.cli.auth.console.input", return_value="  ACME ")
    def test_case_insensitive_match(self, _mock_input, _mock_tty) -> None:
        """Whitespace + case-folding still selects a valid org."""
        assert _prompt_default_org(("acme", "beta")) == "acme"

    @patch("dhub.cli.auth.sys.stdin.isatty", return_value=True)
    @patch("dhub.cli.auth.console.input", return_value="unknown-org")
    def test_unknown_choice_returns_none(self, _mock_input, _mock_tty) -> None:
        """Typos yield no default and warn the user rather than silently
        assigning to some other org."""
        assert _prompt_default_org(("acme", "beta")) is None

    @patch("dhub.cli.auth.sys.stdin.isatty", return_value=True)
    @patch("dhub.cli.auth.console.input", side_effect=EOFError)
    def test_ctrl_d_returns_none(self, _mock_input, _mock_tty) -> None:
        """Ctrl-D on the prompt should not crash the login."""
        assert _prompt_default_org(("acme", "beta")) is None


class TestPromptDefaultOrgNonTTY:
    """Behaviour under CI / piped stdin."""

    @patch("dhub.cli.auth.sys.stdin.isatty", return_value=False)
    def test_skips_prompt_entirely(self, _mock_tty) -> None:
        """Non-interactive contexts must not block on stdin."""
        with patch("dhub.cli.auth.console.input") as mock_input:
            assert _prompt_default_org(("acme", "beta")) is None
            mock_input.assert_not_called()

    @patch("dhub.cli.auth.sys.stdin.isatty", return_value=False)
    def test_single_org_returns_it(self, _mock_tty) -> None:
        """Single-org users get the org even without a TTY."""
        assert _prompt_default_org(("only-one",)) == "only-one"

    def test_no_orgs_returns_none(self) -> None:
        """Empty tuple returns None with no prompt (regardless of TTY)."""
        assert _prompt_default_org(()) is None
