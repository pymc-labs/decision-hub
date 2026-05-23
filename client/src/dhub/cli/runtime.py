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

    # Sync dependencies. ``check=True`` on the raw subprocess would dump
    # a traceback to the user; instead we catch and exit with a friendly
    # message. The 10-min cap prevents a stuck ``uv sync`` (e.g. a
    # hanging package server) from blocking the CLI indefinitely.
    sync_cmd = build_uv_sync_command(skill_dir)
    console.print(f"[dim]Syncing dependencies in {skill_dir}...[/]")
    try:
        subprocess.run(sync_cmd, check=True, env=env, timeout=600)
    except subprocess.TimeoutExpired:
        console.print("[red]Error: 'uv sync' timed out after 10 minutes.[/]")
        raise typer.Exit(1) from None
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Error: 'uv sync' failed with exit code {exc.returncode}.[/]")
        raise typer.Exit(exc.returncode or 1) from None

    # Run the entrypoint. No timeout here: skills are arbitrary user code
    # and may legitimately run for a long time.
    args_tuple = tuple(extra_args) if extra_args else ()
    run_cmd = build_uv_run_command(skill_dir, manifest.runtime.entrypoint, args_tuple)
    console.print(f"[dim]Running {manifest.name}...[/]")
    result = subprocess.run(run_cmd, env=env)
    raise typer.Exit(result.returncode)
