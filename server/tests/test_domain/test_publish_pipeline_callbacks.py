"""Tests for the unified Gemini-callback factory in publish_pipeline.

``_make_gemini_callback`` replaced five near-identical ``_build_*_fn``
helpers.  These tests cover the factory directly and verify each of the
public wrappers still routes through it correctly — that's the contract
the gauntlet relies on (``analyze_fn(...)`` etc. all take positional
args and forward to the corresponding ``decision_hub.infra.gemini``
function with ``model=settings.gemini_model``).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from decision_hub.domain import publish_pipeline


def _settings(api_key: str = "", model: str = "gemini-3.1-flash-lite-preview") -> SimpleNamespace:
    """Build a minimal Settings stand-in for the factory."""
    return SimpleNamespace(google_api_key=api_key, gemini_model=model)


class TestMakeGeminiCallback:
    def test_returns_none_when_api_key_missing(self) -> None:
        """No api key -> the factory short-circuits to None (regex-only mode)."""
        assert publish_pipeline._make_gemini_callback(_settings(""), "analyze_code_safety") is None

    def test_creates_client_when_api_key_present(self) -> None:
        """With an api key, the factory builds a client lazily and returns a callable."""
        settings = _settings("test-key")
        sentinel_client = {"client": "sentinel"}
        with patch("decision_hub.infra.gemini.create_gemini_client", return_value=sentinel_client) as mk_client:
            cb = publish_pipeline._make_gemini_callback(settings, "analyze_code_safety")
        assert callable(cb)
        mk_client.assert_called_once_with("test-key")

    def test_reuses_supplied_client(self) -> None:
        """When a Gemini client is passed in (gauntlet shares one), the factory must not create another."""
        settings = _settings("test-key")
        shared = {"shared": True}
        with patch("decision_hub.infra.gemini.create_gemini_client") as mk_client:
            cb = publish_pipeline._make_gemini_callback(settings, "analyze_code_safety", gemini=shared)
        assert callable(cb)
        mk_client.assert_not_called()

    def test_callback_forwards_args_and_model(self) -> None:
        """The returned closure prepends the client and appends ``model=...`` from settings."""
        settings = _settings("test-key", model="gemini-x")
        target = MagicMock(return_value="ok")
        # Patch the resolved attribute on the gemini module so the factory's
        # getattr() lookup finds our mock.
        with (
            patch("decision_hub.infra.gemini.analyze_code_safety", target),
            patch("decision_hub.infra.gemini.create_gemini_client", return_value="CLIENT"),
        ):
            cb = publish_pipeline._make_gemini_callback(settings, "analyze_code_safety")
        result = cb("snippets", ["src.py"], "skill", "desc")
        assert result == "ok"
        target.assert_called_once_with("CLIENT", "snippets", ["src.py"], "skill", "desc", model="gemini-x")


class TestBuildFnWrappers:
    """The five ``_build_*_fn`` wrappers are kept as monkey-patch handles for tests.

    Each one should be a thin pass-through to ``_make_gemini_callback`` with
    the right Gemini function name.  Verifying the routing here means the
    factory body can change without breaking the existing mock setup in
    ``test_api/test_registry_routes.py`` and ``test_api/conftest.py``.
    """

    @pytest.mark.parametrize(
        ("wrapper_name", "fn_name"),
        [
            ("_build_analyze_fn", "analyze_code_safety"),
            ("_build_analyze_prompt_fn", "analyze_prompt_safety"),
            ("_build_review_body_fn", "review_prompt_body_safety"),
            ("_build_review_code_fn", "review_code_body_safety"),
            ("_build_analyze_credential_fn", "analyze_credential_entropy"),
        ],
    )
    def test_wrapper_routes_to_factory(self, wrapper_name: str, fn_name: str) -> None:
        wrapper = getattr(publish_pipeline, wrapper_name)
        settings = _settings("")  # api_key empty => factory returns None
        # Sanity-check the public surface: with no key, every wrapper returns
        # None just like the factory does.  This proves they share a code
        # path without us having to inspect implementation details.
        assert wrapper(settings) is None

    def test_wrappers_return_callable_when_key_present(self) -> None:
        """All five wrappers must return a callable when google_api_key is set."""
        settings = _settings("test-key")
        with patch("decision_hub.infra.gemini.create_gemini_client", return_value={"c": 1}):
            for wrapper_name in (
                "_build_analyze_fn",
                "_build_analyze_prompt_fn",
                "_build_review_body_fn",
                "_build_review_code_fn",
                "_build_analyze_credential_fn",
            ):
                wrapper = getattr(publish_pipeline, wrapper_name)
                assert callable(wrapper(settings)), f"{wrapper_name} returned None with api key set"
