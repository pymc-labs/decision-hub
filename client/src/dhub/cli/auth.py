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
    from dhub.cli.config import CliConfig, get_api_url, save_config

    base_url = api_url or get_api_url()

    # Step 1: Request a device code from the API
    with httpx.Client() as client:
        resp = client.post(f"{base_url}/auth/github/code")
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
    console.print("Waiting for authorization...")

    # Step 3: Poll for the token until the user completes the flow
    token_data = _poll_for_token(base_url, device_code, poll_interval)

    # Step 4: Persist the token
    new_config = CliConfig(api_url=base_url, token=token_data["access_token"])
    save_config(new_config)

    console.print(f"[green]Authenticated as @{token_data['username']}[/]")


def logout_command() -> None:
    """Log out by removing the stored token."""
    from dhub.cli.config import CliConfig, load_config, save_config

    config = load_config()
    if not config.token:
        console.print("Not logged in.")
        return

    save_config(CliConfig(api_url=config.api_url, token=None))
    console.print("[green]Logged out.[/]")


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

    with httpx.Client(timeout=30) as client:
        while time.monotonic() < deadline:
            resp = client.post(
                f"{base_url}/auth/github/token",
                json={"device_code": device_code},
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
