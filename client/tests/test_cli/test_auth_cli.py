"""Tests for dhub.cli.auth -- login command via device flow."""

from unittest.mock import patch

import httpx
import respx


class TestLoginCommand:
    """dhub login -- GitHub Device Flow via CLI."""

    @respx.mock
    @patch("dhub.cli.config.save_config")
    @patch("dhub.cli.auth._poll_for_token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_login_command_success(
        self,
        _mock_url,
        mock_poll,
        mock_save,
    ) -> None:
        """Successful login should save the token to config."""
        from typer.testing import CliRunner

        from dhub.cli.app import app

        runner = CliRunner()

        respx.post("http://test:8000/auth/github/code").mock(
            return_value=httpx.Response(
                200,
                json={
                    "device_code": "dev-123",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://github.com/login/device",
                    "interval": 5,
                },
            )
        )

        mock_poll.return_value = {
            "access_token": "jwt-token-xyz",
            "username": "testuser",
        }

        result = runner.invoke(app, ["login"])

        assert result.exit_code == 0
        assert "testuser" in result.output

        mock_save.assert_called_once()
        saved_config = mock_save.call_args[0][0]
        assert saved_config.token == "jwt-token-xyz"

    @respx.mock
    @patch("dhub.cli.config.save_config")
    @patch("dhub.cli.auth._poll_for_token")
    def test_login_command_with_api_url_override(
        self,
        mock_poll,
        mock_save,
    ) -> None:
        """Login with --api-url should use the provided URL."""
        from typer.testing import CliRunner

        from dhub.cli.app import app

        runner = CliRunner()

        respx.post("http://localhost:8000/auth/github/code").mock(
            return_value=httpx.Response(
                200,
                json={
                    "device_code": "dev-456",
                    "user_code": "WXYZ-1234",
                    "verification_uri": "https://github.com/login/device",
                    "interval": 5,
                },
            )
        )

        mock_poll.return_value = {
            "access_token": "jwt-token-custom",
            "username": "customuser",
        }

        result = runner.invoke(app, ["login", "--api-url", "http://localhost:8000"])

        assert result.exit_code == 0

        saved_config = mock_save.call_args[0][0]
        assert saved_config.api_url == "http://localhost:8000"
        assert saved_config.token == "jwt-token-custom"
