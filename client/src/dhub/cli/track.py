"""Tracker management commands for auto-republishing skills from GitHub."""

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()
track_app = typer.Typer(help="Manage GitHub repo trackers for auto-republishing", no_args_is_help=True)


def _resolve_tracker_id(api_url: str, headers: dict, tracker_id: str) -> str | None:
    """Resolve a tracker ID prefix to a full UUID.

    If the input is already a full UUID (36 chars), returns it directly.
    Otherwise, fetches the tracker list and matches by prefix.
    """
    if len(tracker_id) == 36:
        return tracker_id

    with httpx.Client(timeout=60) as client:
        resp = client.get(f"{api_url}/v1/trackers", headers=headers)
        resp.raise_for_status()
        trackers = resp.json()

    matches = [t["id"] for t in trackers if t["id"].startswith(tracker_id)]
    if len(matches) == 1:
        return matches[0]
    return None


@track_app.command("add")
def add_tracker(
    repo_url: str = typer.Argument(help="GitHub repository URL"),
    branch: str = typer.Option("main", "--branch", "-b", help="Branch to track"),
    interval: int = typer.Option(60, "--interval", "-i", help="Poll interval in minutes (min 5)"),
) -> None:
    """Add a tracker for a GitHub repository."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{get_api_url()}/v1/trackers",
            headers=build_headers(get_token()),
            json={
                "repo_url": repo_url,
                "branch": branch,
                "poll_interval_minutes": interval,
            },
        )
        if resp.status_code == 409:
            console.print("[red]Error: A tracker for this repo and branch already exists.[/]")
            raise typer.Exit(1)
        if resp.status_code == 422:
            detail = resp.json().get("detail", "Validation error")
            console.print(f"[red]Error: {detail}[/]")
            raise typer.Exit(1)
        resp.raise_for_status()

    data = resp.json()
    console.print(f"[green]Created tracker:[/] {data['id'][:8]}")
    console.print(f"  Repo:     {data['repo_url']}")
    console.print(f"  Branch:   {data['branch']}")
    console.print(f"  Org:      {data['org_slug']}")
    console.print(f"  Interval: {data['poll_interval_minutes']}m")

    if data.get("warning"):
        console.print()
        console.print(f"[yellow]Warning: {data['warning']}[/]")


@track_app.command("list")
def list_trackers() -> None:
    """List all your trackers."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{get_api_url()}/v1/trackers",
            headers=build_headers(get_token()),
        )
        resp.raise_for_status()
        trackers = resp.json()

    if not trackers:
        console.print("No trackers configured.")
        return

    table = Table(title="Trackers")
    table.add_column("ID", style="cyan", max_width=8)
    table.add_column("Repo")
    table.add_column("Branch")
    table.add_column("Org")
    table.add_column("Interval")
    table.add_column("Enabled")
    table.add_column("Last Checked", style="dim")
    table.add_column("Last Published", style="dim")
    table.add_column("Error", style="red", max_width=30)

    for t in trackers:
        table.add_row(
            t["id"][:8],
            t["repo_url"],
            t["branch"],
            t["org_slug"],
            f"{t['poll_interval_minutes']}m",
            "yes" if t["enabled"] else "no",
            t.get("last_checked_at") or "-",
            t.get("last_published_at") or "-",
            (t.get("last_error") or "")[:30] or "-",
        )

    console.print(table)


