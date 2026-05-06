"""Thin HTTP wrapper around httpx for talking to the Decision Hub API.

Every CLI command used to open its own ``httpx.Client(timeout=60)``, build
``X-DHub-Client-Version`` + ``Authorization`` headers by hand, and call
``raise_for_status()`` (or its 426-aware sibling) ad-hoc. ``APIClient``
collapses that boilerplate to one place so:

* a new command is ~10 LOC instead of ~30,
* the timeout, version header, and 426-Upgrade-Required handling are
  guaranteed to be applied everywhere,
* tests can keep using ``respx`` without changes — the underlying
  ``httpx.Client`` still issues the same fully-qualified URLs.

The class is a context manager so callers retain the explicit
open/close lifecycle they had with raw ``httpx.Client``.
"""

from __future__ import annotations

from typing import Any

import httpx

# Import the module rather than the individual names so callers can
# ``@patch("dhub.cli.config.get_token")`` and have it apply here too.
# Binding ``get_token`` directly would freeze the reference at import
# time and silently bypass per-test mocks.
from dhub.cli import config as _config

DEFAULT_TIMEOUT = 60.0


class APIClient:
    """Authenticated HTTP client for the Decision Hub API."""

    def __init__(
        self,
        api_url: str | None = None,
        token: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._api_url = (api_url or _config.get_api_url()).rstrip("/")
        self._token = token
        self._client = httpx.Client(timeout=timeout, headers=_config.build_headers(token))

    # -- lifecycle -------------------------------------------------------

    def __enter__(self) -> APIClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- properties ------------------------------------------------------

    @property
    def api_url(self) -> str:
        return self._api_url

    # -- request helpers -------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        check: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue a request to ``path`` (relative or absolute).

        ``check=True`` (default) calls :func:`raise_for_status` from
        ``cli.config`` so 426 produces the friendly upgrade message.
        Pass ``check=False`` when the caller needs to inspect specific
        status codes (e.g. ``404`` to mean "not found").
        """
        url = path if path.startswith(("http://", "https://")) else f"{self._api_url}{path}"
        resp = self._client.request(method, url, **kwargs)
        if check:
            _config.raise_for_status(resp)
        return resp

    def get(self, path: str, *, check: bool = True, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, check=check, **kwargs)

    def post(self, path: str, *, check: bool = True, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, check=check, **kwargs)

    def put(self, path: str, *, check: bool = True, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", path, check=check, **kwargs)

    def patch(self, path: str, *, check: bool = True, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", path, check=check, **kwargs)

    def delete(self, path: str, *, check: bool = True, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", path, check=check, **kwargs)


# ---------------------------------------------------------------------------
# Convenience constructors — these mirror the patterns already used by every
# CLI command, but make the auth requirement explicit at the call site.
# ---------------------------------------------------------------------------


def authed_client(*, timeout: float = DEFAULT_TIMEOUT) -> APIClient:
    """Return an :class:`APIClient` bound to the current saved token.

    Exits the process via :func:`dhub.cli.config.get_token` when no token
    is configured.
    """
    return APIClient(token=_config.get_token(), timeout=timeout)


def optional_client(*, timeout: float = DEFAULT_TIMEOUT) -> APIClient:
    """Return an :class:`APIClient` for endpoints that work anonymously.

    Carries the saved token when present so private skills remain
    accessible, but does not exit when the user is not logged in.
    """
    return APIClient(token=_config.get_optional_token(), timeout=timeout)


def anonymous_client(*, timeout: float = DEFAULT_TIMEOUT) -> APIClient:
    """Return an :class:`APIClient` with no auth header.

    Used for endpoints where bearing a token would be wrong (the device
    flow's code/token endpoints, public ``/health`` checks).
    """
    return APIClient(token=None, timeout=timeout)
