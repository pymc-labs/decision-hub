"""Tests for decision_hub.api.client_ip — proxy-aware IP resolution."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from decision_hub.api.client_ip import client_ip


def _request(
    *,
    socket_host: str | None = "10.0.0.1",
    forwarded_for: str | None = None,
    trusted_proxy: bool = False,
    settings_present: bool = True,
):
    """Build a minimal Request stand-in with the surface client_ip uses."""
    req = MagicMock()
    req.client = SimpleNamespace(host=socket_host) if socket_host is not None else None
    if settings_present:
        req.app.state.settings = SimpleNamespace(trusted_proxy=trusted_proxy)
    else:
        # No settings on app.state at all — defensive fall-through.
        del req.app.state.settings
    req.headers = {"x-forwarded-for": forwarded_for} if forwarded_for else {}
    return req


def test_returns_socket_peer_when_proxy_not_trusted() -> None:
    assert client_ip(_request(socket_host="10.0.0.1")) == "10.0.0.1"


def test_ignores_forwarded_for_when_proxy_not_trusted() -> None:
    """An untrusted client must not be able to spoof their IP via XFF."""
    req = _request(socket_host="10.0.0.1", forwarded_for="203.0.113.99", trusted_proxy=False)
    assert client_ip(req) == "10.0.0.1"


def test_uses_forwarded_for_when_proxy_trusted() -> None:
    req = _request(socket_host="10.0.0.1", forwarded_for="203.0.113.99", trusted_proxy=True)
    assert client_ip(req) == "203.0.113.99"


def test_takes_first_address_in_forwarded_chain() -> None:
    req = _request(
        socket_host="10.0.0.1",
        forwarded_for="203.0.113.99, 198.51.100.1, 198.51.100.2",
        trusted_proxy=True,
    )
    assert client_ip(req) == "203.0.113.99"


def test_falls_back_to_socket_when_xff_blank() -> None:
    """Blank XFF should not be trusted; fall back to the socket peer."""
    req = _request(socket_host="10.0.0.1", forwarded_for=" ,  , ", trusted_proxy=True)
    assert client_ip(req) == "10.0.0.1"


def test_returns_unknown_when_no_client() -> None:
    req = _request(socket_host=None)
    assert client_ip(req) == "unknown"


def test_handles_missing_settings() -> None:
    """A request whose app has no settings on state must not crash."""
    req = _request(socket_host="10.0.0.2", settings_present=False)
    assert client_ip(req) == "10.0.0.2"
