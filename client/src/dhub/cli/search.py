"""CLI command for natural language skill search."""

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console()


def ask_command(
    query: str = typer.Argument(help="Natural language query to search for skills"),
    category: str | None = typer.Option(
        None,
        "--category",
        "-c",
        help="Filter search to a specific category (e.g. 'Backend & APIs')",
    ),
) -> None:
    """Search for skills using natural language.

    Example: dhub ask "analyze A/B test results"
    Example: dhub ask "build a REST API" --category "Backend & APIs"
    """
    from dhub.cli.config import get_optional_token, raise_for_status
    from dhub.cli.http import api_client

    params: dict[str, str] = {"q": query}
    if category:
        params["category"] = category

    with console.status("Searching registry..."), api_client(token=get_optional_token()) as client:
        resp = client.get("/v1/ask", params=params)
        if resp.status_code == 503:
            console.print("[red]Search is not available (server not configured).[/]")
            raise typer.Exit(1)
        raise_for_status(resp)
        data = resp.json()

    from dhub.cli.output import is_json, print_json

    if is_json():
        print_json(data)
        return

    title = f"Results for: {data['query']}"
    if category:
        title += f" (category: {category})"

    console.print(
        Panel(
            Markdown(data["answer"]),
            title=title,
            border_style="blue",
        )
    )

    skills = data.get("skills", [])
    if skills:
        table = Table(title="Referenced Skills", show_lines=True)
        table.add_column("Skill", style="cyan")
        table.add_column("Grade", style="green")
        table.add_column("Description")
        table.add_column("Reason", style="dim")

        for skill in skills:
            table.add_row(
                f"{skill['org_slug']}/{skill['skill_name']}",
                skill.get("safety_rating", "?"),
                skill.get("description", ""),
                skill.get("reason", ""),
            )

        console.print(table)
