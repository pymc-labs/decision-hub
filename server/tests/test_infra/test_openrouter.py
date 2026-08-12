"""Tests for the OpenRouter transport and provider dispatch."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx

from decision_hub.infra.gemini import analyze_code_safety, classify_skill
from decision_hub.infra.openrouter import (
    create_openrouter_client,
    openrouter_generate,
    openrouter_request_with_retry,
)
from decision_hub.settings import Settings, resolve_judge_provider

_MODEL = "qwen/qwen3.7-flash"
_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


def _chat_response(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


@pytest.fixture
def openrouter_client() -> dict:
    return create_openrouter_client("test-or-key")


class TestCreateClient:
    def test_client_carries_provider_field(self, openrouter_client: dict) -> None:
        assert openrouter_client["provider"] == "openrouter"
        assert openrouter_client["base_url"] == "https://openrouter.ai/api/v1"
        assert openrouter_client["api_key"] == "test-or-key"


class TestOpenRouterGenerate:
    @respx.mock
    def test_sends_bearer_auth_and_chat_payload(self, openrouter_client: dict) -> None:
        route = respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json=_chat_response("hello")))

        result = openrouter_generate(openrouter_client, _MODEL, "test prompt")

        assert result == "hello"
        request = route.calls[0].request
        assert request.headers["authorization"] == "Bearer test-or-key"
        payload = json.loads(request.content)
        assert payload["model"] == _MODEL
        assert payload["messages"] == [{"role": "user", "content": "test prompt"}]
        assert payload["temperature"] == 0.0
        assert payload["reasoning"] == {"enabled": False}

    @respx.mock
    def test_empty_choices_returns_empty_string(self, openrouter_client: dict) -> None:
        respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json={"choices": []}))
        assert openrouter_generate(openrouter_client, _MODEL, "p") == ""

    @respx.mock
    def test_null_content_returns_empty_string(self, openrouter_client: dict) -> None:
        respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": None}}]}))
        assert openrouter_generate(openrouter_client, _MODEL, "p") == ""


class TestOpenRouterRetry:
    @respx.mock
    def test_retries_on_429_then_succeeds(self, openrouter_client: dict) -> None:
        route = respx.post(_CHAT_URL).mock(
            side_effect=[
                httpx.Response(429, text="Rate limited"),
                httpx.Response(200, json=_chat_response("ok")),
            ]
        )
        with (
            patch("decision_hub.infra.openrouter.time.sleep") as mock_sleep,
            patch("decision_hub.infra.openrouter.random.uniform", return_value=0.25),
        ):
            result = openrouter_request_with_retry(openrouter_client, _CHAT_URL, {}, max_retries=3)
        assert result == _chat_response("ok")
        assert route.call_count == 2
        mock_sleep.assert_called_once_with(1.25)

    @respx.mock
    def test_non_retriable_error_raises_immediately(self, openrouter_client: dict) -> None:
        route = respx.post(_CHAT_URL).mock(return_value=httpx.Response(402, text="Payment required"))
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            openrouter_request_with_retry(openrouter_client, _CHAT_URL, {}, max_retries=3)
        assert exc_info.value.response.status_code == 402
        assert route.call_count == 1

    @respx.mock
    def test_raises_after_max_retries_exhausted(self, openrouter_client: dict) -> None:
        respx.post(_CHAT_URL).mock(return_value=httpx.Response(503, text="Unavailable"))
        with patch("decision_hub.infra.openrouter.time.sleep"), pytest.raises(httpx.HTTPStatusError) as exc_info:
            openrouter_request_with_retry(openrouter_client, _CHAT_URL, {}, max_retries=2)
        assert exc_info.value.response.status_code == 503


class TestJudgeDispatch:
    """The judge functions in infra.gemini dispatch on the client's provider field."""

    @respx.mock
    def test_classify_skill_routes_to_openrouter(self, openrouter_client: dict) -> None:
        respx.post(_CHAT_URL).mock(
            return_value=httpx.Response(
                200, json=_chat_response('```json\n{"category": "Content & Writing", "confidence": 0.9}\n```')
            )
        )
        result = classify_skill(openrouter_client, "humanize", "desc", "body", "taxonomy", model=_MODEL)
        # Markdown fences are stripped so the caller can json.loads directly
        assert json.loads(result) == {"category": "Content & Writing", "confidence": 0.9}

    @respx.mock
    def test_analyze_code_safety_routes_to_openrouter(self, openrouter_client: dict) -> None:
        judgment = [{"file": "a.py", "label": "subprocess invocation", "dangerous": False, "reason": "packing"}]
        respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json=_chat_response(json.dumps(judgment))))

        snippets = [{"file": "a.py", "label": "subprocess invocation", "line": "subprocess.run([...])"}]
        results = analyze_code_safety(openrouter_client, snippets, [("a.py", "code")], "s", "d", model=_MODEL)

        assert len(results) == 1
        assert results[0]["dangerous"] is False

    @respx.mock
    def test_analyze_code_safety_parses_concatenated_objects(self, openrouter_client: dict) -> None:
        """Qwen sometimes emits '{...}\\n{...}' instead of a JSON array on
        many-finding prompts. The parser must not fail-close the whole batch."""
        concatenated = (
            '{"file": "a.py", "label": "subprocess invocation", "dangerous": false, "reason": "git call"}\n'
            '{"file": "b.py", "label": "subprocess invocation", "dangerous": false, "reason": "list-form"}'
        )
        respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json=_chat_response(concatenated)))

        snippets = [
            {"file": "a.py", "label": "subprocess invocation", "line": "subprocess.run([...])"},
            {"file": "b.py", "label": "subprocess invocation", "line": "subprocess.run([...])"},
        ]
        files = [("a.py", "code"), ("b.py", "code")]
        results = analyze_code_safety(openrouter_client, snippets, files, "s", "d", model=_MODEL)

        assert len(results) == 2
        assert all(r["dangerous"] is False for r in results)

    @respx.mock
    def test_analyze_code_safety_fails_closed_on_empty_response(self, openrouter_client: dict) -> None:
        respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json={"choices": []}))
        snippets = [{"file": "a.py", "label": "subprocess invocation", "line": "subprocess.run([...])"}]
        results = analyze_code_safety(openrouter_client, snippets, [("a.py", "code")], "s", "d", model=_MODEL)
        assert results[0]["dangerous"] is True


