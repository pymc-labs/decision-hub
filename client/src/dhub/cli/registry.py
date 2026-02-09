"""Publish, install, list, and delete commands for the skill registry."""

import io
import json
import shutil
import zipfile
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()


def _publish_skill_directory(
    path: Path,
    org: str,
    name: str,
    version: str | None,
    bump_level: str,
    api_url: str,
    token: str,
) -> bool:
    """Publish a single skill directory to the registry.

    Returns True on success, False on skip (no changes).
    Raises typer.Exit on errors.
    """
    from dhub.cli.config import build_headers
    from dhub.core.validation import (
        FIRST_VERSION,
        bump_version,
        validate_semver,
        validate_skill_name,
    )

    validate_skill_name(name)

    with console.status(f"Packaging {name}..."):
        zip_data = _create_zip(path)

    # Resolve version: explicit wins, otherwise auto-bump
    if version is not None:
        validate_semver(version)
    else:
        from dhub.core.install import compute_checksum

        local_checksum = compute_checksum(zip_data)
        version, latest_checksum, current_version = _auto_bump_version(
            api_url, token, org, name, bump_level, bump_version, FIRST_VERSION,
        )
        if latest_checksum is not None and local_checksum == latest_checksum:
            console.print(f"  No changes detected for [cyan]{name}[/]. Already at [cyan]{current_version}[/].")
            return False

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

    grade_colors = {"A": "green", "B": "yellow", "C": "red", "F": "red"}
    grade_color = grade_colors.get(eval_status, "white")
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

    return True


def publish_command(
    source: str = typer.Argument(
        ..., help="Path to a directory containing skills, or a git repo URL"
    ),
    version: str = typer.Option(None, "--version", help="Explicit semver version (overrides auto-bump)"),
    patch: bool = typer.Option(False, "--patch", help="Bump patch version"),
    minor: bool = typer.Option(False, "--minor", help="Bump minor version"),
    major: bool = typer.Option(False, "--major", help="Bump major version"),
    ref: str = typer.Option(None, "--ref", help="Branch/tag/commit (only for git repo URLs)"),
) -> None:
    """Publish skills to the registry.

    SOURCE can be:
    - A git repository URL (HTTPS/SSH) — clones the repo, discovers all
      skills, and publishes each one
    - A local path — discovers all skill directories (containing SKILL.md)
      under the given path and publishes each one

    Version is auto-bumped by default (patch). Use --major or --minor to
    control the bump level, or --version to set an explicit version.
    """
    from dhub.core.git_repo import looks_like_git_url

    # Validate flags early (before auth) to fail fast on bad input
    bump_level = _resolve_bump_level(patch, minor, major)

    # Detect git URL in the first positional arg
    if looks_like_git_url(source):
        _publish_from_git_repo(source, ref, version, bump_level)
        return

    if ref is not None:
        console.print("[red]Error: --ref can only be used with a git repository URL.[/]")
        raise typer.Exit(1)

    _publish_from_directory(Path(source), version, bump_level)


def _publish_discovered_skills(
    skill_dirs: list[Path],
    root: Path,
    org: str,
    version: str | None,
    bump_level: str,
    api_url: str,
    token: str,
) -> None:
    """Publish a list of discovered skill directories."""
    from dhub.core.manifest import parse_skill_md

    console.print(f"Found [cyan]{len(skill_dirs)}[/] skill(s):")
    for skill_dir in skill_dirs:
        rel = skill_dir.relative_to(root)
        console.print(f"  - {rel}")
    console.print()

    published = 0
    failed = 0
    skipped = 0
    for skill_dir in skill_dirs:
        manifest = parse_skill_md(skill_dir / "SKILL.md")
        name = manifest.name
        rel = skill_dir.relative_to(root)
        console.print(f"Publishing [cyan]{name}[/] (from {rel})...")

        try:
            result = _publish_skill_directory(
                skill_dir, org, name, version, bump_level, api_url, token,
            )
            if result:
                published += 1
            else:
                skipped += 1
        except typer.Exit:
            failed += 1
            console.print(f"[red]Failed to publish {name}, continuing...[/]")
            continue

    console.print()
    console.print(
        f"Done: [green]{published} published[/], "
        f"[yellow]{skipped} skipped[/], "
        f"[red]{failed} failed[/]"
    )

    if failed > 0:
        raise typer.Exit(1)


