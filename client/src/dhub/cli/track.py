"""Skill update tracker commands — track GitHub repos for auto-republish."""

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()
track_app = typer.Typer(help="Track GitHub repos for automatic skill updates", no_args_is_help=True)


@track_app.command("add")
def add_tracker(
    repo_url: str = typer.Argument(help="GitHub repository URL to track"),
    branch: str = typer.Option("main", "--branch", "-b", help="Branch to track"),
    interval: int = typer.Option(60, "--interval", "-i", help="Poll interval in minutes (min 5)"),
) -> None:
    """Set up a tracker for a GitHub repo to auto-republish skills on changes."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    api_url = get_api_url()
    headers = build_headers(get_token())

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{api_url}/v1/trackers",
            json={
                "repo_url": repo_url,
                "branch": branch,
                "poll_interval_minutes": interval,
            },
            headers=headers,
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
    console.print(f"[green]Tracker created:[/] {data['repo_url']} ({data['branch']})")
    console.print(f"  ID: [dim]{data['id']}[/]")
    console.print(f"  Org: [cyan]{data['org_slug']}[/]")
    console.print(f"  Poll every: {data['poll_interval_minutes']} minutes")


@track_app.command("list")
def list_trackers() -> None:
    """List all active skill trackers."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    api_url = get_api_url()
    headers = build_headers(get_token())

    with httpx.Client(timeout=60) as client:
        resp = client.get(f"{api_url}/v1/trackers", headers=headers)
        resp.raise_for_status()
        trackers = resp.json()

    if not trackers:
        console.print("No trackers configured. Use 'dhub track add <repo-url>' to create one.")
        return

    table = Table(title="Skill Trackers")
    table.add_column("ID", style="dim", max_width=10)
    table.add_column("Repo")
    table.add_column("Branch", style="cyan")
    table.add_column("Org", style="cyan")
    table.add_column("Interval")
    table.add_column("Enabled")
    table.add_column("Last Checked")
    table.add_column("Last Published")
    table.add_column("Error", max_width=30)

    for t in trackers:
        enabled_style = "green" if t["enabled"] else "red"
        error_text = t.get("last_error") or ""
        if len(error_text) > 30:
            error_text = error_text[:27] + "..."

        table.add_row(
            t["id"][:8] + "...",
            t["repo_url"],
            t["branch"],
            t["org_slug"],
            f"{t['poll_interval_minutes']}m",
            f"[{enabled_style}]{t['enabled']}[/]",
            (t.get("last_checked_at") or "-")[:19],
            (t.get("last_published_at") or "-")[:19],
            f"[red]{error_text}[/]" if error_text else "-",
        )

    console.print(table)


@track_app.command("status")
def tracker_status(
    tracker_id: str = typer.Argument(help="Tracker ID (or prefix)"),
) -> None:
    """Show detailed status of a tracker."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    api_url = get_api_url()
    headers = build_headers(get_token())

    # Resolve prefix to full ID
    full_id = _resolve_tracker_id(api_url, headers, tracker_id)
    if full_id is None:
        console.print(f"[red]Error: Tracker '{tracker_id}' not found.[/]")
        raise typer.Exit(1)

    with httpx.Client(timeout=60) as client:
        resp = client.get(f"{api_url}/v1/trackers/{full_id}", headers=headers)
        resp.raise_for_status()
        t = resp.json()

    enabled_style = "green" if t["enabled"] else "red"
    console.print(f"Tracker:        [dim]{t['id']}[/]")
    console.print(f"Repo:           {t['repo_url']}")
    console.print(f"Branch:         [cyan]{t['branch']}[/]")
    console.print(f"Org:            [cyan]{t['org_slug']}[/]")
    console.print(f"Enabled:        [{enabled_style}]{t['enabled']}[/]")
    console.print(f"Poll interval:  {t['poll_interval_minutes']} minutes")
    console.print(f"Last commit:    {t.get('last_commit_sha') or 'never checked'}")
    console.print(f"Last checked:   {t.get('last_checked_at') or 'never'}")
    console.print(f"Last published: {t.get('last_published_at') or 'never'}")
    if t.get("last_error"):
        console.print(f"Last error:     [red]{t['last_error']}[/]")


@track_app.command("remove")
def remove_tracker(
    tracker_id: str = typer.Argument(help="Tracker ID (or prefix)"),
) -> None:
    """Remove a skill tracker."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    api_url = get_api_url()
    headers = build_headers(get_token())

    full_id = _resolve_tracker_id(api_url, headers, tracker_id)
    if full_id is None:
        console.print(f"[red]Error: Tracker '{tracker_id}' not found.[/]")
        raise typer.Exit(1)

    with httpx.Client(timeout=60) as client:
        resp = client.delete(f"{api_url}/v1/trackers/{full_id}", headers=headers)
        if resp.status_code == 404:
            console.print("[red]Error: Tracker not found.[/]")
            raise typer.Exit(1)
        resp.raise_for_status()

    console.print(f"[green]Tracker removed: {full_id[:8]}...[/]")


@track_app.command("pause")
def pause_tracker(
    tracker_id: str = typer.Argument(help="Tracker ID (or prefix)"),
) -> None:
    """Pause a tracker (stop checking for updates)."""
    _toggle_tracker(tracker_id, enabled=False)
    console.print("[yellow]Tracker paused.[/]")


@track_app.command("resume")
def resume_tracker(
    tracker_id: str = typer.Argument(help="Tracker ID (or prefix)"),
) -> None:
    """Resume a paused tracker."""
    _toggle_tracker(tracker_id, enabled=True)
    console.print("[green]Tracker resumed.[/]")


def _toggle_tracker(tracker_id: str, *, enabled: bool) -> None:
    """Enable or disable a tracker."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    api_url = get_api_url()
    headers = build_headers(get_token())

    full_id = _resolve_tracker_id(api_url, headers, tracker_id)
    if full_id is None:
        console.print(f"[red]Error: Tracker '{tracker_id}' not found.[/]")
        raise typer.Exit(1)

    with httpx.Client(timeout=60) as client:
        resp = client.patch(
            f"{api_url}/v1/trackers/{full_id}",
            json={"enabled": enabled},
            headers=headers,
        )
        resp.raise_for_status()


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
