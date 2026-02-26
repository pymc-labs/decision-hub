"""Organization management commands."""

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()
org_app = typer.Typer(help="Manage organizations", no_args_is_help=True)


@org_app.command("list")
def list_orgs() -> None:
    """List namespaces you can publish to."""
    from dhub.cli.config import build_headers, get_api_url, get_token, raise_for_status

    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{get_api_url()}/v1/orgs",
            headers=build_headers(get_token()),
        )
        raise_for_status(resp)
        orgs = resp.json()

    if not orgs:
        console.print("No namespaces available.")
        return

    table = Table(title="Namespaces")
    table.add_column("Slug", style="cyan")

    for org in orgs:
        table.add_row(org.get("slug", ""))

    console.print(table)
