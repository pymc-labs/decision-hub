"""Access grant management commands for private skills."""

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()
access_app = typer.Typer(help="Manage access grants for private skills", no_args_is_help=True)


@access_app.command("grant")
def grant_command(
    skill_ref: str = typer.Argument(help="Skill reference (org/skill)"),
    grantee: str = typer.Argument(help="Organisation slug to grant access to"),
) -> None:
    """Grant an organisation access to a private skill."""
    from dhub.cli.config import build_headers, get_api_url, get_token, raise_for_status
    from dhub.core.validation import parse_skill_ref

    try:
        org_slug, skill_name = parse_skill_ref(skill_ref)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/]")
        raise typer.Exit(1) from None

    api_url = get_api_url()
    headers = build_headers(get_token())

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{api_url}/v1/skills/{org_slug}/{skill_name}/access",
            headers=headers,
            json={"grantee_org_slug": grantee},
        )
        if resp.status_code == 404:
            console.print(f"[red]Error: {resp.json().get('detail', 'Not found')}[/]")
            raise typer.Exit(1)
        if resp.status_code == 403:
            console.print("[red]Error: Only org owners and admins can manage access grants.[/]")
            raise typer.Exit(1)
        if resp.status_code == 409:
            console.print(f"[yellow]Access already granted to '{grantee}'.[/]")
            raise typer.Exit(1)
        raise_for_status(resp)

    console.print(f"[green]Granted access to '{grantee}' for {org_slug}/{skill_name}.[/]")


@access_app.command("revoke")
def revoke_command(
    skill_ref: str = typer.Argument(help="Skill reference (org/skill)"),
    grantee: str = typer.Argument(help="Organisation slug to revoke access from"),
) -> None:
    """Revoke an organisation's access to a private skill."""
    from dhub.cli.config import build_headers, get_api_url, get_token, raise_for_status
    from dhub.core.validation import parse_skill_ref

    try:
        org_slug, skill_name = parse_skill_ref(skill_ref)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/]")
        raise typer.Exit(1) from None

    api_url = get_api_url()
    headers = build_headers(get_token())

    with httpx.Client(timeout=60) as client:
        resp = client.delete(
            f"{api_url}/v1/skills/{org_slug}/{skill_name}/access/{grantee}",
            headers=headers,
        )
        if resp.status_code == 404:
            console.print(f"[red]Error: {resp.json().get('detail', 'Not found')}[/]")
            raise typer.Exit(1)
        if resp.status_code == 403:
            console.print("[red]Error: Only org owners and admins can manage access grants.[/]")
            raise typer.Exit(1)
        raise_for_status(resp)

    console.print(f"[green]Revoked access from '{grantee}' for {org_slug}/{skill_name}.[/]")


@access_app.command("list")
def list_command(
    skill_ref: str = typer.Argument(help="Skill reference (org/skill)"),
) -> None:
    """List access grants for a private skill."""
    from dhub.cli.config import build_headers, get_api_url, get_token, raise_for_status
    from dhub.core.validation import parse_skill_ref

    try:
        org_slug, skill_name = parse_skill_ref(skill_ref)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/]")
        raise typer.Exit(1) from None

    api_url = get_api_url()
    headers = build_headers(get_token())

    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{api_url}/v1/skills/{org_slug}/{skill_name}/access",
            headers=headers,
        )
        if resp.status_code == 404:
            console.print(f"[red]Error: {resp.json().get('detail', 'Not found')}[/]")
            raise typer.Exit(1)
        if resp.status_code == 403:
            console.print("[red]Error: Only org owners and admins can view access grants.[/]")
            raise typer.Exit(1)
        raise_for_status(resp)
        grants = resp.json()

    if not grants:
        console.print(f"No access grants for {org_slug}/{skill_name}.")
        return

    table = Table(title=f"Access Grants for {org_slug}/{skill_name}")
    table.add_column("Grantee", style="cyan")
    table.add_column("Granted By", style="dim")
    table.add_column("Date", style="dim")

    for grant in grants:
        table.add_row(
            grant["grantee_org_slug"],
            grant["granted_by"],
            grant.get("created_at", "")[:19] if grant.get("created_at") else "-",
        )

    console.print(table)
