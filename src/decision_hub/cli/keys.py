"""API key management commands."""

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()
keys_app = typer.Typer(help="Manage API keys for agent evals", no_args_is_help=True)


def _headers() -> dict[str, str]:
    """Build authorization headers using the stored token."""
    from decision_hub.cli.config import get_token

    return {"Authorization": f"Bearer {get_token()}"}


def _api_url() -> str:
    """Retrieve the configured API URL."""
    from decision_hub.cli.config import get_api_url

    return get_api_url()


@keys_app.command("add")
def add_key(
    key_name: str = typer.Argument(help="Name for the API key"),
) -> None:
    """Add an API key (prompts for the value securely)."""
    key_value = typer.prompt("Enter API key value", hide_input=True)

    if not key_value.strip():
        console.print("[red]Error: Key value cannot be empty.[/]")
        raise typer.Exit(1)

    with httpx.Client() as client:
        resp = client.post(
            f"{_api_url()}/v1/keys",
            headers=_headers(),
            json={"key_name": key_name, "value": key_value},
        )
        if resp.status_code == 409:
            console.print(
                f"[red]Error: Key '{key_name}' already exists. "
                "Remove it first with [bold]dhub keys remove[/bold].[/]"
            )
            raise typer.Exit(1)
        resp.raise_for_status()

    console.print(f"[green]Added key: {key_name}[/]")


@keys_app.command("list")
def list_keys() -> None:
    """List stored API key names."""
    with httpx.Client() as client:
        resp = client.get(
            f"{_api_url()}/v1/keys",
            headers=_headers(),
        )
        resp.raise_for_status()
        keys = resp.json()

    if not keys:
        console.print("No API keys stored.")
        return

    table = Table(title="API Keys")
    table.add_column("Name", style="cyan")
    table.add_column("Created", style="dim")

    for key in keys:
        table.add_row(key.get("key_name", ""), key.get("created_at", ""))

    console.print(table)


@keys_app.command("remove")
def remove_key(
    key_name: str = typer.Argument(help="Name of the API key to remove"),
) -> None:
    """Remove a stored API key."""
    with httpx.Client() as client:
        resp = client.delete(
            f"{_api_url()}/v1/keys/{key_name}",
            headers=_headers(),
        )
        if resp.status_code == 404:
            console.print(
                f"[red]Error: Key '{key_name}' not found.[/]"
            )
            raise typer.Exit(1)
        resp.raise_for_status()

    console.print(f"[green]Removed key: {key_name}[/]")
