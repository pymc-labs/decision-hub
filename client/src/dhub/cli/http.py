"""Shared HTTP client for CLI commands.

Every CLI command that talks to the Decision Hub API used to open its own
``httpx.Client(timeout=60)``, then hand-invoke ``build_headers`` and
``raise_for_status`` from :mod:`dhub.cli.config`. That pattern was copied to
~40 call sites, each one having to remember to attach the ``X-DHub-Client-Version``
header and the 60-second timeout. This module centralises it.

Usage::

    from dhub.cli.http import api_client
    from dhub.cli.config import get_token, raise_for_status

    with api_client(token=get_token()) as client:
        resp = client.get("/v1/keys")
        raise_for_status(resp)
        keys = resp.json()

The context manager returns a fully-configured :class:`httpx.Client` with
``base_url`` set to the current API URL (from :func:`dhub.cli.config.get_api_url`),
authentication + client-version headers pre-attached, and a 60-second timeout.
Individual commands can still pass absolute URLs or override the timeout when
they need to (e.g. ``dhub doctor`` uses a tighter latency probe).
"""

from collections.abc import Iterator
from contextlib import contextmanager

import httpx

# Default per-call timeout, in seconds. Tuned for the slowest legitimate
# server call (large publish, eval report fetch). Individual commands can
# override this — see ``dhub doctor`` and the PyPI version check.
DEFAULT_TIMEOUT_SECONDS: float = 60.0


@contextmanager
def api_client(
    *,
    token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    base_url: str | None = None,
) -> Iterator[httpx.Client]:
    """Yield an :class:`httpx.Client` configured for the Decision Hub API.

    Args:
        token: Bearer token to include on every request. Pass the result of
            :func:`dhub.cli.config.get_token` for authenticated commands or
            :func:`dhub.cli.config.get_optional_token` for commands that
            work anonymously.
        timeout: Total request timeout in seconds. Defaults to 60. Pass a
            smaller value for health probes.
        base_url: Override the API URL. Defaults to
            :func:`dhub.cli.config.get_api_url`; explicit override useful for
            tests and for commands that hit a fixed URL (e.g. PyPI).

    The returned client:

    * has ``base_url`` set so callers can pass path-only URLs like
      ``client.get("/v1/keys")``;
    * attaches ``X-DHub-Client-Version`` (and ``Authorization`` when *token*
      is provided) to every request;
    * has the standard :attr:`timeout`.

    Absolute URLs still work — :class:`httpx.Client` respects them regardless
    of ``base_url``.
    """
    # Local import to keep CLI startup latency low. `config` transitively
    # imports typer.Console, which is heavy.
    from dhub.cli.config import build_headers, get_api_url

    resolved_base_url = (base_url or get_api_url()).rstrip("/")
    headers = build_headers(token)

    with httpx.Client(base_url=resolved_base_url, headers=headers, timeout=timeout) as client:
        yield client
