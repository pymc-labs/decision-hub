"""Diagnostic command to validate CLI environment."""

import time

import httpx
from rich.console import Console
from rich.markup import escape

from dhub.cli.config import get_api_url, get_client_version, get_env, get_optional_token, load_config
from dhub.cli.output import is_json, print_json

console = Console()


def doctor_command() -> None:
    """Check CLI configuration, authentication, and API connectivity."""
    env = get_env()
    api_url = get_api_url()
    token = get_optional_token()
    config = load_config()
    cli_version = get_client_version()

    authenticated = token is not None
    org = config.default_org or (config.orgs[0] if len(config.orgs) == 1 else None)

    # Check API connectivity
    api_error: str | None = None
    latency_ms = 0
    try:
        start = time.monotonic()
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{api_url}/health")
            latency_ms = int((time.monotonic() - start) * 1000)
        api_error = _health_error(resp)
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
        # ValueError here comes from httpx configuration (e.g. an unsupported
        # HTTPS_PROXY scheme); report it instead of hiding it behind a bare FAIL.
        api_error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    api_reachable = api_error is None

    result = {
        "env": env,
        "cli_version": cli_version,
        "authenticated": authenticated,
        "org": org,
        "api_url": api_url,
        "api_reachable": api_reachable,
        "api_latency_ms": latency_ms,
        "api_error": api_error,
    }

    if is_json():
        print_json(result)
        return

    console.print()
    _check(authenticated, "Authenticated" + (f" (org: {org})" if org else ""))
    _check(api_reachable, f"API reachable at {escape(api_url)} ({latency_ms}ms)")
    if api_error:
        console.print(f"        [dim]{escape(api_error)}[/]")
    console.print(f"  [dim]--[/]   CLI version: {cli_version}")
    console.print(f"  [dim]--[/]   Environment: {env}")
    console.print()


def _health_error(resp: httpx.Response) -> str | None:
    """Explain why a /health response is not a healthy Decision Hub API, or return None.

    A stale deployment or website host can answer /health with its HTML
    fallback page and HTTP 200, so the status code alone does not prove the
    URL points at a working registry. The server contract is HTTP 200 with
    ``{"status": "ok", "database": "ok"}``; it answers 503 when the database
    is unreachable.
    """
    if resp.status_code != 200:
        return f"/health returned HTTP {resp.status_code}"
    try:
        health = resp.json()
    except ValueError:
        return "/health did not return JSON; is this a Decision Hub API URL?"
    if not isinstance(health, dict) or health.get("status") != "ok":
        return "/health returned an unexpected payload; is this a Decision Hub API URL?"
    if health.get("database") != "ok":
        return "server reports its database is unavailable"
    return None


def _check(ok: bool, msg: str) -> None:
    """Print a status check line with OK/FAIL indicator."""
    icon = "[green]OK[/]" if ok else "[red]FAIL[/]"
    console.print(f"  {icon}  {msg}")
