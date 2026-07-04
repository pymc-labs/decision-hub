"""Organization management commands."""

import typer
from rich.console import Console
from rich.table import Table

console = Console()
org_app = typer.Typer(help="Manage organizations", no_args_is_help=True)


@org_app.command("list")
def list_orgs() -> None:
    """List namespaces you can publish to."""
    from dhub.cli.config import get_token, raise_for_status
    from dhub.cli.http import api_client

    with api_client(token=get_token()) as client:
        resp = client.get("/v1/orgs")
        raise_for_status(resp)
        orgs = resp.json()

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
