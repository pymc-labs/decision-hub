"""Structured output support for the dhub CLI.

Provides a global output-format flag (text vs json) and helpers
for emitting machine-readable JSON to stdout/stderr.
"""

import json
import sys
from enum import Enum
from typing import Any


class OutputFormat(str, Enum):
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
