"""Organization management commands."""

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()
org_app = typer.Typer(help="Manage organizations", no_args_is_help=True)


def _headers() -> dict[str, str]:
    """Build authorization headers using the stored token."""
    from decision_hub.cli.config import get_token

    return {"Authorization": f"Bearer {get_token()}"}


def _api_url() -> str:
    """Retrieve the configured API URL."""
    from decision_hub.cli.config import get_api_url

    return get_api_url()


@org_app.command("create")
def create_org(slug: str = typer.Argument(help="Organization slug")) -> None:
    """Create a new organization."""
    with httpx.Client() as client:
        resp = client.post(
            f"{_api_url()}/v1/orgs",
            headers=_headers(),
            json={"slug": slug},
        )
        if resp.status_code == 409:
            console.print(
                f"[red]Error: Organization '{slug}' already exists.[/]"
            )
            raise typer.Exit(1)
        resp.raise_for_status()
        data = resp.json()

    console.print(f"[green]Created organization: {data['slug']}[/]")


@org_app.command("list")
def list_orgs() -> None:
    """List organizations you belong to."""
    with httpx.Client() as client:
        resp = client.get(
            f"{_api_url()}/v1/orgs",
            headers=_headers(),
        )
        resp.raise_for_status()
        orgs = resp.json()

    if not orgs:
        console.print("You are not a member of any organizations.")
        return

    table = Table(title="Organizations")
    table.add_column("Slug", style="cyan")
    table.add_column("Role", style="green")

    for org in orgs:
        table.add_row(org.get("slug", ""), org.get("role", ""))

    console.print(table)


@org_app.command("invite")
def invite_member(
    org: str = typer.Argument(help="Organization slug"),
    user: str = typer.Option(..., "--user", help="GitHub username to invite"),
    role: str = typer.Option(
        "member", "--role", help="Role: owner, admin, or member"
    ),
) -> None:
    """Invite a user to an organization."""
    with httpx.Client() as client:
        resp = client.post(
            f"{_api_url()}/v1/orgs/{org}/invites",
            headers=_headers(),
            json={"invitee_github_username": user, "role": role},
        )
        if resp.status_code == 404:
            console.print(
                f"[red]Error: Organization '{org}' not found.[/]"
            )
            raise typer.Exit(1)
        if resp.status_code == 403:
            console.print(
                "[red]Error: You do not have permission to invite members.[/]"
            )
            raise typer.Exit(1)
        resp.raise_for_status()
        data = resp.json()

    console.print(
        f"[green]Invited @{user} to '{org}' as {role}. "
        f"Invite ID: {data['id']}[/]"
    )


@org_app.command("accept")
def accept_invite(
    invite_id: str = typer.Argument(help="Invite ID to accept"),
) -> None:
    """Accept an organization invite."""
    with httpx.Client() as client:
        resp = client.post(
            f"{_api_url()}/v1/invites/{invite_id}/accept",
            headers=_headers(),
        )
        if resp.status_code == 404:
            console.print(
                f"[red]Error: Invite '{invite_id}' not found.[/]"
            )
            raise typer.Exit(1)
        resp.raise_for_status()
        data = resp.json()

    console.print(
        f"[green]Accepted invite. You are now a member of '{data['org_slug']}'.[/]"
    )