class TestResolveJudgeProvider:
    def _settings(self, **overrides) -> Settings:
        base = {
            "database_url": "sqlite://",
            "s3_bucket": "b",
            "aws_access_key_id": "k",
            "aws_secret_access_key": "s",
            "github_client_id": "c",
            "jwt_secret": "j",
            "fernet_key": "f",
        }
        return Settings(_env_file=None, **base, **overrides)

    def test_defaults_to_openrouter_when_key_present(self) -> None:
        settings = self._settings(openrouter_api_key="or-key", google_api_key="g-key")
        assert resolve_judge_provider(settings) == "openrouter"

    def test_falls_back_to_gemini_without_openrouter_key(self) -> None:
        settings = self._settings(google_api_key="g-key")
        assert resolve_judge_provider(settings) == "gemini"

    def test_prefers_gemini_when_configured(self) -> None:
        settings = self._settings(openrouter_api_key="or-key", google_api_key="g-key", gauntlet_llm_provider="gemini")
        assert resolve_judge_provider(settings) == "gemini"

    def test_gemini_preference_falls_back_to_openrouter(self) -> None:
        settings = self._settings(openrouter_api_key="or-key", gauntlet_llm_provider="gemini")
        assert resolve_judge_provider(settings) == "openrouter"

    def test_none_when_no_keys(self) -> None:
        assert resolve_judge_provider(self._settings()) is None

    def test_judge_client_uses_openrouter_model(self) -> None:
        from decision_hub.domain.publish_pipeline import _create_judge_client

        settings = self._settings(openrouter_api_key="or-key")
        judge = _create_judge_client(settings)
        assert judge is not None
        client, model = judge
        assert client["provider"] == "openrouter"
        assert model == settings.openrouter_model

    def test_judge_client_falls_back_to_gemini(self) -> None:
        from decision_hub.domain.publish_pipeline import _create_judge_client

        settings = self._settings(google_api_key="g-key")
        judge = _create_judge_client(settings)
        assert judge is not None
        client, model = judge
        assert client.get("provider") is None
        assert model == settings.gemini_model

    def test_judge_client_none_without_keys(self) -> None:
        from decision_hub.domain.publish_pipeline import _create_judge_client

        assert _create_judge_client(self._settings()) is None
