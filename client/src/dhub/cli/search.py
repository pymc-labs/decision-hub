"""CLI command for natural language skill search."""

import httpx
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

console = Console()


def ask_command(
    query: str = typer.Argument(help="Natural language query to search for skills"),
) -> None:
    """Search for skills using natural language.

    Example: dhub ask "analyze A/B test results"
    """
    from dhub.cli.config import get_api_url, get_token

    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{get_api_url()}/v1/search",
            params={"q": query},
            headers={"Authorization": f"Bearer {get_token()}"},
        )
        if resp.status_code == 503:
            console.print("[red]Search is not available (server not configured).[/]")
            raise typer.Exit(1)
        resp.raise_for_status()
        data = resp.json()

    console.print(Panel(
        Markdown(data["results"]),
        title=f"Results for: {data['query']}",
        border_style="blue",
    ))
