"""CLI command for natural language skill search."""

import httpx
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

console = Console()


def ask_command(
    query: str = typer.Argument(help="Natural language query to search for skills"),
    category: str | None = typer.Option(
        None, "--category", "-c",
        help="Filter search to a specific category (e.g. 'Backend & APIs')",
    ),
) -> None:
    """Search for skills using natural language.

    Example: dhub ask "analyze A/B test results"
    Example: dhub ask "build a REST API" --category "Backend & APIs"
    """
    from dhub.cli.config import build_headers, get_api_url, get_token

    params: dict[str, str] = {"q": query}
    if category:
        params["category"] = category

    with console.status("Searching registry..."), httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{get_api_url()}/v1/search",
            params=params,
            headers=build_headers(get_token()),
        )
        if resp.status_code == 503:
            console.print("[red]Search is not available (server not configured).[/]")
            raise typer.Exit(1)
        resp.raise_for_status()
        data = resp.json()

    title = f"Results for: {data['query']}"
    if data.get("category"):
        title += f" [dim](category: {data['category']})[/]"

    console.print(Panel(
        Markdown(data["results"]),
        title=title,
        border_style="blue",
    ))
