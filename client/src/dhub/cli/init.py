"""CLI command for scaffolding a new skill project."""

from pathlib import Path
from sys import maxsize

import typer
import yaml
from rich.console import Console

from dhub.core.validation import validate_skill_name

console = Console()


def _validate_description(description: str) -> None:
    if not description.strip():
        console.print("[red]Error: Description must not be blank.[/]")
        raise typer.Exit(1)
    if len(description) > 1024:
        console.print("[red]Error: Description must be 1-1024 characters.[/]")
        raise typer.Exit(1)


def _new_manifest_path(skill_dir: Path) -> Path:
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists() or skill_md.is_symlink():
        console.print(f"Error: {skill_md} already exists.", style="red", markup=False)
        raise typer.Exit(1)
    return skill_md


def init_command(
    path: Path = typer.Argument(Path("."), help="Directory to create the skill in (default: current dir)"),
    name: str | None = typer.Option(None, "--name", help="Skill name (prompted if omitted)."),
    description: str | None = typer.Option(None, "--description", help="Short description (prompted if omitted)."),
) -> None:
    """Scaffold a new skill project with SKILL.md and src/ directory."""
    if description is not None:
        _validate_description(description)

    skill_md = _new_manifest_path(path) if path == Path(".") else None
    skill_name = name if name is not None else typer.prompt("Skill name (lowercase, hyphens ok)")
    try:
        validate_skill_name(skill_name)
        if "\n" in skill_name:
            raise ValueError("Invalid skill name: line breaks are not allowed.")
    except ValueError as exc:
        console.print(f"Error: {exc}", style="red", markup=False)
        raise typer.Exit(1) from None

    if skill_md is None:
        skill_md = _new_manifest_path(path / skill_name)

    if description is None:
        description = typer.prompt("Short description")
        _validate_description(description)

    # Quote YAML-typed names such as "on". Keep the description on one physical
    # line so a literal "---" inside it cannot terminate the frontmatter.
    name_yaml = yaml.safe_dump({"name": skill_name})
    description_yaml = yaml.safe_dump(description, default_style='"', width=maxsize)
    content = (
        f"---\n"
        f"{name_yaml}"
        f"description: {description_yaml}"
        f"---\n"
        f"\n"
        f"# {skill_name}\n"
        f"\n"
        f"Describe what this skill does and how the agent should use it.\n"
    )

    skill_dir = skill_md.parent
    try:
        skill_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = skill_md.open("x", encoding="utf-8")
        try:
            with manifest_file:
                manifest_file.write(content)
            (skill_dir / "src").mkdir(exist_ok=True)
        except OSError:
            skill_md.unlink()
            raise
    except OSError as exc:
        console.print(f"Error: {exc}", style="red", markup=False)
        raise typer.Exit(1) from None

    console.print(f"Created skill project at {skill_dir.resolve()}", style="green", markup=False)
    console.print("  SKILL.md")
    console.print("  src/")
    console.print("\nEdit [cyan]SKILL.md[/] to define your skill's behavior.")
