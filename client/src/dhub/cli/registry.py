"""Publish, install, list, and delete commands for the skill registry."""

import io
import json
import zipfile
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()

# Shared grade-to-color mapping used by publish, list, and eval-report display.
GRADE_COLORS: dict[str, str] = {
    "A": "green",
    "B": "yellow",
    "C": "dark_orange",
    "F": "red",
}


def _parse_skill_ref(skill_ref: str) -> tuple[str, str]:
    """Parse an 'org/skill' reference into (org_slug, skill_name).

    Raises typer.Exit(1) with an error message if the format is invalid.
    """
    parts = skill_ref.split("/", 1)
    if len(parts) != 2:
        console.print(
            "[red]Error: Skill reference must be in org/skill format.[/]"
        )
        raise typer.Exit(1)
    return parts[0], parts[1]


def publish_command(
    skill_ref: str = typer.Argument(
        None, help="Skill name (e.g. 'myorg/my-skill')"
    ),
    path: Path = typer.Argument(
        None, help="Path to the skill directory (default: current dir)"
    ),
    version: str = typer.Option(None, "--version", help="Explicit semver version (overrides auto-bump)"),
    patch: bool = typer.Option(False, "--patch", help="Bump patch version"),
    minor: bool = typer.Option(False, "--minor", help="Bump minor version"),
    major: bool = typer.Option(False, "--major", help="Bump major version"),
) -> None:
    """Publish a skill to the registry.

    When ORG/SKILL is omitted, the skill name is read from SKILL.md and the
    org is auto-detected (requires membership in exactly one org).

    Version is auto-bumped by default (patch). Use --major or --minor to
    control the bump level, or --version to set an explicit version.
    """
    from dhub.cli.config import build_headers, get_api_url, get_token
    from dhub.core.manifest import parse_skill_md
    from dhub.core.validation import validate_semver, validate_skill_name

    # Disambiguate positional args: if skill_ref looks like a filesystem path
    # (starts with '.', '/', '~', or is an existing directory) rather than
    # an org/skill pattern, treat it as the path argument instead.
    if skill_ref is not None and path is None:
        candidate = Path(skill_ref)
        if skill_ref.startswith((".", "/", "~")) or candidate.is_dir():
            path = candidate
            skill_ref = None

    # Default path to current directory
    if path is None:
        path = Path(".")

    # Verify the directory contains a SKILL.md manifest (needed for both auto-detect and validation)
    skill_md_path = path / "SKILL.md"
    if not skill_md_path.exists():
        console.print(
            "[red]Error: SKILL.md not found in the specified directory.[/]"
        )
        raise typer.Exit(1)

    api_url = get_api_url()
    token = get_token()

    manifest = parse_skill_md(skill_md_path)

    # Resolve org and name from skill_ref or auto-detect
    if skill_ref is not None:
        org, name = _parse_skill_ref(skill_ref)
        # Warn if the CLI-provided name doesn't match SKILL.md
        if name != manifest.name:
            console.print(
                f"[yellow]Warning: CLI name '{name}' differs from SKILL.md "
                f"name '{manifest.name}'. Using '{name}'.[/]"
            )
    else:
        # Auto-detect name from SKILL.md
        name = manifest.name
        # Auto-detect org: user must belong to exactly one org
        org = _auto_detect_org(api_url, token)

    validate_skill_name(name)

    with console.status("Packaging skill..."):
        zip_data = _create_zip(path)

    # Resolve version: explicit --version wins, otherwise auto-bump
    if version is not None:
        validate_semver(version)
    else:
        from dhub.core.install import compute_checksum

        local_checksum = compute_checksum(zip_data)
        bump_level = _resolve_bump_level(patch, minor, major)
        version, latest_checksum, current_version = _auto_bump_version(
            api_url, token, org, name, bump_level,
        )
        if latest_checksum is not None and local_checksum == latest_checksum:
            console.print(f"No changes detected. Already at [cyan]{current_version}[/].")
            return

    metadata = json.dumps(
        {"org_slug": org, "skill_name": name, "version": version}
    )

    with console.status(f"Publishing {org}/{name}@{version}..."):
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{api_url}/v1/publish",
                headers=build_headers(token),
                files={"zip_file": ("skill.zip", zip_data, "application/zip")},
                data={"metadata": metadata},
            )
        if resp.status_code == 409:
            console.print(
                f"[red]Error: Version {version} already exists for "
                f"{org}/{name}.[/]"
            )
            raise typer.Exit(1)
        if resp.status_code == 422:
            detail = resp.json().get("detail", "Gauntlet checks failed")
            console.print(f"[red]Rejected (Grade F): {detail}[/]")
            raise typer.Exit(1)
        if resp.status_code == 503:
            console.print(
                "[red]Error: Server LLM judge not configured. "
                "Cannot publish without LLM review.[/]"
            )
            raise typer.Exit(1)
        resp.raise_for_status()

    data = resp.json()
    eval_status = data.get("eval_status", "")
    eval_report_status = data.get("eval_report_status")

    grade_color = GRADE_COLORS.get(eval_status, "white")
    console.print(
        f"[green]Published: {org}/{name}@{version}[/] "
        f"(Grade [{grade_color}]{eval_status}[/])"
    )
    if eval_status == "B":
        console.print("[yellow]Warning: Grade B — elevated permissions detected.[/]")
    elif eval_status == "C":
        console.print(
            "[red]Warning: Grade C — ambiguous patterns detected. "
            "Users will need --allow-risky to install.[/]"
        )

    if eval_report_status == "pending":
        console.print("[dim]Agent evaluation running in background...[/]")


