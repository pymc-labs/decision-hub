"""CLI command for running skills locally."""

import subprocess

import typer
from rich.console import Console

console = Console()


def run_command(
    skill_ref: str = typer.Argument(help="Skill reference: org/skill"),
    extra_args: list[str] = typer.Argument(None, help="Extra arguments to pass to the skill"),
) -> None:
    """Run a locally installed skill using its configured runtime."""
    from dhub.core.install import get_dhub_skill_path
    from dhub.core.manifest import parse_skill_md
    from dhub.core.runtime import (
        build_env_vars,
        build_uv_run_command,
        build_uv_sync_command,
        validate_local_runtime_prerequisites,
    )
    from dhub.core.validation import parse_skill_ref

    # Parse org/skill reference
    try:
        org_slug, skill_name = parse_skill_ref(skill_ref)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/]")
        raise typer.Exit(1) from None

    # Resolve the local skill directory
    skill_dir = get_dhub_skill_path(org_slug, skill_name)
    if not skill_dir.exists():
        console.print(f"[red]Error: Skill '{skill_ref}' is not installed. Expected at {skill_dir}[/]")
        raise typer.Exit(1)

    # Parse SKILL.md to get runtime config
    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        console.print(f"[red]Error: SKILL.md not found in {skill_dir}[/]")
        raise typer.Exit(1)

    manifest = parse_skill_md(skill_md_path)

    if manifest.runtime is None:
        console.print("[red]Error: This skill has no runtime configuration.[/]")
        raise typer.Exit(1)

    if manifest.runtime.language != "python":
        console.print(
            f"[red]Error: Unsupported runtime language '{manifest.runtime.language}'. Only 'python' is supported.[/]"
        )
        raise typer.Exit(1)

    # Validate prerequisites
    errors = validate_local_runtime_prerequisites(skill_dir, manifest.runtime)
    if errors:
        console.print("[red]Runtime prerequisites not met:[/]")
        for error in errors:
            console.print(f"  [red]- {error}[/]")
        raise typer.Exit(1)

    # Build environment variables
    env = build_env_vars(manifest.runtime)

    # Sync dependencies — catch the subprocess error so the user sees a
    # friendly message instead of a Python traceback (which would expose the
    # full env dict if typer's pretty_exceptions are ever enabled).
    sync_cmd = build_uv_sync_command(skill_dir)
    console.print(f"[dim]Syncing dependencies in {skill_dir}...[/]")
    try:
        subprocess.run(sync_cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        console.print(
            f"[red]Error: Dependency sync failed (exit {exc.returncode}). "
            "Check that 'uv' is installed and the skill's lockfile is valid.[/]"
        )
        raise typer.Exit(1) from None
    except FileNotFoundError:
        console.print("[red]Error: 'uv' was not found on PATH. Install it from https://docs.astral.sh/uv/[/]")
        raise typer.Exit(1) from None

    # Run the entrypoint
    args_tuple = tuple(extra_args) if extra_args else ()
    run_cmd = build_uv_run_command(skill_dir, manifest.runtime.entrypoint, args_tuple)
    console.print(f"[dim]Running {manifest.name}...[/]")
    try:
        result = subprocess.run(run_cmd, env=env)
    except FileNotFoundError:
        console.print("[red]Error: 'uv' was not found on PATH. Install it from https://docs.astral.sh/uv/[/]")
        raise typer.Exit(1) from None
    raise typer.Exit(result.returncode)
