"""CLI command for scaffolding a new skill project."""

from pathlib import Path

import typer
import yaml
from rich.console import Console

console = Console()


def _prompt_nonempty(message: str, *, max_length: int) -> str:
    """Prompt repeatedly until the user enters a non-empty value of the right length.

    The bare ``typer.prompt`` accepts an empty Enter, which then propagates
    through to manifest validation as a confusing failure at publish time.
    Catching it here keeps the round-trip tight.
    """
    while True:
        value = typer.prompt(message).strip()
        if not value:
            console.print("[yellow]Value cannot be empty — please try again.[/]")
            continue
        if len(value) > max_length:
            console.print(f"[yellow]Value must be at most {max_length} characters.[/]")
            continue
        return value


def init_command(
    path: Path = typer.Argument(None, help="Directory to create the skill in (default: current dir)"),
) -> None:
    """Scaffold a new skill project with SKILL.md and src/ directory."""
    if path is None:
        path = Path(".")

    # Interactive prompts.
    name = _prompt_nonempty("Skill name (lowercase, hyphens ok)", max_length=64)
    description = _prompt_nonempty("Short description", max_length=1024)

    from dhub.core.validation import validate_skill_name

    try:
        validate_skill_name(name)
    except ValueError as exc:
        # validate_skill_name raises with a useful message; render it as
        # a friendly error instead of letting the traceback through.
        console.print(f"[red]Error: {exc}[/]")
        raise typer.Exit(1) from exc

    # Create directory structure
    skill_dir = path / name if path != Path(".") else Path(".")
    skill_dir.mkdir(parents=True, exist_ok=True)
    src_dir = skill_dir / "src"
    src_dir.mkdir(exist_ok=True)

    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        console.print(f"[red]Error: {skill_md} already exists.[/]")
        raise typer.Exit(1)

    # Hand the description to PyYAML so quote/colon characters get escaped
    # consistently. The previous f-string interpolation produced invalid
    # YAML for inputs containing a double quote, which then failed parsing
    # on publish with a non-obvious error.
    description_yaml = yaml.safe_dump(
        description,
        default_style='"',
        allow_unicode=True,
        width=2**20,  # don't wrap
    ).rstrip()

    skill_md.write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: {description_yaml}\n"
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
