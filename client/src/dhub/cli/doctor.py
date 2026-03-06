"""Diagnostic command to validate CLI environment."""

import time

import httpx
from rich.console import Console

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
    api_reachable = False
    latency_ms = 0
    try:
        start = time.monotonic()
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{api_url}/health")
            api_reachable = resp.status_code == 200
        latency_ms = int((time.monotonic() - start) * 1000)
    except httpx.HTTPError:
        pass

    result = {
        "env": env,
        "cli_version": cli_version,
        "authenticated": authenticated,
        "org": org,
        "api_url": api_url,
        "api_reachable": api_reachable,
        "api_latency_ms": latency_ms,
    }

    if is_json():
        print_json(result)
        return

    console.print()
    _check(authenticated, "Authenticated" + (f" (org: {org})" if org else ""))
    _check(api_reachable, f"API reachable at {api_url} ({latency_ms}ms)")
    console.print(f"  [dim]--[/]   CLI version: {cli_version}")
    console.print(f"  [dim]--[/]   Environment: {env}")
    console.print()


def _check(ok: bool, msg: str) -> None:
    """Print a status check line with OK/FAIL indicator."""
    icon = "[green]OK[/]" if ok else "[red]FAIL[/]"
    console.print(f"  {icon}  {msg}")
