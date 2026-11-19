"""Offline validation of a local skill manifest."""

import stat
from pathlib import Path

import typer
from rich.markup import escape
from yaml import YAMLError

from dhub.cli.output import ErrorCode, exit_error, is_json, print_json
from dhub.core.manifest import parse_skill_md


def validate_command(
    path: Path = typer.Argument(
        Path("."), help="Skill directory or SKILL.md file (defaults to the current directory)."
    ),
) -> None:
    """Validate one local SKILL.md manifest offline."""
    manifest_path = path
    try:
        if path.is_dir():
            manifest_path = path / "SKILL.md"
        mode = manifest_path.stat().st_mode
        if manifest_path.name != "SKILL.md" or not stat.S_ISREG(mode):
            raise ValueError("Expected a skill directory or a regular file named SKILL.md.")
        manifest = parse_skill_md(manifest_path)
    except (OSError, ValueError, YAMLError) as exc:
        code = ErrorCode.NOT_FOUND if isinstance(exc, FileNotFoundError) else ErrorCode.VALIDATION_ERROR
        reason = exc.strerror if isinstance(exc, OSError) else str(exc)
        message = f"{manifest_path}: {reason}"
        exit_error(code, message if is_json() else escape(message))

    if is_json():
        print_json({"valid": True, "name": manifest.name, "path": str(manifest_path)})
    else:
        typer.echo(f"Valid manifest for {manifest.name} ({manifest_path})")