def _auto_detect_org(api_url: str, token: str) -> str:
    """Auto-detect the org for publishing.

    Checks in order:
    1. DHUB_DEFAULT_ORG env var or config default_org
    2. Cached orgs from config (if exactly one)
    3. Falls back to API call (for old configs without cached orgs)
    """
    from dhub.cli.config import build_headers, get_default_org, load_config

    # 1. Check default org (env var takes priority over config)
    default = get_default_org()
    if default:
        console.print(f"Using default namespace: [cyan]{default}[/]")
        return default

    # 2. Check cached orgs from config
    config = load_config()
    if config.orgs:
        if len(config.orgs) == 1:
            console.print(f"Auto-detected namespace: [cyan]{config.orgs[0]}[/]")
            return config.orgs[0]
        slugs = ", ".join(config.orgs)
        console.print(
            f"[red]Error: You have multiple namespaces ({slugs}). "
            f"Run 'dhub config default-org' to set a default, "
            f"or set DHUB_DEFAULT_ORG, "
            f"or specify: dhub publish <org>/<skill>[/]"
        )
        raise typer.Exit(1)

    # 3. Fall back to API (old config without cached orgs)
    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{api_url}/v1/orgs",
            headers=build_headers(token),
        )
        resp.raise_for_status()
        orgs = resp.json()

    if len(orgs) == 0:
        console.print(
            "[red]Error: No namespaces available. "
            "Run 'dhub login' to refresh your org memberships.[/]"
        )
        raise typer.Exit(1)

    if len(orgs) > 1:
        slugs = ", ".join(o["slug"] for o in orgs)
        console.print(
            f"[red]Error: You have multiple namespaces ({slugs}). "
            f"Run 'dhub config default-org' to set a default, "
            f"or set DHUB_DEFAULT_ORG, "
            f"or specify: dhub publish <org>/<skill>[/]"
        )
        raise typer.Exit(1)

    org_slug = orgs[0]["slug"]
    console.print(f"Auto-detected namespace: [cyan]{org_slug}[/]")
    return org_slug


def _resolve_bump_level(patch: bool, minor: bool, major: bool) -> str:
    """Determine bump level from CLI flags. Default is 'patch'."""
    flags = sum([patch, minor, major])
    if flags > 1:
        console.print("[red]Error: Only one of --patch, --minor, --major can be specified.[/]")
        raise typer.Exit(1)
    if major:
        return "major"
    if minor:
        return "minor"
    return "patch"


def _auto_bump_version(
    api_url: str,
    token: str,
    org: str,
    name: str,
    bump_level: str,
) -> tuple[str, str | None, str | None]:
    """Fetch the latest version from the registry and auto-bump it.

    Returns (bumped_version, latest_checksum, current_version).
    On first publish (404), latest_checksum and current_version are None.
    """
    from dhub.cli.config import build_headers
    from dhub.core.validation import FIRST_VERSION, bump_version

    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{api_url}/v1/skills/{org}/{name}/latest-version",
            headers=build_headers(token),
        )

    if resp.status_code == 404:
        console.print(f"First publish — using version [cyan]{FIRST_VERSION}[/]")
        return FIRST_VERSION, None, None

    resp.raise_for_status()
    data = resp.json()
    current = data["version"]
    latest_checksum = data.get("checksum")
    bumped = bump_version(current, bump_level)
    console.print(f"Auto-bumped: {current} -> [cyan]{bumped}[/]")
    return bumped, latest_checksum, current


