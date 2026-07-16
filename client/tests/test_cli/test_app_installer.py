"""Tests for the installer helpers used by `dhub upgrade`."""

import subprocess
from unittest.mock import patch

import pytest

from dhub.cli.app import (
    _detect_installer,
    _first_token_is_dhub_cli,
    _query_version,
    _run_installer,
)


class TestFirstTokenIsDhubCli:
    """`dhub-cli` must match exactly, not the sibling `dhub-cli-extras`."""

    def test_exact_match(self) -> None:
        assert _first_token_is_dhub_cli("dhub-cli v0.12.1")

    def test_leading_whitespace(self) -> None:
        assert _first_token_is_dhub_cli("   dhub-cli v0.12.1")

    def test_sibling_prefix_rejected(self) -> None:
        # This is the exact bug the fix targets — startswith("dhub-cli") would
        # have accepted these lines and returned the wrong version.
        assert not _first_token_is_dhub_cli("dhub-cli-extras 0.1.0")
        assert not _first_token_is_dhub_cli("dhub-cli-plugin 2.0.0")

    def test_empty_line(self) -> None:
        assert not _first_token_is_dhub_cli("")
        assert not _first_token_is_dhub_cli("   ")


class TestRunInstaller:
    """`_run_installer` bounds every subprocess call and swallows exec errors."""

    def test_returns_completed_process(self) -> None:
        # Use `true` — always available on Linux runners.
        result = _run_installer(["true"])
        assert result is not None
        assert result.returncode == 0

    def test_missing_binary_returns_none(self) -> None:
        result = _run_installer(["/does/not/exist/for/dhub/tests"])
        assert result is None

    def test_timeout_returns_none(self) -> None:
        def _timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        with patch("dhub.cli.app.subprocess.run", side_effect=_timeout):
            assert _run_installer(["ignored"]) is None


class TestDetectInstaller:
    """`_detect_installer` distinguishes dhub-cli from sibling packages."""

    def _fake_result(self, stdout: str) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")

    def test_uv_detection(self) -> None:
        with (
            patch("dhub.cli.app.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name == "uv" else None),
            patch("dhub.cli.app._run_installer", return_value=self._fake_result("dhub-cli v0.12.1\n")),
        ):
            assert _detect_installer() == "uv"

    def test_uv_ignores_sibling_dhub_cli_extras(self) -> None:
        """Regression: sibling packages must not be mistaken for dhub-cli."""
        with (
            patch(
                "dhub.cli.app.shutil.which",
                side_effect=lambda name: f"/usr/bin/{name}" if name in {"uv", "pipx"} else None,
            ),
            patch(
                "dhub.cli.app._run_installer",
                side_effect=[
                    self._fake_result("dhub-cli-extras 0.1.0\n"),  # uv result
                    self._fake_result("dhub-cli-extras 0.1.0\n"),  # pipx result
                ],
            ),
        ):
            assert _detect_installer() == "pip"

    def test_pipx_fallback(self) -> None:
        with (
            patch("dhub.cli.app.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name == "pipx" else None),
            patch("dhub.cli.app._run_installer", return_value=self._fake_result("dhub-cli 0.12.1\n")),
        ):
            assert _detect_installer() == "pipx"

    def test_falls_back_to_pip_when_no_managers(self) -> None:
        with patch("dhub.cli.app.shutil.which", return_value=None):
            assert _detect_installer() == "pip"


class TestQueryVersion:
    """`_query_version` returns None cleanly when tooling misbehaves."""

    def _fake_result(self, stdout: str) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")

    def test_uv_parses_version(self) -> None:
        with (
            patch("dhub.cli.app._require_bin", return_value="/usr/bin/uv"),
            patch("dhub.cli.app._run_installer", return_value=self._fake_result("dhub-cli v0.12.1\n")),
        ):
            assert _query_version("uv") == "0.12.1"

    def test_uv_skips_sibling(self) -> None:
        stdout = "dhub-cli-extras 0.1.0\ndhub-cli v0.12.1\n"
        with (
            patch("dhub.cli.app._require_bin", return_value="/usr/bin/uv"),
            patch("dhub.cli.app._run_installer", return_value=self._fake_result(stdout)),
        ):
            assert _query_version("uv") == "0.12.1"

    def test_returns_none_on_run_failure(self) -> None:
        with (
            patch("dhub.cli.app._require_bin", return_value="/usr/bin/uv"),
            patch("dhub.cli.app._run_installer", return_value=None),
        ):
            assert _query_version("uv") is None

    def test_pip_parses_show_output(self) -> None:
        stdout = "Name: dhub-cli\nVersion: 0.12.1\n"
        with patch("dhub.cli.app._run_installer", return_value=self._fake_result(stdout)):
            assert _query_version("pip") == "0.12.1"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
