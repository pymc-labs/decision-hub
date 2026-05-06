"""Tests for the shared :class:`dhub.cli.api_client.APIClient` wrapper."""

from unittest.mock import patch

import httpx
import pytest
import respx

from dhub.cli.api_client import (
    APIClient,
    anonymous_client,
    authed_client,
    optional_client,
)

# ---------------------------------------------------------------------------
# Header injection
# ---------------------------------------------------------------------------


@respx.mock
def test_authed_request_sends_bearer_and_version_headers() -> None:
    route = respx.get("https://api.example.com/v1/skills").mock(return_value=httpx.Response(200, json=[]))

    with APIClient("https://api.example.com", token="t-123") as api:
        api.get("/v1/skills")

    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer t-123"
    assert sent.headers["x-dhub-client-version"]  # populated from importlib.metadata


@respx.mock
def test_anonymous_request_omits_authorization_header() -> None:
    route = respx.get("https://api.example.com/health").mock(return_value=httpx.Response(200))

    with APIClient("https://api.example.com", token=None) as api:
        api.get("/health")

    assert "authorization" not in route.calls.last.request.headers


@respx.mock
def test_trailing_slash_in_base_url_is_stripped() -> None:
    route = respx.get("https://api.example.com/v1/orgs").mock(return_value=httpx.Response(200, json=[]))

    with APIClient("https://api.example.com/", token=None) as api:
        api.get("/v1/orgs")

    assert route.called
    assert str(route.calls.last.request.url) == "https://api.example.com/v1/orgs"


# ---------------------------------------------------------------------------
# Status-code semantics: ``check`` flag
# ---------------------------------------------------------------------------


@respx.mock
def test_check_true_raises_on_5xx() -> None:
    respx.get("https://api.example.com/boom").mock(return_value=httpx.Response(500, text="kaboom"))

    with APIClient("https://api.example.com", token=None) as api, pytest.raises(httpx.HTTPStatusError):
        api.get("/boom")


@respx.mock
def test_check_false_lets_caller_inspect_404() -> None:
    respx.get("https://api.example.com/missing").mock(return_value=httpx.Response(404, json={"detail": "nope"}))

    with APIClient("https://api.example.com", token=None) as api:
        resp = api.get("/missing", check=False)

    assert resp.status_code == 404
    assert resp.json() == {"detail": "nope"}


@respx.mock
def test_426_upgrade_triggers_fatal_exit() -> None:
    """The friendly 426 → SystemExit conversion in ``raise_for_status``
    must keep working through ``APIClient.request`` so users still get
    the upgrade message instead of an httpx traceback. ``fatal=True``
    raises ``SystemExit`` (not ``typer.Exit``) so batch loops that
    catch ``typer.Exit`` per-item don't accidentally swallow it."""
    respx.get("https://api.example.com/v1/skills").mock(return_value=httpx.Response(426, json={"detail": "old CLI"}))

    with APIClient("https://api.example.com", token=None) as api, pytest.raises(SystemExit):
        api.get("/v1/skills")


# ---------------------------------------------------------------------------
# Verb helpers
# ---------------------------------------------------------------------------


@respx.mock
def test_post_put_patch_delete_round_trip() -> None:
    """All verb helpers go through the same code path, but smoke-test
    each so a typo in the wrapper would surface immediately."""
    respx.post("https://api.example.com/v1/x").mock(return_value=httpx.Response(201, json={"v": "post"}))
    respx.put("https://api.example.com/v1/x").mock(return_value=httpx.Response(200, json={"v": "put"}))
    respx.patch("https://api.example.com/v1/x").mock(return_value=httpx.Response(200, json={"v": "patch"}))
    respx.delete("https://api.example.com/v1/x").mock(return_value=httpx.Response(200, json={"v": "delete"}))

    with APIClient("https://api.example.com", token=None) as api:
        assert api.post("/v1/x", json={}).json() == {"v": "post"}
        assert api.put("/v1/x", json={}).json() == {"v": "put"}
        assert api.patch("/v1/x", json={}).json() == {"v": "patch"}
        assert api.delete("/v1/x").json() == {"v": "delete"}


@respx.mock
def test_absolute_url_bypasses_base_url() -> None:
    """``request`` accepts an absolute URL without prepending the base —
    used for things like presigned S3 download URLs (though we now use
    raw httpx for those, this keeps the wrapper general-purpose)."""
    route = respx.get("https://other.example.com/zip").mock(return_value=httpx.Response(200, content=b"PK"))

    with APIClient("https://api.example.com", token=None) as api:
        resp = api.get("https://other.example.com/zip")

    assert route.called
    assert resp.content == b"PK"


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


@respx.mock
@patch("dhub.cli.config.get_token", return_value="from-saved-config")
@patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
def test_authed_client_pulls_token_from_config(_mock_url, _mock_token) -> None:
    route = respx.get("http://test:8000/v1/keys").mock(return_value=httpx.Response(200, json=[]))

    with authed_client() as api:
        api.get("/v1/keys")

    assert route.calls.last.request.headers["authorization"] == "Bearer from-saved-config"


@respx.mock
@patch("dhub.cli.config.get_optional_token", return_value=None)
@patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
def test_optional_client_works_without_token(_mock_url, _mock_token) -> None:
    route = respx.get("http://test:8000/v1/skills").mock(return_value=httpx.Response(200, json=[]))

    with optional_client() as api:
        api.get("/v1/skills")

    assert "authorization" not in route.calls.last.request.headers


@respx.mock
@patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
def test_anonymous_client_never_sends_authorization(_mock_url) -> None:
    route = respx.post("http://test:8000/auth/github/code").mock(return_value=httpx.Response(200, json={}))

    with anonymous_client() as api:
        api.post("/auth/github/code")

    assert "authorization" not in route.calls.last.request.headers
