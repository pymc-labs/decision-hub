"""Tests for decision_hub.infra.modal_client -- API key validation."""

import httpx
import pytest
import respx

from decision_hub.infra.modal_client import validate_api_key


class TestValidateApiKey:
    @respx.mock
    def test_raises_on_401(self):
        respx.get("https://api.anthropic.com/v1/models").mock(return_value=httpx.Response(401))
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is invalid"):
            validate_api_key("ANTHROPIC_API_KEY", "sk-bad-key")

    @respx.mock
    def test_passes_on_200(self):
        respx.get("https://api.anthropic.com/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
        validate_api_key("ANTHROPIC_API_KEY", "sk-good-key")

    def test_skips_unknown_provider(self):
        # Should not raise for providers without a validation endpoint
        validate_api_key("SOME_OTHER_KEY", "any-value")

    @respx.mock
    def test_does_not_block_on_network_error(self):
        respx.get("https://api.anthropic.com/v1/models").mock(side_effect=httpx.ConnectError("connection refused"))
        # Should not raise — network issues are transient
        validate_api_key("ANTHROPIC_API_KEY", "sk-any-key")
