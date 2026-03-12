"""Tests for dhub.cli.output -- output format module and global --output flag."""

import json

import pytest
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


class TestEnvJsonOutput:
    def test_env_json_output(self) -> None:
        result = runner.invoke(app, ["--output", "json", "env"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "environment" in data
        assert "config_file" in data
        assert "api_url" in data


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


class TestExitError:
    def test_exit_error_text_mode(self) -> None:
        """In text mode, exit_error prints a Rich error to stderr and raises typer.Exit."""
        import typer

        from dhub.cli.output import ErrorCode, exit_error

        set_format(OutputFormat.text)
        with pytest.raises(typer.Exit):
            exit_error(ErrorCode.NOT_FOUND, "Skill not found")

    def test_exit_error_json_mode(self, capsys) -> None:
        """In JSON mode, exit_error writes structured JSON to stderr and raises typer.Exit."""
        import typer

        from dhub.cli.output import ErrorCode, exit_error

        set_format(OutputFormat.json)
        with pytest.raises(typer.Exit):
            exit_error(ErrorCode.NOT_FOUND, "Skill not found", status=404)
        captured = capsys.readouterr()
        data = json.loads(captured.err)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"
        assert data["message"] == "Skill not found"
        assert data["status"] == 404
        set_format(OutputFormat.text)  # Reset

    def test_exit_error_json_mode_without_status(self, capsys) -> None:
        """In JSON mode without status, the status key should be absent."""
        import typer

        from dhub.cli.output import ErrorCode, exit_error

        set_format(OutputFormat.json)
        with pytest.raises(typer.Exit):
            exit_error(ErrorCode.AUTH_REQUIRED, "Not logged in")
        captured = capsys.readouterr()
        data = json.loads(captured.err)
        assert data["error"] is True
        assert data["code"] == "AUTH_REQUIRED"
        assert "status" not in data
        set_format(OutputFormat.text)  # Reset

    def test_exit_error_fatal_raises_system_exit(self, capsys) -> None:
        """fatal=True raises SystemExit so batch loops can't swallow the error."""
        from dhub.cli.output import ErrorCode, exit_error

        set_format(OutputFormat.text)
        with pytest.raises(SystemExit, match="1"):
            exit_error(ErrorCode.UPGRADE_REQUIRED, "CLI outdated", fatal=True)

    def test_exit_error_fatal_json_mode(self, capsys) -> None:
        """fatal=True in JSON mode still writes structured JSON before SystemExit."""
        from dhub.cli.output import ErrorCode, exit_error

        set_format(OutputFormat.json)
        with pytest.raises(SystemExit, match="1"):
            exit_error(ErrorCode.UPGRADE_REQUIRED, "CLI outdated", status=426, fatal=True)
        captured = capsys.readouterr()
        data = json.loads(captured.err)
        assert data["error"] is True
        assert data["code"] == "UPGRADE_REQUIRED"
        assert data["status"] == 426
        set_format(OutputFormat.text)  # Reset
