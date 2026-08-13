"""Tests for the OpenRouter transport and provider dispatch."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx

from decision_hub.infra.gemini import analyze_code_safety, ask_conversational, classify_skill, parse_query_with_guard
from decision_hub.infra.openrouter import (
    DEFAULT_MAX_TOKENS,
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
        assert openrouter_client["providers"] == []


class TestProviderRouting:
    """Every request pins routing policy so verdicts stay reproducible."""

    @respx.mock
    def test_sends_default_routing_policy(self, openrouter_client: dict) -> None:
        route = respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json=_chat_response("ok")))

        openrouter_generate(openrouter_client, _MODEL, "p")

        routing = json.loads(route.calls[0].request.content)["provider"]
        # Skill source code is in the prompt — never route it to a provider
        # that may retain or train on it.
        assert routing["data_collection"] == "deny"
        assert routing["require_parameters"] is True
        # No quantization filter: providers that declare none are excluded
        # by it, which for qwen/qwen3.7-flash means all of them (404).
        assert "quantizations" not in routing
        # Unpinned: OpenRouter may pick any provider satisfying the policy
        assert "order" not in routing
        assert "allow_fallbacks" not in routing

    @respx.mock
    def test_pinned_providers_disable_fallback(self) -> None:
        client = create_openrouter_client("k", providers=["deepinfra", "fireworks"])
        route = respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json=_chat_response("ok")))

        openrouter_generate(client, _MODEL, "p")

        routing = json.loads(route.calls[0].request.content)["provider"]
        assert routing["order"] == ["deepinfra", "fireworks"]
        assert routing["allow_fallbacks"] is False
        assert routing["data_collection"] == "deny"

    @respx.mock
    def test_pin_does_not_mutate_shared_policy(self) -> None:
        """The policy dict is module-level; pinning must copy, not mutate it."""
        pinned = create_openrouter_client("k", providers=["deepinfra"])
        respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json=_chat_response("ok")))
        openrouter_generate(pinned, _MODEL, "p")

        route = respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json=_chat_response("ok")))
        openrouter_generate(create_openrouter_client("k"), _MODEL, "p")

        assert "order" not in json.loads(route.calls[-1].request.content)["provider"]


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
        # Never left to the provider default, which varies by upstream host
        assert payload["max_tokens"] == DEFAULT_MAX_TOKENS

    @respx.mock
    def test_max_tokens_override(self, openrouter_client: dict) -> None:
        route = respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json=_chat_response("hi")))

        openrouter_generate(openrouter_client, _MODEL, "p", max_tokens=1024)

        assert json.loads(route.calls[0].request.content)["max_tokens"] == 1024

    @respx.mock
    def test_empty_choices_returns_empty_string(self, openrouter_client: dict) -> None:
        respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json={"choices": []}))
        assert openrouter_generate(openrouter_client, _MODEL, "p") == ""

    @respx.mock
    def test_null_content_returns_empty_string(self, openrouter_client: dict) -> None:
        respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": None}}]}))
        assert openrouter_generate(openrouter_client, _MODEL, "p") == ""


class TestTruncationLogging:
    """Truncation must be distinguishable from a garbage response in logs.

    Both fail closed to grade F, so without a distinct signal there is no
    way to tell a too-small token cap from a model that returned junk.
    """

    @respx.mock
    def test_warns_when_finish_reason_is_length(self, openrouter_client: dict) -> None:
        respx.post(_CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "provider": "deepinfra",
                    "usage": {"completion_tokens": 16384},
                    "choices": [{"finish_reason": "length", "message": {"content": '[{"file": "a.py"'}}],
                },
            )
        )

        with patch("decision_hub.infra.openrouter.logger.warning") as mock_warn:
            result = openrouter_generate(openrouter_client, _MODEL, "p")

        assert result == '[{"file": "a.py"'  # partial content still returned
        assert mock_warn.call_count == 1
        assert "truncated" in mock_warn.call_args[0][0]

    @respx.mock
    def test_no_warning_on_normal_stop(self, openrouter_client: dict) -> None:
        respx.post(_CHAT_URL).mock(
            return_value=httpx.Response(
                200, json={"choices": [{"finish_reason": "stop", "message": {"content": "[]"}}]}
            )
        )

        with patch("decision_hub.infra.openrouter.logger.warning") as mock_warn:
            openrouter_generate(openrouter_client, _MODEL, "p")

        mock_warn.assert_not_called()

    @respx.mock
    def test_no_crash_on_empty_choices(self, openrouter_client: dict) -> None:
        respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json={"choices": []}))
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
    def test_parse_query_with_guard_routes_to_openrouter(self, openrouter_client: dict) -> None:
        respx.post(_CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                json=_chat_response(
                    '{"is_skill_query": true, "reason": "on-topic", "fts_queries": ["bayesian model"]}'
                ),
            )
        )
        result = parse_query_with_guard(openrouter_client, "help me build a bayesian model", _MODEL)
        assert result.is_skill_query is True
        assert result.fts_queries == ["bayesian model"]

    @respx.mock
    def test_parse_query_with_guard_fails_open_on_error(self, openrouter_client: dict) -> None:
        respx.post(_CHAT_URL).mock(return_value=httpx.Response(200, json=_chat_response("not json")))
        result = parse_query_with_guard(openrouter_client, "some query", _MODEL)
        assert result.is_skill_query is True
        assert result.fts_queries == ["some query"]

    @respx.mock
    def test_ask_conversational_routes_to_openrouter(self, openrouter_client: dict) -> None:
        answer = {
            "answer": "Use **acme/weather**.",
            "referenced_skills": [{"org_slug": "acme", "skill_name": "weather", "reason": "fits"}],
        }
        respx.post(_CHAT_URL).mock(
            return_value=httpx.Response(200, json=_chat_response(f"```json\n{json.dumps(answer)}\n```"))
        )
        result = ask_conversational(openrouter_client, "weather tool?", "{}", _MODEL)
        assert result["answer"] == "Use **acme/weather**."
        assert result["referenced_skills"] == answer["referenced_skills"]

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

    def test_provider_pin_reaches_the_client(self) -> None:
        from decision_hub.domain.publish_pipeline import _create_judge_client

        settings = self._settings(openrouter_api_key="or-key", openrouter_providers="deepinfra, fireworks")
        judge = _create_judge_client(settings)
        assert judge is not None
        assert judge[0]["providers"] == ["deepinfra", "fireworks"]

    def test_empty_provider_pin_yields_no_pin(self) -> None:
        from decision_hub.domain.publish_pipeline import _create_judge_client

        judge = _create_judge_client(self._settings(openrouter_api_key="or-key"))
        assert judge is not None
        assert judge[0]["providers"] == []

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
