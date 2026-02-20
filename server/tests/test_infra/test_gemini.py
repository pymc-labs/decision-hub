"""Tests for decision_hub.infra.gemini -- client construction."""

from decision_hub.infra.gemini import create_gemini_client


class TestCreateGeminiClient:
    def test_returns_dict_with_api_key_and_base_url(self):
        client = create_gemini_client("test-key")
        assert client["api_key"] == "test-key"
        assert "generativelanguage.googleapis.com" in client["base_url"]
