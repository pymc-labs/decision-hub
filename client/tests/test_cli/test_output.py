"""Tests for dhub.cli.output -- output format module and global --output flag."""

import json
import sys

from typer.testing import CliRunner

from dhub.cli.app import app
from dhub.cli.output import OutputFormat, is_json, print_json, print_json_err, set_format

runner = CliRunner()


class TestOutputFormat:
    def test_default_is_text(self) -> None:
        """The default output format should be text."""
        set_format(OutputFormat.text)
        assert not is_json()

    def test_set_to_json(self) -> None:
        """Setting format to json should stick."""
        set_format(OutputFormat.json)
        assert is_json()
        # Reset to avoid polluting other tests
        set_format(OutputFormat.text)

    def test_is_json_returns_false_for_text(self) -> None:
        set_format(OutputFormat.text)
        assert is_json() is False

    def test_is_json_returns_true_for_json(self) -> None:
        set_format(OutputFormat.json)
        assert is_json() is True
        set_format(OutputFormat.text)


class TestGlobalOutputFlag:
    def test_output_json_flag_accepted(self) -> None:
        """The --output json flag should be accepted without error."""
        result = runner.invoke(app, ["--output", "json", "--help"])
        assert result.exit_code == 0

    def test_invalid_format_rejected(self) -> None:
        """An invalid output format like 'xml' should be rejected."""
        result = runner.invoke(app, ["--output", "xml", "env"])
        assert result.exit_code != 0


class TestPrintJson:
    def test_print_json_writes_valid_json_to_stdout(self, capsys) -> None:
        """print_json should write valid JSON followed by a newline to stdout."""
        data = {"name": "test-skill", "version": 1}
        print_json(data)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed == data
        assert captured.out.endswith("\n")

    def test_print_json_handles_non_serializable_with_default_str(self, capsys) -> None:
        """print_json should use str() as default for non-serializable types."""
        from datetime import datetime

        dt = datetime(2026, 1, 15, 12, 0, 0)
        data = {"timestamp": dt}
        print_json(data)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["timestamp"] == str(dt)

    def test_print_json_err_writes_to_stderr(self, capsys) -> None:
        """print_json_err should write valid JSON to stderr."""
        data = {"error": "something went wrong"}
        print_json_err(data)
        captured = capsys.readouterr()
        assert captured.out == ""
        parsed = json.loads(captured.err)
        assert parsed == data
        assert captured.err.endswith("\n")
