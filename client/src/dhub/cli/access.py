"""CLI commands for managing access grants on private skills."""

import httpx
import typer
from rich.console import Console
from rich.table import Table as RichTable

console = Console()

access_app = typer.Typer(
    name="access",
    no_args_is_help=True,
    help="Manage access grants for private skills.",
)


@access_app.command("grant")
def grant_command(
    skill_ref: str = typer.Argument(help="Skill name (e.g. 'myorg/my-skill')"),
    grantee: str = typer.Argument(help="Org or user slug to grant access to"),
) -> None:
    """Grant an org or user access to a private skill.

    Since every user has a personal org (their username), granting access
    to a user is the same as granting to their personal org.
    """
    from dhub.cli.config import build_headers, get_api_url, get_token

    parts = skill_ref.split("/", 1)
    if len(parts) != 2:
        console.print("[red]Error: Skill reference must be in org/skill format.[/]")
        raise typer.Exit(1)
    org_slug, skill_name = parts

    api_url = get_api_url()
    headers = build_headers(get_token())
    headers["Content-Type"] = "application/json"

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{api_url}/v1/skills/{org_slug}/{skill_name}/access",
            headers=headers,
            json={"grantee_org_slug": grantee},
        )
        if resp.status_code == 404:
            detail = resp.json().get("detail", "Not found")
            console.print(f"[red]Error: {detail}[/]")
            raise typer.Exit(1)
        if resp.status_code == 403:
            console.print("[red]Error: Only org admins can manage access grants.[/]")
            raise typer.Exit(1)
        if resp.status_code == 409:
            console.print(f"[yellow]Access already granted to '{grantee}'.[/]")
            raise typer.Exit(1)
        resp.raise_for_status()

    console.print(f"[green]Granted access to '{grantee}' for {org_slug}/{skill_name}[/]")


@access_app.command("revoke")
def revoke_command(
    skill_ref: str = typer.Argument(help="Skill name (e.g. 'myorg/my-skill')"),
    grantee: str = typer.Argument(help="Org or user slug to revoke access from"),
) -> None:
    """Revoke an org or user's access to a private skill."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    parts = skill_ref.split("/", 1)
    if len(parts) != 2:
        console.print("[red]Error: Skill reference must be in org/skill format.[/]")
        raise typer.Exit(1)
    org_slug, skill_name = parts

    api_url = get_api_url()
    headers = build_headers(get_token())

    with httpx.Client(timeout=60) as client:
        resp = client.delete(
            f"{api_url}/v1/skills/{org_slug}/{skill_name}/access/{grantee}",
            headers=headers,
        )
        if resp.status_code == 404:
            detail = resp.json().get("detail", "Not found")
            console.print(f"[red]Error: {detail}[/]")
            raise typer.Exit(1)
        if resp.status_code == 403:
            console.print("[red]Error: Only org admins can manage access grants.[/]")
            raise typer.Exit(1)
        resp.raise_for_status()

    console.print(f"[green]Revoked access from '{grantee}' for {org_slug}/{skill_name}[/]")


@access_app.command("list")
def list_command(
    skill_ref: str = typer.Argument(help="Skill name (e.g. 'myorg/my-skill')"),
) -> None:
    """List all access grants for a private skill."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    parts = skill_ref.split("/", 1)
    if len(parts) != 2:
        console.print("[red]Error: Skill reference must be in org/skill format.[/]")
        raise typer.Exit(1)
    org_slug, skill_name = parts

    api_url = get_api_url()
    headers = build_headers(get_token())

    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{api_url}/v1/skills/{org_slug}/{skill_name}/access",
            headers=headers,
        )
        if resp.status_code == 404:
            detail = resp.json().get("detail", "Not found")
            console.print(f"[red]Error: {detail}[/]")
            raise typer.Exit(1)
        if resp.status_code == 403:
            console.print("[red]Error: Only org admins can view access grants.[/]")
            raise typer.Exit(1)
        resp.raise_for_status()
        grants = resp.json()

    if not grants:
        console.print(f"No access grants for {org_slug}/{skill_name}")
        return

    table = RichTable(title=f"Access Grants: {org_slug}/{skill_name}")
    table.add_column("Grantee", style="cyan")
    table.add_column("Granted By", style="green")
    table.add_column("Date")

    for g in grants:
        table.add_row(
            g["grantee_org_slug"],
            g.get("granted_by", ""),
            g.get("created_at", ""),
        )

    console.print(table)
