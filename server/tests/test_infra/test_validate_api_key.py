"""Tests for validate_api_key() in infra/modal_client.py.

validate_api_key() makes a lightweight HTTP request to verify an API key
before launching a sandbox. It should fail fast for invalid keys and
not block on transient network errors.

Note: validate_api_key imports httpx locally, so we patch httpx.get
directly (the module is resolved from sys.modules at import time).
"""

from unittest.mock import MagicMock, patch

import pytest

from decision_hub.infra.modal_client import validate_api_key


class TestValidateApiKey:
    """Tests for the pre-sandbox API key validation."""

    @patch("httpx.get")
    def test_valid_anthropic_key_passes(self, mock_get: MagicMock):
        """200 response means key is valid — no exception raised."""
        mock_get.return_value = MagicMock(status_code=200)

        # Should not raise
        validate_api_key("ANTHROPIC_API_KEY", "sk-ant-valid-key-123")

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "api.anthropic.com" in call_args[0][0]
        headers = call_args[1]["headers"]
        assert headers["x-api-key"] == "sk-ant-valid-key-123"

    @patch("httpx.get")
    def test_invalid_anthropic_key_raises_valueerror(self, mock_get: MagicMock):
        """401 response raises ValueError with clear message."""
        mock_get.return_value = MagicMock(status_code=401)

        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is invalid"):
            validate_api_key("ANTHROPIC_API_KEY", "sk-ant-expired-key")

    @patch("httpx.get")
    def test_network_error_does_not_raise(self, mock_get: MagicMock):
        """Network errors are logged but don't block the pipeline."""
        import httpx

        mock_get.side_effect = httpx.HTTPError("Connection timed out")

        # Should not raise — transient network issues don't fail-fast
        validate_api_key("ANTHROPIC_API_KEY", "sk-ant-some-key")

    def test_unknown_provider_returns_immediately(self):
        """Keys for unknown providers skip validation (no HTTP call)."""
        # Should not raise, and should not make any HTTP calls
        validate_api_key("CODEX_API_KEY", "some-codex-key")
        validate_api_key("GEMINI_API_KEY", "some-gemini-key")
        validate_api_key("UNKNOWN_KEY", "some-value")

    @patch("httpx.get")
    def test_non_401_error_does_not_raise(self, mock_get: MagicMock):
        """Non-401 HTTP errors (500, 403, etc.) don't raise — only 401 is a clear signal."""
        mock_get.return_value = MagicMock(status_code=500)

        # 500 could be transient — should not raise
        validate_api_key("ANTHROPIC_API_KEY", "sk-ant-some-key")

    @patch("httpx.get")
    def test_uses_correct_anthropic_version_header(self, mock_get: MagicMock):
        """Validates the anthropic-version header is set correctly."""
        mock_get.return_value = MagicMock(status_code=200)

        validate_api_key("ANTHROPIC_API_KEY", "sk-ant-test-key")

        headers = mock_get.call_args[1]["headers"]
        assert headers["anthropic-version"] == "2023-06-01"
