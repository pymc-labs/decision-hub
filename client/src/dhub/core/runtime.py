"""Local uv runtime domain logic.

Provides functions for validating prerequisites, building commands,
and preparing environment variables for running skills via uv.
"""

import os
import shutil
from pathlib import Path

from dhub.models import RuntimeConfig


def validate_local_runtime_prerequisites(skill_dir: Path, config: RuntimeConfig) -> list[str]:
    """Check that all prerequisites for local runtime are met.

    Returns a list of error messages. An empty list means all prerequisites
    are satisfied.
    """
    errors: list[str] = []

    if shutil.which("uv") is None:
        errors.append("'uv' is not installed or not on PATH. Install it from https://docs.astral.sh/uv/")

    lockfile = config.dependencies.lockfile if config.dependencies else None
    if lockfile:
        lockfile_path = skill_dir / lockfile
        if not lockfile_path.exists():
            errors.append(f"Lockfile not found: {lockfile_path}")

    entrypoint_path = skill_dir / config.entrypoint
    if not entrypoint_path.exists():
        errors.append(f"Entrypoint not found: {entrypoint_path}")

    return errors


def build_uv_sync_command(skill_dir: Path) -> list[str]:
    """Build the uv sync command for installing dependencies in a skill directory."""
    return ["uv", "sync", "--directory", str(skill_dir)]


def build_uv_run_command(
    skill_dir: Path,
    entrypoint: str,
    extra_args: tuple[str, ...] = (),
) -> list[str]:
    """Build the uv run command for executing a skill entrypoint."""
    cmd = ["uv", "run", "--directory", str(skill_dir), "python", entrypoint]
    cmd.extend(extra_args)
    return cmd


def build_env_vars(
    config: RuntimeConfig,
    user_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build environment variables dict from runtime config and user overrides.

    Starts with the current process environment, overlays any user-provided
    values, and validates that all required env vars (from config.env) are present.

    Raises:
        ValueError: If any required environment variable is missing.
    """
    env = dict(os.environ)

    if user_env:
        env.update(user_env)

    missing = [var for var in config.env if var not in env]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    return env
