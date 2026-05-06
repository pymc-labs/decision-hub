"""Organization management commands."""

import typer
from rich.console import Console
from rich.table import Table

from dhub.cli.api_client import authed_client

console = Console()
org_app = typer.Typer(help="Manage organizations", no_args_is_help=True)


@org_app.command("list")
def list_orgs() -> None:
    """List namespaces you can publish to."""
    with authed_client() as api:
        orgs = api.get("/v1/orgs").json()

    from dhub.cli.output import is_json, print_json

    if is_json():
        print_json(orgs)
        return

    if not orgs:
        console.print("No namespaces available.")
        return

    table = Table(title="Namespaces")
    table.add_column("Slug", style="cyan")

    for org in orgs:
        table.add_row(org.get("slug", ""))

    console.print(table)
