"""Tests for dhub.cli.app — installer detection and version probing.

Focus is on the subprocess timeout & error-handling hardening: a broken
package manager (hung, missing, permission-denied) must not freeze the CLI
or crash with an uncaught exception.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from dhub.cli.app import _detect_installer, _query_version, _run_probe


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestRunProbe:
    def test_returns_completed_process_on_success(self):
        with patch("dhub.cli.app.subprocess.run", return_value=_proc(returncode=0, stdout="ok")) as run:
            result = _run_probe(["echo", "ok"])
        assert result is not None
        assert result.returncode == 0
        assert result.stdout == "ok"
        # The probe must always pass a timeout so a hung child cannot wedge the CLI.
        assert run.call_args.kwargs.get("timeout") is not None

    def test_returns_none_on_timeout(self):
        with patch(
            "dhub.cli.app.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="x", timeout=10),
        ):
            assert _run_probe(["x"]) is None

    def test_returns_none_when_executable_missing(self):
        with patch("dhub.cli.app.subprocess.run", side_effect=FileNotFoundError):
            assert _run_probe(["does-not-exist"]) is None

    def test_returns_none_on_oserror(self):
        with patch("dhub.cli.app.subprocess.run", side_effect=PermissionError):
            assert _run_probe(["x"]) is None


class TestDetectInstaller:
    def test_uv_takes_priority(self, monkeypatch):
        which = {"uv": "/bin/uv", "pipx": "/bin/pipx"}.get
        monkeypatch.setattr("dhub.cli.app.shutil.which", which)
        monkeypatch.setattr(
            "dhub.cli.app._run_probe",
            lambda cmd: _proc(stdout="dhub-cli v0.9.0\n") if cmd[0] == "/bin/uv" else _proc(returncode=1),
        )
        assert _detect_installer() == "uv"

    def test_falls_back_to_pipx(self, monkeypatch):
        which = {"pipx": "/bin/pipx"}.get
        monkeypatch.setattr("dhub.cli.app.shutil.which", which)
        monkeypatch.setattr(
            "dhub.cli.app._run_probe",
            lambda cmd: _proc(stdout="dhub-cli 0.9.0\n") if cmd[0] == "/bin/pipx" else None,
        )
        assert _detect_installer() == "pipx"

    def test_pip_fallback_when_no_managers(self, monkeypatch):
        monkeypatch.setattr("dhub.cli.app.shutil.which", lambda _name: None)
        # _run_probe will never be invoked here, but stub it defensively.
        monkeypatch.setattr("dhub.cli.app._run_probe", lambda _cmd: None)
        assert _detect_installer() == "pip"

    def test_hung_uv_does_not_crash(self, monkeypatch):
        """A hung `uv tool list` (timeout) must fall through to the next probe."""
        monkeypatch.setattr("dhub.cli.app.shutil.which", lambda name: "/bin/" + name)
        monkeypatch.setattr("dhub.cli.app._run_probe", lambda _cmd: None)
        # All probes return None -> we fall through to "pip"
        assert _detect_installer() == "pip"


class TestQueryVersion:
    def test_pip_returns_version_from_show_output(self, monkeypatch):
        out = "Name: dhub-cli\nVersion: 1.2.3\nLocation: /x\n"
        monkeypatch.setattr("dhub.cli.app._run_probe", lambda _cmd: _proc(stdout=out))
        monkeypatch.setattr("dhub.cli.app._require_bin", lambda name: "/bin/" + name)
        assert _query_version("pip") == "1.2.3"

    def test_returns_none_when_probe_fails(self, monkeypatch):
        monkeypatch.setattr("dhub.cli.app._run_probe", lambda _cmd: None)
        monkeypatch.setattr("dhub.cli.app._require_bin", lambda name: "/bin/" + name)
        assert _query_version("uv") is None
        assert _query_version("pipx") is None
        assert _query_version("pip") is None

    def test_uv_strips_leading_v(self, monkeypatch):
        monkeypatch.setattr("dhub.cli.app._run_probe", lambda _cmd: _proc(stdout="dhub-cli v0.9.0 (/path)\n"))
        monkeypatch.setattr("dhub.cli.app._require_bin", lambda name: "/bin/" + name)
        assert _query_version("uv") == "0.9.0"
