"""Structured output support for the dhub CLI.

Provides a global output-format flag (text vs json) and helpers
for emitting machine-readable JSON to stdout/stderr.
"""

import json
import sys
from enum import StrEnum
from typing import Any


class OutputFormat(StrEnum):
    text = "text"
    json = "json"


_current_format: OutputFormat = OutputFormat.text


def set_format(fmt: OutputFormat) -> None:
    """Set the global output format."""
    global _current_format
    _current_format = fmt


def is_json() -> bool:
    """Return True if the current output format is JSON."""
    return _current_format is OutputFormat.json


def print_json(data: Any) -> None:
    """Write JSON-serialized *data* to stdout, followed by a newline, and flush."""
    sys.stdout.write(json.dumps(data, default=str) + "\n")
    sys.stdout.flush()


def print_json_err(data: dict) -> None:
    """Write JSON-serialized *data* to stderr, followed by a newline, and flush."""
    sys.stderr.write(json.dumps(data, default=str) + "\n")
    sys.stderr.flush()


class ErrorCode(StrEnum):
    """Machine-readable error codes for structured CLI error output."""

    AUTH_REQUIRED = "AUTH_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    VERSION_EXISTS = "VERSION_EXISTS"
    GAUNTLET_FAILED = "GAUNTLET_FAILED"
    UPGRADE_REQUIRED = "UPGRADE_REQUIRED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


def exit_error(code: ErrorCode, message: str, *, status: int | None = None) -> None:
    """Print an error and raise typer.Exit(1).

    In JSON mode: writes structured JSON to stderr.
    In text mode: prints Rich-formatted error to stderr.
    """
    import typer

    if is_json():
        err: dict[str, object] = {"error": True, "code": code.value, "message": message}
        if status is not None:
            err["status"] = status
        print_json_err(err)
    else:
        from rich.console import Console

        Console(stderr=True).print(f"[red]Error: {message}[/]")

    raise typer.Exit(1)