def _create_zip(path: Path) -> bytes:
    """Create an in-memory zip archive of a directory.

    Skips hidden files (names starting with '.') and __pycache__
    directories.

    Args:
        path: Root directory to archive.

    Returns:
        Raw bytes of the zip file.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(path.rglob("*")):
            if not file.is_file():
                continue
            # Skip hidden files and __pycache__
            relative = file.relative_to(path)
            parts = relative.parts
            if any(part.startswith(".") or part == "__pycache__" for part in parts):
                continue
            zf.write(file, relative)
    return buf.getvalue()


def list_command() -> None:
    """List all published skills on the registry."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    api_url = get_api_url()

    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{api_url}/v1/skills",
            headers=build_headers(get_token()),
        )
        resp.raise_for_status()
        skills = resp.json()

    console.print(f"Registry: [dim]{api_url}[/]")

    if not skills:
        console.print("No skills published yet.")
        return

    table = Table(title="Published Skills", show_lines=True)
    table.add_column("Org", style="cyan")
    table.add_column("Skill", style="green")
    table.add_column("Version")
    table.add_column("Updated")
    table.add_column("Safety")
    table.add_column("Downloads")
    table.add_column("Author")
    table.add_column("Description")

    for s in skills:
        rating = s.get("safety_rating", "")
        rating_style = GRADE_COLORS.get(rating, "white")
        table.add_row(
            s["org_slug"],
            s["skill_name"],
            s["latest_version"],
            s.get("updated_at", ""),
            f"[{rating_style}]{rating}[/]",
            str(s.get("download_count", 0)),
            s.get("author", ""),
            s.get("description", ""),
        )

    console.print(table)


def delete_command(
    skill_ref: str = typer.Argument(help="Skill name (e.g. 'myorg/my-skill')"),
    version: str = typer.Option(None, "--version", "-v", help="Version to delete (omit to delete all)"),
) -> None:
    """Delete a published skill version (or all versions) from the registry."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    org_slug, skill_name = _parse_skill_ref(skill_ref)

    api_url = get_api_url()
    headers = build_headers(get_token())

    if version is None:
        # Delete ALL versions
        typer.confirm(
            f"Delete ALL versions of {org_slug}/{skill_name}?",
            abort=True,
        )

        with httpx.Client(timeout=60) as client:
            resp = client.delete(
                f"{api_url}/v1/skills/{org_slug}/{skill_name}",
                headers=headers,
            )
            if resp.status_code == 404:
                console.print(
                    f"[red]Error: Skill '{skill_name}' not found in {org_slug}.[/]"
                )
                raise typer.Exit(1)
            if resp.status_code == 403:
                console.print(
                    "[red]Error: You don't have permission to delete this skill.[/]"
                )
                raise typer.Exit(1)
            resp.raise_for_status()

        data = resp.json()
        count = data["versions_deleted"]
        console.print(
            f"[green]Deleted {count} version(s) of {org_slug}/{skill_name}[/]"
        )
    else:
        # Delete a single version
        with httpx.Client(timeout=60) as client:
            resp = client.delete(
                f"{api_url}/v1/skills/{org_slug}/{skill_name}/{version}",
                headers=headers,
            )
            if resp.status_code == 404:
                console.print(
                    f"[red]Error: Version {version} not found for "
                    f"{org_slug}/{skill_name}.[/]"
                )
                raise typer.Exit(1)
            if resp.status_code == 403:
                console.print(
                    "[red]Error: You don't have permission to delete this version.[/]"
                )
                raise typer.Exit(1)
            resp.raise_for_status()

        console.print(f"[green]Deleted: {org_slug}/{skill_name}@{version}[/]")


def eval_report_command(
    skill_ref: str = typer.Argument(help="Skill name (e.g. 'myorg/my-skill@1.0.0')"),
) -> None:
    """View the agent evaluation report for a skill version."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    # Parse skill reference (org/skill@version)
    if "@" not in skill_ref:
        console.print(
            "[red]Error: Skill reference must include version: org/skill@version[/]"
        )
        raise typer.Exit(1)

    skill_path, version = skill_ref.rsplit("@", 1)
    org_slug, skill_name = _parse_skill_ref(skill_path)

    api_url = get_api_url()
    headers = build_headers(get_token())

    # Fetch the eval report
    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{api_url}/v1/skills/{org_slug}/{skill_name}/versions/{version}/eval-report",
            headers=headers,
        )
        if resp.status_code == 404:
            console.print(
                f"[red]Error: No eval report found for {org_slug}/{skill_name}@{version}[/]"
            )
            raise typer.Exit(1)
        resp.raise_for_status()

    data = resp.json()

    # Handle null response (no eval report yet)
    if data is None:
        console.print(f"No eval report available for {org_slug}/{skill_name}@{version}")
        return

    # Display report summary
    status = data["status"]
    passed = data["passed"]
    total = data["total"]
    duration = data["total_duration_ms"] / 1000

    _status_colors = {"passed": "green", "failed": "red", "error": "red", "pending": "yellow"}
    status_color = _status_colors.get(status, "white")

    console.print(f"\nEval Report: {org_slug}/{skill_name}@{version}")
    console.print(f"Agent: [cyan]{data['agent']}[/]")
    console.print(f"Judge: [dim]{data['judge_model']}[/]")
    console.print(f"Status: [{status_color}]{status.upper()}[/]")
    console.print(f"Results: [{status_color}]{passed}/{total}[/] cases passed")
    console.print(f"Duration: {duration:.2f}s")

    if data.get("error_message"):
        console.print(f"\n[red]Error: {data['error_message']}[/]")

    # Display individual case results
    console.print("\nCase Results:")
    for case in data["case_results"]:
        verdict = case["verdict"]
        _verdict_colors = {"pass": "green", "fail": "red", "error": "red"}
        verdict_color = _verdict_colors.get(verdict, "white")

        console.print(f"\n  [{verdict_color}]{case['name']}[/]: {verdict.upper()}")
        console.print(f"    {case['description']}")
        if case["reasoning"]:
            console.print(f"    Reasoning: {case['reasoning']}")


