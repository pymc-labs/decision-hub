"""Resolve the originating client IP for a request.

When the API runs behind a load balancer (Modal, CloudFlare, …) the raw socket
peer reported by ``request.client`` is the proxy, not the originating client.
For per-IP rate limiting and security log lines we want the real client.

This module honors ``X-Forwarded-For`` only when the application has been
configured to trust the proxy via ``Settings.trusted_proxy``. That guard is
critical: a public service that blindly trusts ``X-Forwarded-For`` lets any
caller spoof their IP and bypass per-IP rate limits.

If the header is absent, malformed, or untrusted, we fall back to the socket
peer (and finally to the literal string ``"unknown"`` so dictionaries always
have a usable key).
"""

from fastapi import Request


def client_ip(request: Request) -> str:
    """Return the originating client IP, honoring trusted forwarded headers.

    Resolution order:

    1. If ``Settings.trusted_proxy`` is true and ``X-Forwarded-For`` is present,
       return the **first** address in the header (the original client; later
       entries are intermediate proxies).
    2. Otherwise return ``request.client.host`` (the socket peer).
    3. If the request has no client (e.g. ASGI test transport), return
       ``"unknown"``.
    """
    settings = getattr(request.app.state, "settings", None)
    trust_proxy = bool(getattr(settings, "trusted_proxy", False))

    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Header format: "client, proxy1, proxy2". Take the leftmost
            # non-empty entry. Strip whitespace; ignore obviously empty values.
            first = forwarded.split(",", 1)[0].strip()
            if first:
                return first

    if request.client is not None:
        return request.client.host

    return "unknown"
