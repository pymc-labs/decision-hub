"""Tests for ``decision_hub.api.client_ip.client_ip``.

The helper exists to fix a real production hazard: behind Modal (or any
reverse proxy) ``request.client.host`` is the proxy's IP, identical for
every real client, so the per-IP rate limiter and the per-IP auth log
collapse to a single bucket.  These tests pin the proxy-aware semantics.
"""

from unittest.mock import MagicMock

from decision_hub.api.client_ip import client_ip


def _make_request(*, client_host: str | None = "10.0.0.1", forwarded: str | None = None) -> MagicMock:
    """Build a minimal mock ``Request`` for the helper.

    A real Starlette ``Request`` exposes ``client.host`` and ``headers`` —
    both of which the helper reads.  Using a plain ``MagicMock`` keeps the
    test independent of FastAPI / Starlette internals.
    """
    request = MagicMock()
    if client_host is None:
        request.client = None
    else:
        request.client.host = client_host
    request.headers = {"x-forwarded-for": forwarded} if forwarded is not None else {}
    return request


def test_zero_proxies_ignores_forwarded_for() -> None:
    """With ``trusted_proxy_count=0`` the header is ignored entirely.

    A client could spoof X-Forwarded-For locally; trusting it without an
    explicit deployment opt-in would let any client get a fresh per-IP
    bucket per request.
    """
    req = _make_request(client_host="10.0.0.1", forwarded="1.2.3.4, 5.6.7.8")
    assert client_ip(req, trusted_proxy_count=0) == "10.0.0.1"


def test_one_proxy_strips_one_hop_from_right() -> None:
    """Modal sits one hop in front of the app: skip exactly one entry."""
    # Header layout: <client>, <proxy1>
    req = _make_request(client_host="172.16.0.1", forwarded="203.0.113.5, 172.16.0.1")
    assert client_ip(req, trusted_proxy_count=1) == "203.0.113.5"


def test_two_proxies_strip_two_hops_from_right() -> None:
    """Multi-hop deployments: client, proxy1, proxy2 — skip two from the right."""
    req = _make_request(forwarded="203.0.113.5, 10.0.0.1, 172.16.0.1")
    assert client_ip(req, trusted_proxy_count=2) == "203.0.113.5"


def test_short_chain_falls_back_to_leftmost() -> None:
    """If declared proxy count exceeds the chain length, return the leftmost.

    Per the X-Forwarded-For convention the leftmost entry is the closest
    we have to "the originating client", so it is the right fallback.
    """
    req = _make_request(forwarded="203.0.113.5")
    assert client_ip(req, trusted_proxy_count=5) == "203.0.113.5"


def test_missing_header_falls_back_to_request_client() -> None:
    """Trusted-proxy mode set but header absent — fall through to client.host."""
    req = _make_request(client_host="10.0.0.1", forwarded=None)
    assert client_ip(req, trusted_proxy_count=1) == "10.0.0.1"


def test_no_client_returns_unknown() -> None:
    """When request.client is ``None`` and no header is present, return ``unknown``."""
    req = _make_request(client_host=None, forwarded=None)
    assert client_ip(req, trusted_proxy_count=0) == "unknown"


def test_strips_whitespace_around_forwarded_entries() -> None:
    """Real proxies often emit ``a, b, c`` with surrounding spaces."""
    req = _make_request(forwarded="  203.0.113.5 ,  172.16.0.1 ")
    assert client_ip(req, trusted_proxy_count=1) == "203.0.113.5"
