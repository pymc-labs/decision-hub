"""CLI command for scaffolding a new skill project."""

from pathlib import Path

import typer
import yaml
from rich.console import Console

console = Console()


def init_command(
    path: Path = typer.Argument(None, help="Directory to create the skill in (default: current dir)"),
) -> None:
    """Scaffold a new skill project with SKILL.md and src/ directory."""
    if path is None:
        path = Path(".")

    # Interactive prompts
    name = typer.prompt("Skill name (lowercase, hyphens ok)")
    description = typer.prompt("Short description")

    from dhub.core.validation import validate_skill_name

    validate_skill_name(name)

    if len(description) > 1024:
        console.print("[red]Error: Description must be 1-1024 characters.[/]")
        raise typer.Exit(1)

    # Create directory structure
    skill_dir = path / name if path != Path(".") else Path(".")
    skill_dir.mkdir(parents=True, exist_ok=True)
    src_dir = skill_dir / "src"
    src_dir.mkdir(exist_ok=True)

    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        console.print(f"[red]Error: {skill_md} already exists.[/]")
        raise typer.Exit(1)

    # Emit the frontmatter through yaml.dump so descriptions containing
    # quotes, backslashes, or newlines don't produce a broken SKILL.md
    # that parse_skill_md would later reject. `default_flow_style=False`
    # keeps the block-style layout the rest of the tooling expects.
    frontmatter = yaml.dump(
        {"name": name, "description": description},
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    ).strip()
    skill_md.write_text(
        f"---\n{frontmatter}\n---\n\n# {name}\n\nDescribe what this skill does and how the agent should use it.\n"
    )

    console.print(f"[green]Created skill project at {skill_dir.resolve()}[/]")
    console.print("  SKILL.md")
    console.print("  src/")
    console.print("\nEdit [cyan]SKILL.md[/] to define your skill's behavior.")
