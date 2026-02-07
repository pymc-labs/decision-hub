"""Login via GitHub Device Flow."""

import time

import httpx
import typer
from rich.console import Console
from rich.panel import Panel

console = Console()


def login_command(
    api_url: str = typer.Option(None, "--api-url", help="API URL override"),
) -> None:
    """Authenticate with Decision Hub via GitHub."""
    from dhub.cli.config import CliConfig, build_headers, get_api_url, save_config

    base_url = api_url or get_api_url()

    # Step 1: Request a device code from the API
    with httpx.Client(timeout=60) as client:
        resp = client.post(f"{base_url}/auth/github/code", headers=build_headers())
        resp.raise_for_status()
        data = resp.json()

    device_code: str = data["device_code"]
    user_code: str = data["user_code"]
    verification_uri: str = data["verification_uri"]
    poll_interval: int = data.get("interval", 5)

    # Step 2: Show the user code and URL
    console.print(
        Panel(
            f"Open [bold blue]{verification_uri}[/] and enter code: "
            f"[bold green]{user_code}[/]",
            title="GitHub Login",
        )
    )
    # Step 3: Poll for the token until the user completes the flow
    with console.status("Waiting for authorization..."):
        token_data = _poll_for_token(base_url, device_code, poll_interval)

    # Step 4: Persist the token and synced orgs
    orgs = tuple(token_data.get("orgs", ()))
    default_org = _prompt_default_org(orgs)

    new_config = CliConfig(
        api_url=base_url,
        token=token_data["access_token"],
        orgs=orgs,
        default_org=default_org,
    )
    save_config(new_config)

    console.print(f"[green]Authenticated as @{token_data['username']}[/]")
    if orgs:
        console.print(f"Namespaces: {', '.join(orgs)}")
    if default_org:
        console.print(f"Default namespace: [cyan]{default_org}[/]")


def logout_command() -> None:
    """Log out by removing the stored token."""
    from dhub.cli.config import CliConfig, load_config, save_config

    config = load_config()
    if not config.token:
        console.print("Not logged in.")
        return

    save_config(CliConfig(api_url=config.api_url, token=None, orgs=(), default_org=None))
    console.print("[green]Logged out.[/]")


def _prompt_default_org(orgs: tuple[str, ...]) -> str | None:
    """Prompt the user to set a default namespace if they have multiple.

    Returns the chosen org slug, or None if only one org or user declines.
    """
    if len(orgs) <= 1:
        return orgs[0] if orgs else None

    console.print("\nYou belong to multiple namespaces.")
    choices = list(orgs) + ["(none)"]
    choice = console.input(
        f"Set a default namespace for publishing? [{'/'.join(orgs)}/(none)]: "
    ).strip().lower()

    if choice in orgs:
        return choice
    if not choice:
        # Default to first org
        return orgs[0]
    return None


def _poll_for_token(
    base_url: str,
    device_code: str,
    interval: int,
    timeout_seconds: int = 300,
) -> dict:
    """Poll the token endpoint until authorization succeeds or times out.

    Args:
        base_url: API base URL.
        device_code: The device code returned from the code request.
        interval: Seconds to wait between poll attempts.
        timeout_seconds: Maximum total seconds to wait before giving up.

    Returns:
        Parsed JSON response containing 'access_token' and 'username'.

    Raises:
        typer.Exit: If the flow times out or the server rejects the request.
    """
    deadline = time.monotonic() + timeout_seconds

    from dhub.cli.config import build_headers

    with httpx.Client(timeout=60) as client:
        while time.monotonic() < deadline:
            resp = client.post(
                f"{base_url}/auth/github/token",
                json={"device_code": device_code},
                headers=build_headers(),
            )

            if resp.status_code == 200:
                return resp.json()

            # 428 means "authorization_pending" -- keep polling
            if resp.status_code == 428:
                time.sleep(interval)
                continue

            # Any other error is fatal
            resp.raise_for_status()

    console.print("[red]Error: Login timed out. Please try again.[/]")
    raise typer.Exit(1)
