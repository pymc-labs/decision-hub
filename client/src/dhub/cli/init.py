"""CLI command for scaffolding a new skill project."""

from pathlib import Path

import typer
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

    skill_md.write_text(
        f"---\n"
        f"name: {name}\n"
        f'description: "{description}"\n'
        f"---\n"
        f"\n"
        f"# {name}\n"
        f"\n"
        f"Describe what this skill does and how the agent should use it.\n"
    )

    console.print(f"[green]Created skill project at {skill_dir.resolve()}[/]")
    console.print("  SKILL.md")
    console.print("  src/")
    console.print("\nEdit [cyan]SKILL.md[/] to define your skill's behavior.")