def install_command(
    skill_ref: str = typer.Argument(help="Skill name (e.g. 'myorg/my-skill')"),
    version: str = typer.Option(
        "latest", "--version", "-v", help="Version spec"
    ),
    agent: str = typer.Option(
        None, "--agent", help="Target agent (claude, cursor, etc.) or 'all'"
    ),
    allow_risky: bool = typer.Option(
        False, "--allow-risky", help="Allow installing C-grade (risky) skills"
    ),
) -> None:
    """Install a skill from the registry."""
    from dhub.cli.config import build_headers, get_api_url, get_token
    from dhub.core.install import (
        get_dhub_skill_path,
        link_skill_to_agent,
        link_skill_to_all_agents,
        verify_checksum,
    )

    org_slug, skill_name = _parse_skill_ref(skill_ref)

    headers = build_headers(get_token())
    base_url = get_api_url()

    # Resolve the version to a concrete download URL and checksum
    resolve_params: dict[str, str] = {"spec": version}
    if allow_risky:
        resolve_params["allow_risky"] = "true"
    with console.status(f"Resolving {org_slug}/{skill_name}@{version}..."):
        with httpx.Client(timeout=60) as client:
            resp = client.get(
                f"{base_url}/v1/resolve/{org_slug}/{skill_name}",
                params=resolve_params,
                headers=headers,
            )
            if resp.status_code == 404:
                console.print(
                    f"[red]Error: Skill '{skill_ref}' not found.[/]"
                )
                raise typer.Exit(1)
            resp.raise_for_status()
            data = resp.json()

    resolved_version: str = data["version"]
    download_url: str = data["download_url"]
    expected_checksum: str = data["checksum"]

    # Download and verify
    with console.status(f"Downloading {org_slug}/{skill_name}@{resolved_version}..."):
        with httpx.Client(timeout=60) as client:
            resp = client.get(download_url)
            resp.raise_for_status()
            zip_data = resp.content
    verify_checksum(zip_data, expected_checksum)

    # Extract to the canonical skill path
    skill_path = get_dhub_skill_path(org_slug, skill_name)
    skill_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        zf.extractall(skill_path)

    console.print(
        f"[green]Installed {org_slug}/{skill_name}@{resolved_version} "
        f"to {skill_path}[/]"
    )

    # Create agent symlinks
    if agent:
        if agent == "all":
            linked = link_skill_to_all_agents(org_slug, skill_name)
            console.print(
                f"[green]Linked to agents: {', '.join(linked)}[/]"
            )
        else:
            link_path = link_skill_to_agent(org_slug, skill_name, agent)
            console.print(
                f"[green]Linked to {agent} at {link_path}[/]"
            )


def uninstall_command(
    skill_ref: str = typer.Argument(help="Skill name (e.g. 'myorg/my-skill')"),
) -> None:
    """Remove a locally installed skill and its agent symlinks."""
    from dhub.core.install import uninstall_skill

    org_slug, skill_name = _parse_skill_ref(skill_ref)

    try:
        unlinked = uninstall_skill(org_slug, skill_name)
    except FileNotFoundError:
        console.print(
            f"[red]Error: Skill '{skill_ref}' is not installed.[/]"
        )
        raise typer.Exit(1)

    console.print(f"[green]Uninstalled {org_slug}/{skill_name}[/]")
    if unlinked:
        console.print(f"[green]Removed symlinks from: {', '.join(unlinked)}[/]")