def _publish_from_directory(
    path: Path,
    version: str | None,
    bump_level: str,
) -> None:
    """Discover and publish all skills under a local directory."""
    from dhub.cli.config import get_api_url, get_token
    from dhub.core.git_repo import discover_skills

    if not path.is_dir():
        console.print(f"[red]Error: '{path}' is not a directory.[/]")
        raise typer.Exit(1)

    skill_dirs = discover_skills(path)

    if not skill_dirs:
        console.print(f"[yellow]No skills found under '{path}'.[/]")
        raise typer.Exit(1)

    api_url = get_api_url()
    token = get_token()
    org = _auto_detect_org(api_url, token)

    _publish_discovered_skills(skill_dirs, path, org, version, bump_level, api_url, token)


def _publish_from_git_repo(
    repo_url: str,
    ref: str | None,
    version: str | None,
    bump_level: str,
) -> None:
    """Clone a git repo, discover skills, and publish each one."""
    from dhub.cli.config import get_api_url, get_token
    from dhub.core.git_repo import clone_repo, discover_skills

    api_url = get_api_url()
    token = get_token()
    org = _auto_detect_org(api_url, token)

    with console.status(f"Cloning {repo_url}..."):
        try:
            repo_root = clone_repo(repo_url, ref=ref)
        except RuntimeError as exc:
            console.print(f"[red]Error: {exc}[/]")
            raise typer.Exit(1)

    try:
        skill_dirs = discover_skills(repo_root)

        if not skill_dirs:
            console.print("[yellow]No skills found in the repository.[/]")
            raise typer.Exit(1)

        _publish_discovered_skills(
            skill_dirs, repo_root, org, version, bump_level, api_url, token,
        )
    finally:
        shutil.rmtree(repo_root.parent, ignore_errors=True)


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
    bump_version_fn,
    first_version: str,
) -> tuple[str, str | None, str | None]:
    """Fetch the latest version from the registry and auto-bump it.

    Returns (bumped_version, latest_checksum, current_version).
    On first publish (404), latest_checksum and current_version are None.
    """
    from dhub.cli.config import build_headers

    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{api_url}/v1/skills/{org}/{name}/latest-version",
            headers=build_headers(token),
        )

    if resp.status_code == 404:
        version = first_version
        console.print(f"First publish — using version [cyan]{version}[/]")
        return version, None, None

    resp.raise_for_status()
    data = resp.json()
    current = data["version"]
    latest_checksum = data.get("checksum")
    version = bump_version_fn(current, bump_level)
    console.print(f"Auto-bumped: {current} -> [cyan]{version}[/]")
    return version, latest_checksum, current


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
    from dhub.cli.banner import check_and_show_update, print_banner
    from dhub.cli.config import build_headers, get_api_url, get_token

    print_banner(console)

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
        check_and_show_update(console)
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

    grade_styles = {"A": "green", "B": "yellow", "C": "dark_orange", "F": "red"}
    for s in skills:
        rating = s.get("safety_rating", "")
        rating_style = grade_styles.get(rating, "white")
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

    check_and_show_update(console)


def delete_command(
    skill_ref: str = typer.Argument(help="Skill name (e.g. 'myorg/my-skill')"),
    version: str = typer.Option(None, "--version", "-v", help="Version to delete (omit to delete all)"),
) -> None:
    """Delete a published skill version (or all versions) from the registry."""
    from dhub.cli.config import build_headers, get_api_url, get_token

    parts = skill_ref.split("/", 1)
    if len(parts) != 2:
        console.print(
            "[red]Error: Skill reference must be in org/skill format.[/]"
        )
        raise typer.Exit(1)
    org_slug, skill_name = parts

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
    parts = skill_path.split("/", 1)
    if len(parts) != 2:
        console.print(
            "[red]Error: Skill reference must be in org/skill@version format.[/]"
        )
        raise typer.Exit(1)
    org_slug, skill_name = parts

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

    status_colors = {"completed": "green", "failed": "red", "error": "red", "pending": "yellow"}
    status_color = status_colors.get(status, "white")

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
        verdict_colors = {"pass": "green", "fail": "red", "error": "red"}
        verdict_color = verdict_colors.get(verdict, "white")

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

    # Parse skill reference
    parts = skill_ref.split("/", 1)
    if len(parts) != 2:
        console.print(
            "[red]Error: Skill reference must be in org/skill format.[/]"
        )
        raise typer.Exit(1)
    org_slug, skill_name = parts

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

    parts = skill_ref.split("/", 1)
    if len(parts) != 2:
        console.print(
            "[red]Error: Skill reference must be in org/skill format.[/]"
        )
        raise typer.Exit(1)
    org_slug, skill_name = parts

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