@track_app.command("status")
def tracker_status(
    tracker_id: str = typer.Argument(help="Tracker ID or prefix"),
) -> None:
    """Show detailed status of a tracker."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    api_url = get_api_url()
    headers = build_headers(get_token())

    resolved_id = _resolve_tracker_id(api_url, headers, tracker_id)
    if resolved_id is None:
        console.print(f"[red]Error: Could not resolve tracker ID '{tracker_id}'.[/]")
        raise typer.Exit(1)

    with httpx.Client(timeout=60) as client:
        resp = client.get(f"{api_url}/v1/trackers/{resolved_id}", headers=headers)
        if resp.status_code == 404:
            console.print("[red]Error: Tracker not found.[/]")
            raise typer.Exit(1)
        resp.raise_for_status()

    t = resp.json()
    console.print(f"[bold]Tracker {t['id'][:8]}[/]")
    console.print(f"  Repo:           {t['repo_url']}")
    console.print(f"  Branch:         {t['branch']}")
    console.print(f"  Org:            {t['org_slug']}")
    console.print(f"  Interval:       {t['poll_interval_minutes']}m")
    console.print(f"  Enabled:        {'yes' if t['enabled'] else 'no'}")
    console.print(f"  Last Commit:    {t.get('last_commit_sha') or '-'}")
    console.print(f"  Last Checked:   {t.get('last_checked_at') or '-'}")
    console.print(f"  Last Published: {t.get('last_published_at') or '-'}")
    console.print(f"  Created:        {t.get('created_at') or '-'}")
    if t.get("last_error"):
        console.print(f"  [red]Error: {t['last_error']}[/]")
        error_lower = t["last_error"].lower()
        if any(kw in error_lower for kw in ("404", "403", "not found", "authentication", "credentials")):
            console.print()
            console.print("  [yellow]Hint: For private repos, add a GitHub token: dhub keys add GITHUB_TOKEN[/]")


@track_app.command("pause")
def pause_tracker(
    tracker_id: str = typer.Argument(help="Tracker ID or prefix"),
) -> None:
    """Pause a tracker (stop polling)."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    api_url = get_api_url()
    headers = build_headers(get_token())

    resolved_id = _resolve_tracker_id(api_url, headers, tracker_id)
    if resolved_id is None:
        console.print(f"[red]Error: Could not resolve tracker ID '{tracker_id}'.[/]")
        raise typer.Exit(1)

    with httpx.Client(timeout=60) as client:
        resp = client.patch(
            f"{api_url}/v1/trackers/{resolved_id}",
            headers=headers,
            json={"enabled": False},
        )
        if resp.status_code == 404:
            console.print("[red]Error: Tracker not found.[/]")
            raise typer.Exit(1)
        resp.raise_for_status()

    console.print(f"[yellow]Paused tracker {resolved_id[:8]}[/]")


@track_app.command("resume")
def resume_tracker(
    tracker_id: str = typer.Argument(help="Tracker ID or prefix"),
) -> None:
    """Resume a paused tracker."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    api_url = get_api_url()
    headers = build_headers(get_token())

    resolved_id = _resolve_tracker_id(api_url, headers, tracker_id)
    if resolved_id is None:
        console.print(f"[red]Error: Could not resolve tracker ID '{tracker_id}'.[/]")
        raise typer.Exit(1)

    with httpx.Client(timeout=60) as client:
        resp = client.patch(
            f"{api_url}/v1/trackers/{resolved_id}",
            headers=headers,
            json={"enabled": True},
        )
        if resp.status_code == 404:
            console.print("[red]Error: Tracker not found.[/]")
            raise typer.Exit(1)
        resp.raise_for_status()

    console.print(f"[green]Resumed tracker {resolved_id[:8]}[/]")


@track_app.command("remove")
def remove_tracker(
    tracker_id: str = typer.Argument(help="Tracker ID or prefix"),
) -> None:
    """Remove a tracker."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    api_url = get_api_url()
    headers = build_headers(get_token())

    resolved_id = _resolve_tracker_id(api_url, headers, tracker_id)
    if resolved_id is None:
        console.print(f"[red]Error: Could not resolve tracker ID '{tracker_id}'.[/]")
        raise typer.Exit(1)

    with httpx.Client(timeout=60) as client:
        resp = client.delete(
            f"{api_url}/v1/trackers/{resolved_id}",
            headers=headers,
        )
        if resp.status_code == 404:
            console.print("[red]Error: Tracker not found.[/]")
            raise typer.Exit(1)
        resp.raise_for_status()

    console.print(f"[green]Removed tracker {resolved_id[:8]}[/]")
