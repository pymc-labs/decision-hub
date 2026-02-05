"""Tests for local uv runtime domain logic."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from decision_hub.domain.runtime import (
    build_env_vars,
    build_uv_run_command,
    build_uv_sync_command,
    validate_local_runtime_prerequisites,
)
from decision_hub.models import RuntimeConfig


@pytest.fixture
def runtime_config() -> RuntimeConfig:
    """A standard runtime config for tests."""
    return RuntimeConfig(
        driver="local/uv",
        entrypoint="src/main.py",
        lockfile="uv.lock",
        env=("OPENAI_API_KEY",),
    )


@pytest.fixture
def runtime_config_no_env() -> RuntimeConfig:
    """A runtime config with no required env vars."""
    return RuntimeConfig(
        driver="local/uv",
        entrypoint="main.py",
        lockfile="uv.lock",
        env=(),
    )


class TestBuildUvSyncCommand:
    """Tests for build_uv_sync_command."""

    def test_basic_sync_command(self, tmp_path: Path) -> None:
        cmd = build_uv_sync_command(tmp_path)
        assert cmd == ["uv", "sync", "--directory", str(tmp_path)]

    def test_returns_list_of_strings(self, tmp_path: Path) -> None:
        cmd = build_uv_sync_command(tmp_path)
        assert all(isinstance(part, str) for part in cmd)


class TestBuildUvRunCommand:
    """Tests for build_uv_run_command."""

    def test_basic_run_command(self, tmp_path: Path) -> None:
        cmd = build_uv_run_command(tmp_path, "src/main.py")
        assert cmd == [
            "uv", "run", "--directory", str(tmp_path),
            "python", "src/main.py",
        ]

    def test_run_command_with_extra_args(self, tmp_path: Path) -> None:
        cmd = build_uv_run_command(tmp_path, "main.py", ("--verbose", "--port", "8080"))
        assert cmd == [
            "uv", "run", "--directory", str(tmp_path),
            "python", "main.py",
            "--verbose", "--port", "8080",
        ]

    def test_run_command_empty_extra_args(self, tmp_path: Path) -> None:
        cmd = build_uv_run_command(tmp_path, "main.py", ())
        assert cmd == [
            "uv", "run", "--directory", str(tmp_path),
            "python", "main.py",
        ]


class TestValidateLocalRuntimePrerequisites:
    """Tests for validate_local_runtime_prerequisites."""

    def test_all_prerequisites_met(
        self, tmp_path: Path, runtime_config: RuntimeConfig
    ) -> None:
        # Create required files
        (tmp_path / "uv.lock").touch()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").touch()

        with patch("decision_hub.domain.runtime.shutil.which", return_value="/usr/bin/uv"):
            errors = validate_local_runtime_prerequisites(tmp_path, runtime_config)

        assert errors == []

    def test_uv_not_installed(
        self, tmp_path: Path, runtime_config: RuntimeConfig
    ) -> None:
        (tmp_path / "uv.lock").touch()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").touch()

        with patch("decision_hub.domain.runtime.shutil.which", return_value=None):
            errors = validate_local_runtime_prerequisites(tmp_path, runtime_config)

        assert len(errors) == 1
        assert "uv" in errors[0].lower()

    def test_missing_lockfile(
        self, tmp_path: Path, runtime_config: RuntimeConfig
    ) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").touch()

        with patch("decision_hub.domain.runtime.shutil.which", return_value="/usr/bin/uv"):
            errors = validate_local_runtime_prerequisites(tmp_path, runtime_config)

        assert len(errors) == 1
        assert "lockfile" in errors[0].lower() or "uv.lock" in errors[0]

    def test_missing_entrypoint(
        self, tmp_path: Path, runtime_config: RuntimeConfig
    ) -> None:
        (tmp_path / "uv.lock").touch()

        with patch("decision_hub.domain.runtime.shutil.which", return_value="/usr/bin/uv"):
            errors = validate_local_runtime_prerequisites(tmp_path, runtime_config)

        assert len(errors) == 1
        assert "entrypoint" in errors[0].lower() or "main.py" in errors[0]

    def test_multiple_errors(
        self, tmp_path: Path, runtime_config: RuntimeConfig
    ) -> None:
        # Missing everything: uv, lockfile, entrypoint
        with patch("decision_hub.domain.runtime.shutil.which", return_value=None):
            errors = validate_local_runtime_prerequisites(tmp_path, runtime_config)

        assert len(errors) == 3


class TestBuildEnvVars:
    """Tests for build_env_vars."""

    def test_env_vars_from_process_environment(
        self, runtime_config: RuntimeConfig
    ) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test123"}, clear=False):
            env = build_env_vars(runtime_config)

        assert env["OPENAI_API_KEY"] == "sk-test123"

    def test_user_env_overrides(self, runtime_config: RuntimeConfig) -> None:
        user_env = {"OPENAI_API_KEY": "sk-override"}
        env = build_env_vars(runtime_config, user_env=user_env)
        assert env["OPENAI_API_KEY"] == "sk-override"

    def test_missing_required_env_var_raises(
        self, runtime_config: RuntimeConfig
    ) -> None:
        # Clear OPENAI_API_KEY from the environment
        clean_env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with patch.dict(os.environ, clean_env, clear=True):
            with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                build_env_vars(runtime_config)

    def test_no_required_env_vars(
        self, runtime_config_no_env: RuntimeConfig
    ) -> None:
        env = build_env_vars(runtime_config_no_env)
        # Should succeed and return something based on os.environ
        assert isinstance(env, dict)

    def test_user_env_none(self, runtime_config_no_env: RuntimeConfig) -> None:
        env = build_env_vars(runtime_config_no_env, user_env=None)
        assert isinstance(env, dict)
