"""Publish, install, list, and delete commands for the skill registry."""

import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
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
    *,
    private: bool = False,
    source_repo_url: str | None = None,
    manifest_path: str | None = None,
    dry_run: bool = False,
) -> bool:
    """Publish a single skill directory to the registry.

    Returns True on success, False on skip (no changes).
    Raises typer.Exit on errors.
    """
    from dhub.cli.config import build_headers, raise_for_status
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
            api_url,
            token,
            org,
            name,
            bump_level,
            bump_version,
            FIRST_VERSION,
        )
        if latest_checksum is not None and local_checksum == latest_checksum:
            console.print(f"  No changes detected for [cyan]{name}[/]. Already at [cyan]{current_version}[/].")
            return False

    if dry_run:
        import zipfile as _zf

        from dhub.cli.output import is_json, print_json

        with _zf.ZipFile(io.BytesIO(zip_data)) as zf:
            file_count = len(zf.namelist())
        result = {"org": org, "skill": name, "version": version, "files": file_count, "size_bytes": len(zip_data)}
        if is_json():
            print_json(result)
        else:
            console.print(
                f"[yellow]Dry run:[/] Would publish {org}/{name}@{version} ({len(zip_data):,} bytes, {file_count} files)"
            )
        return True

    meta: dict[str, str] = {"org_slug": org, "skill_name": name, "version": version}
    if private:
        meta["visibility"] = "org"
    if source_repo_url:
        meta["source_repo_url"] = source_repo_url
    if manifest_path:
        meta["manifest_path"] = manifest_path
    metadata = json.dumps(meta)

    with console.status(f"Publishing {org}/{name}@{version}..."):
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{api_url}/v1/publish",
                headers=build_headers(token),
                files={"zip_file": ("skill.zip", zip_data, "application/zip")},
                data={"metadata": metadata},
            )
        if resp.status_code == 409:
            console.print(f"[red]Error: Version {version} already exists for {org}/{name}.[/]")
            raise typer.Exit(1)
        if resp.status_code == 422:
            detail = resp.json().get("detail", "Gauntlet checks failed")
            console.print(f"[red]Rejected (Grade F): {detail}[/]")
            raise typer.Exit(1)
        if resp.status_code == 503:
            console.print("[red]Error: Server LLM judge not configured. Cannot publish without LLM review.[/]")
            raise typer.Exit(1)
        raise_for_status(resp)

    data = resp.json()
    eval_status = data.get("eval_status", "")
    eval_report_status = data.get("eval_report_status")

    from dhub.cli.output import is_json, print_json

    if is_json():
        print_json(
            {
                "org": org,
                "skill": name,
                "version": version,
                "grade": eval_status,
                "eval_run_id": data.get("eval_run_id"),
            }
        )
        return True

    grade_colors = {"A": "green", "B": "yellow", "C": "red", "F": "red"}
    grade_color = grade_colors.get(eval_status, "white")
    private_label = " (org-private)" if private else ""
    console.print(f"[green]Published: {org}/{name}@{version}[/] (Grade [{grade_color}]{eval_status}[/]){private_label}")
    if eval_status == "B":
        console.print("[yellow]Warning: Grade B — elevated permissions detected.[/]")
    elif eval_status == "C":
        console.print(
            "[red]Warning: Grade C — ambiguous patterns detected. Users will need --allow-risky to install.[/]"
        )

    eval_run_id = data.get("eval_run_id")
    if eval_report_status == "pending" and eval_run_id:
        console.print(f"[dim]Agent assessment started (run: {eval_run_id[:8]}...)[/]")
        console.print("[dim]Tailing logs... (Ctrl-C to detach)[/]")
        try:
            from dhub.cli.config import build_headers as _bh

            _tail_eval_logs(api_url, _bh(token), eval_run_id)
        except KeyboardInterrupt:
            console.print("\n[dim]Detached. Resume with: dhub logs {eval_run_id} --follow[/]")
    elif eval_report_status == "pending":
        console.print("[dim]Agent assessment running in background...[/]")

    return True


def publish_command(
    source: str = typer.Argument(..., help="Path to a directory containing skills, or a git repo URL"),
    version: str = typer.Option(None, "--version", help="Explicit semver version (overrides auto-bump)"),
    org: str = typer.Option(None, "--org", "-o", help="Override the default namespace (org slug)"),
    patch: bool = typer.Option(False, "--patch", help="Bump patch version"),
    minor: bool = typer.Option(False, "--minor", help="Bump minor version"),
    major: bool = typer.Option(False, "--major", help="Bump major version"),
    ref: str = typer.Option(None, "--ref", help="Branch/tag/commit (only for git repo URLs)"),
    private: bool = typer.Option(False, "--private", help="Publish as org-private (visible only to org members)"),
    no_track: bool = typer.Option(False, "--no-track", help="Don't auto-create a tracker for this GitHub repo"),
    track: bool = typer.Option(False, "--track", help="Re-enable tracking for this GitHub repo"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be published without actually publishing"),
) -> None:
    """Publish skills to the registry.

    SOURCE can be:
    - A git repository URL (HTTPS/SSH) — clones the repo, discovers all
      skills, and publishes each one
    - A local path — discovers all skill directories (containing SKILL.md)
      under the given path and publishes each one

    Version is auto-bumped by default (patch). Use --major or --minor to
    control the bump level, or --version to set an explicit version.

    Use --org to override the default namespace. You can also specify the
    org inline: dhub publish org/skill-name .

    When publishing from a GitHub URL, a tracker is automatically created
    so future commits are republished. Use --no-track to skip, or --track
    to re-enable a previously disabled tracker.
    """
    from dhub.core.git_repo import looks_like_git_url

    # Validate flags early (before auth) to fail fast on bad input
    bump_level = _resolve_bump_level(patch, minor, major)

    if no_track and track:
        console.print("[red]Error: --no-track and --track are mutually exclusive.[/]")
        raise typer.Exit(1)

    # Detect git URL in the first positional arg
    if looks_like_git_url(source):
        _publish_from_git_repo(
            source,
            ref,
            version,
            bump_level,
            private=private,
            no_track=no_track,
            track=track,
            org_override=org,
            dry_run=dry_run,
        )
        return

    if ref is not None:
        console.print("[red]Error: --ref can only be used with a git repository URL.[/]")
        raise typer.Exit(1)
    if track:
        console.print("[red]Error: --track can only be used with a git repository URL.[/]")
        raise typer.Exit(1)

    _publish_from_directory(Path(source), version, bump_level, private=private, org_override=org, dry_run=dry_run)


def _publish_discovered_skills(
    skill_dirs: list[Path],
    root: Path,
    org: str,
    version: str | None,
    bump_level: str,
    api_url: str,
    token: str,
    *,
    private: bool = False,
    source_repo_url: str | None = None,
    dry_run: bool = False,
) -> None:
    """Publish a list of discovered skill directories."""
    from dhub.cli.output import is_json
    from dhub.core.manifest import parse_skill_md

    json_mode = is_json()

    if not json_mode:
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
        if not json_mode:
            console.print(f"Publishing [cyan]{name}[/] (from {rel})...")

        # Compute relative path to SKILL.md within the repo (only meaningful
        # when publishing from a git source — skip for local-only publishes
        # to avoid overwriting a previously correct git-based path).
        skill_manifest_path = (skill_dir / "SKILL.md").relative_to(root).as_posix() if source_repo_url else None

        try:
            result = _publish_skill_directory(
                skill_dir,
                org,
                name,
                version,
                bump_level,
                api_url,
                token,
                private=private,
                source_repo_url=source_repo_url,
                manifest_path=skill_manifest_path,
                dry_run=dry_run,
            )
            if result:
                published += 1
            else:
                skipped += 1
        except typer.Exit:
            failed += 1
            if not json_mode:
                console.print(f"[red]Failed to publish {name}, continuing...[/]")
            continue

    if not json_mode:
        console.print()
        console.print(f"Done: [green]{published} published[/], [yellow]{skipped} skipped[/], [red]{failed} failed[/]")

    if failed > 0:
        raise typer.Exit(1)


def _publish_from_directory(
    path: Path,
    version: str | None,
    bump_level: str,
    *,
    private: bool = False,
    org_override: str | None = None,
    dry_run: bool = False,
) -> None:
    """Discover and publish all skills under a local directory."""
    from dhub.cli.config import get_api_url, get_token
    from dhub.cli.output import is_json
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

    if org_override:
        if not is_json():
            console.print(f"Using namespace: [cyan]{org_override}[/]")
        org = org_override
    else:
        org = _auto_detect_org(api_url, token)

    _publish_discovered_skills(
        skill_dirs, path, org, version, bump_level, api_url, token, private=private, dry_run=dry_run
    )


def _publish_from_git_repo(
    repo_url: str,
    ref: str | None,
    version: str | None,
    bump_level: str,
    *,
    private: bool = False,
    no_track: bool = False,
    track: bool = False,
    org_override: str | None = None,
    dry_run: bool = False,
) -> None:
    """Clone a git repo, discover skills, and publish each one."""
    from dhub.cli.config import build_headers, get_api_url, get_token
    from dhub.core.git_repo import clone_repo, discover_skills, git_url_to_https

    api_url = get_api_url()
    token = get_token()

    if org_override:
        console.print(f"Using namespace: [cyan]{org_override}[/]")
        org = org_override
    else:
        org = _auto_detect_org(api_url, token)

    with console.status(f"Cloning {repo_url}..."):
        try:
            repo_root = clone_repo(repo_url, ref=ref)
        except RuntimeError as exc:
            console.print(f"[red]Error: {exc}[/]")
            raise typer.Exit(1) from None

    publish_exit: typer.Exit | None = None
    try:
        skill_dirs = discover_skills(repo_root)

        if not skill_dirs:
            console.print("[yellow]No skills found in the repository.[/]")
            raise typer.Exit(1)

        source_repo_url = git_url_to_https(repo_url)

        try:
            _publish_discovered_skills(
                skill_dirs,
                repo_root,
                org,
                version,
                bump_level,
                api_url,
                token,
                private=private,
                source_repo_url=source_repo_url,
                dry_run=dry_run,
            )
        except typer.Exit as e:
            # Capture partial-failure exit so auto-tracking still runs
            publish_exit = e

        # Detect branch before cleanup — ref=None means the repo's default branch
        branch = ref or _detect_branch(repo_root)
    finally:
        shutil.rmtree(repo_root.parent, ignore_errors=True)

    # Auto-tracking: create or manage tracker for this GitHub repo
    if not no_track:
        _ensure_tracker(api_url, build_headers(token), repo_url, branch, track=track)

    if publish_exit is not None:
        raise publish_exit


def _detect_branch(repo_root: Path) -> str:
    """Detect the current branch of a cloned repo. Falls back to 'main'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            if branch and branch != "HEAD":
                return branch
    except Exception:
        pass
    return "main"


def _ensure_tracker(api_url: str, headers: dict, repo_url: str, branch: str, *, track: bool = False) -> None:
    """Create a tracker or re-enable an existing one after a GitHub publish.

    - If no tracker exists: creates one (auto-track on first publish).
    - If tracker exists and is enabled: does nothing.
    - If tracker exists but disabled: only re-enables if --track was passed.
    """
    from dhub.cli.config import raise_for_status

    # Check if a tracker already exists for this repo+branch
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.get(f"{api_url}/v1/trackers", headers=headers)
            raise_for_status(resp)
            existing = resp.json()
    except (SystemExit, typer.Exit):
        raise  # Don't swallow typer.Exit (e.g. from 426 handler)
    except Exception:
        return  # Don't fail the publish if tracker API is unavailable

    match = next((t for t in existing if t["repo_url"] == repo_url and t["branch"] == branch), None)

    if match is None:
        # No tracker exists — create one
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{api_url}/v1/trackers",
                    headers=headers,
                    json={"repo_url": repo_url, "branch": branch},
                )
                if resp.status_code == 201:
                    data = resp.json()
                    console.print(f"[dim]Auto-tracking enabled for {repo_url}@{branch}[/]")
                    if data.get("warning"):
                        console.print(f"[yellow]Warning: {data['warning']}[/]")
                elif resp.status_code != 409:
                    # 409 = already exists (race condition), that's fine
                    pass
        except Exception:
            pass  # Best-effort — don't fail the publish
        return

    if not match["enabled"] and track:
        # Tracker exists but paused, and user asked to re-enable
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.patch(
                    f"{api_url}/v1/trackers/{match['id']}",
                    headers=headers,
                    json={"enabled": True},
                )
                if resp.status_code == 200:
                    console.print(f"[dim]Tracking re-enabled for {repo_url}@{branch}[/]")
        except Exception:
            pass
    elif not match["enabled"]:
        console.print("[dim]Tracking is paused for this repo. Use --track to re-enable.[/]")


def _auto_detect_org(api_url: str, token: str) -> str:
    """Auto-detect the org for publishing.

    Checks in order:
    1. DHUB_DEFAULT_ORG env var or config default_org
    2. Cached orgs from config (if exactly one)
    3. Falls back to API call (for old configs without cached orgs)
    """
    from dhub.cli.config import build_headers, get_default_org, load_config, raise_for_status

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
            f"or use --org to specify the namespace.[/]"
        )
        raise typer.Exit(1)

    # 3. Fall back to API (old config without cached orgs)
    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{api_url}/v1/orgs",
            headers=build_headers(token),
        )
        raise_for_status(resp)
        orgs = resp.json()

    if len(orgs) == 0:
        console.print("[red]Error: No namespaces available. Run 'dhub login' to refresh your org memberships.[/]")
        raise typer.Exit(1)

    if len(orgs) > 1:
        slugs = ", ".join(o["slug"] for o in orgs)
        console.print(
            f"[red]Error: You have multiple namespaces ({slugs}). "
            f"Run 'dhub config default-org' to set a default, "
            f"or set DHUB_DEFAULT_ORG, "
            f"or use --org to specify the namespace.[/]"
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
    from dhub.cli.config import build_headers, raise_for_status

    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{api_url}/v1/skills/{org}/{name}/latest-version",
            headers=build_headers(token),
        )

    from dhub.cli.output import is_json

    if resp.status_code == 404:
        version = first_version
        if not is_json():
            console.print(f"First publish — using version [cyan]{version}[/]")
        return version, None, None

    raise_for_status(resp)
    data = resp.json()
    current = data["version"]
    latest_checksum = data.get("checksum")
    version = bump_version_fn(current, bump_level)
    if not is_json():
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


def _render_skills_table(skills: list[dict], title: str = "Published Skills") -> Table:
    """Build a Rich table from a list of skill dicts."""
    table = Table(title=title, show_lines=True)
    table.add_column("Org", style="cyan")
    table.add_column("Skill", style="green")
    table.add_column("Category", style="magenta")
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
        updated = s.get("updated_at", "")[:10]
        table.add_row(
            s["org_slug"],
            s["skill_name"],
            s.get("category", ""),
            s["latest_version"],
            updated,
            f"[{rating_style}]{rating}[/]",
            str(s.get("download_count", 0)),
            s.get("author", ""),
            s.get("description", ""),
        )
    return table


def list_command(
    org: str = typer.Option(None, "--org", "-o", help="Filter by organization"),
    skill: str = typer.Option(None, "--skill", "-s", help="Filter by skill name (substring match)"),
    page_size: int = typer.Option(50, "--page-size", "-n", min=1, max=100, help="Items per page"),
    all_pages: bool = typer.Option(False, "--all", help="Dump all pages without prompting"),
) -> None:
    """List published skills on the registry."""
    import sys

    from dhub.cli.banner import print_banner
    from dhub.cli.config import build_headers, get_api_url, get_optional_token, raise_for_status
    from dhub.cli.output import is_json, print_json

    json_mode = is_json()

    if not json_mode:
        print_banner(console)

    api_url = get_api_url()
    headers = build_headers(get_optional_token())

    if not json_mode:
        console.print(f"Registry: [dim]{api_url}[/]")

    all_items: list[dict] = []
    page = 1
    total = 0
    found_any = False
    with httpx.Client(timeout=60) as client:
        while True:
            params: dict[str, int | str] = {"page": page, "page_size": page_size, "sort": "downloads"}
            if org:
                params["org"] = org
            if skill:
                params["search"] = skill
            resp = client.get(
                f"{api_url}/v1/skills",
                headers=headers,
                params=params,
            )
            raise_for_status(resp)
            data = resp.json()

            items = data["items"]
            total = data["total"]
            total_pages = data["total_pages"]

            if json_mode:
                all_items.extend(items)
                if page >= total_pages or total == 0:
                    break
                page += 1
                continue

            if total == 0:
                console.print("No skills found.")
                break

            if items:
                found_any = True
                console.print(_render_skills_table(items))

            console.print(f"[dim]Page {page} of {total_pages} ({total} total skills)[/]")

            if page >= total_pages:
                if not found_any:
                    filter_msg = ""
                    if org:
                        filter_msg += f" for org '{org}'"
                    if skill:
                        filter_msg += f" matching '{skill}'"
                    console.print(f"No skills found{filter_msg}.")
                break

            if all_pages:
                page += 1
                continue

            # Interactive prompt — only if stdout is a TTY
            if not sys.stdout.isatty():
                break

            try:
                answer = console.input("[bold]Show next page?[/] [dim](y/n)[/] ")
                if answer.strip().lower() not in ("y", "yes"):
                    break
            except (EOFError, KeyboardInterrupt):
                break

            page += 1

    if json_mode:
        print_json({"items": all_items, "total": total, "page_size": len(all_items), "total_pages": 1})
        return


def delete_command(
    skill_ref: str = typer.Argument(help="Skill name (e.g. 'myorg/my-skill')"),
    version: str = typer.Option(None, "--version", "-v", help="Version to delete (omit to delete all)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be deleted without actually deleting"),
) -> None:
    """Delete a published skill version (or all versions) from the registry."""
    from dhub.cli.config import build_headers, get_api_url, get_token, raise_for_status
    from dhub.core.validation import parse_skill_ref

    try:
        org_slug, skill_name = parse_skill_ref(skill_ref)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/]")
        raise typer.Exit(1) from None

    api_url = get_api_url()
    headers = build_headers(get_token())

    from dhub.cli.output import is_json, print_json

    if dry_run:
        # Verify skill exists
        with httpx.Client(timeout=60) as client:
            resp = client.get(f"{api_url}/v1/skills/{org_slug}/{skill_name}/summary", headers=headers)
            if resp.status_code == 404:
                console.print(f"[red]Error: Skill '{skill_name}' not found in {org_slug}.[/]")
                raise typer.Exit(1)
            raise_for_status(resp)
        result: dict[str, object] = {"org": org_slug, "skill": skill_name}
        if version:
            result["version"] = version
        else:
            result["all_versions"] = True
        if is_json():
            print_json(result)
        else:
            if version:
                console.print(f"[yellow]Dry run:[/] Would delete {org_slug}/{skill_name}@{version}")
            else:
                console.print(f"[yellow]Dry run:[/] Would delete ALL versions of {org_slug}/{skill_name}")
        return

    if version is None:
        # Delete ALL versions — skip confirmation in JSON mode (agents can't confirm)
        if not is_json():
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
                console.print(f"[red]Error: Skill '{skill_name}' not found in {org_slug}.[/]")
                raise typer.Exit(1)
            if resp.status_code == 403:
                console.print("[red]Error: You don't have permission to delete this skill.[/]")
                raise typer.Exit(1)
            raise_for_status(resp)

        data = resp.json()
        if is_json():
            print_json(data)
            return
        count = data["versions_deleted"]
        console.print(f"[green]Deleted {count} version(s) of {org_slug}/{skill_name}[/]")
    else:
        # Delete a single version
        with httpx.Client(timeout=60) as client:
            resp = client.delete(
                f"{api_url}/v1/skills/{org_slug}/{skill_name}/{version}",
                headers=headers,
            )
            if resp.status_code == 404:
                console.print(f"[red]Error: Version {version} not found for {org_slug}/{skill_name}.[/]")
                raise typer.Exit(1)
            if resp.status_code == 403:
                console.print("[red]Error: You don't have permission to delete this version.[/]")
                raise typer.Exit(1)
            raise_for_status(resp)

        data = resp.json()
        if is_json():
            print_json(data)
            return
        console.print(f"[green]Deleted: {org_slug}/{skill_name}@{version}[/]")


def eval_report_command(
    skill_ref: str = typer.Argument(help="Skill name (e.g. 'myorg/my-skill@1.0.0')"),
) -> None:
    """View the agent evaluation report for a skill version."""
    from dhub.cli.config import build_headers, get_api_url, get_token, raise_for_status

    # Parse skill reference (org/skill@version)
    if "@" not in skill_ref:
        console.print("[red]Error: Skill reference must include version: org/skill@version[/]")
        raise typer.Exit(1)

    skill_path, version = skill_ref.rsplit("@", 1)
    parts = skill_path.split("/", 1)
    if len(parts) != 2:
        console.print("[red]Error: Skill reference must be in org/skill@version format.[/]")
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
            console.print(f"[red]Error: No eval report found for {org_slug}/{skill_name}@{version}[/]")
            raise typer.Exit(1)
        raise_for_status(resp)

    data = resp.json()

    # Handle null response (no eval report yet)
    if data is None:
        console.print(f"No eval report available for {org_slug}/{skill_name}@{version}")
        return

    from dhub.cli.output import is_json, print_json

    if is_json():
        print_json(data)
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


def _install_single_skill(
    skill_ref: str,
    *,
    version: str = "latest",
    agent: str | None = None,
    allow_risky: bool = False,
) -> None:
    """Resolve, download, and extract a single skill.

    Raises typer.Exit on errors.
    """
    from dhub.cli.config import build_headers, get_api_url, get_optional_token, raise_for_status
    from dhub.core.install import (
        get_dhub_skill_path,
        link_skill_to_agent,
        link_skill_to_all_agents,
        verify_checksum,
    )
    from dhub.core.validation import parse_skill_ref

    # Parse skill reference
    try:
        org_slug, skill_name = parse_skill_ref(skill_ref)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/]")
        raise typer.Exit(1) from None

    headers = build_headers(get_optional_token())
    base_url = get_api_url()

    # Resolve the version to a concrete download URL and checksum
    resolve_params: dict[str, str] = {"spec": version}
    if allow_risky:
        resolve_params["allow_risky"] = "true"
    with console.status(f"Resolving {org_slug}/{skill_name}@{version}..."), httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{base_url}/v1/resolve/{org_slug}/{skill_name}",
            params=resolve_params,
            headers=headers,
        )
        if resp.status_code == 404:
            console.print(f"[red]Error: Skill '{skill_ref}' not found.[/]")
            raise typer.Exit(1)
        raise_for_status(resp)
        data = resp.json()

    resolved_version: str = data["version"]
    download_url: str = data["download_url"]
    expected_checksum: str = data["checksum"]

    # Download and verify
    with (
        console.status(f"Downloading {org_slug}/{skill_name}@{resolved_version}..."),
        httpx.Client(timeout=60) as client,
    ):
        resp = client.get(download_url)
        raise_for_status(resp)
        zip_data = resp.content
    verify_checksum(zip_data, expected_checksum)

    # Extract to the canonical skill path
    skill_path = get_dhub_skill_path(org_slug, skill_name)
    skill_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        # Validate entries before extracting to prevent zip-slip attacks
        # where entries like "../../.bashrc" could write outside skill_path.
        from dhub_core.ziputil import validate_zip_entries

        try:
            validate_zip_entries(zf, str(skill_path))
        except ValueError as exc:
            console.print(f"[red]Error: Refusing to install — {exc}[/]")
            raise typer.Exit(1) from None
        zf.extractall(skill_path)

    from dhub.cli.output import is_json, print_json

    if is_json():
        print_json({"org": org_slug, "skill": skill_name, "version": resolved_version, "path": str(skill_path)})
        return

    console.print(f"[green]Installed {org_slug}/{skill_name}@{resolved_version} to {skill_path}[/]")

    # Create agent symlinks
    if agent:
        if agent == "all":
            linked = link_skill_to_all_agents(org_slug, skill_name)
            console.print(f"[green]Linked to agents: {', '.join(linked)}[/]")
        else:
            link_path = link_skill_to_agent(org_slug, skill_name, agent)
            console.print(f"[green]Linked to {agent} at {link_path}[/]")


def _install_from_repo(
    repo_ref: str,
    *,
    version: str = "latest",
    agent: str | None = None,
    allow_risky: bool = False,
) -> None:
    """Install all skills from a GitHub repository."""
    from dhub.cli.config import build_headers, get_api_url, get_optional_token, raise_for_status

    headers = build_headers(get_optional_token())
    base_url = get_api_url()

    # Normalize repo_ref to full URL if it's owner/repo format
    repo_url = f"https://github.com/{repo_ref}" if not repo_ref.startswith("http") else repo_ref

    if len(repo_url) > 500:
        console.print("[red]Error: Repository URL is too long (max 500 characters).[/]")
        raise typer.Exit(1)

    # Fetch all skills from the repo
    with console.status(f"Fetching skills from {repo_ref}..."), httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{base_url}/v1/skills/by-repo",
            params={"repo_url": repo_url},
            headers=headers,
        )
        raise_for_status(resp)
        data = resp.json()

    skills = data["items"]
    if not skills:
        console.print(f"[red]Error: No published skills found for repo '{repo_ref}'.[/]")
        raise typer.Exit(1)

    console.print(f"Found [cyan]{len(skills)}[/] skills in {repo_ref}:")
    for s in skills:
        console.print(f"  {s['org_slug']}/{s['skill_name']}")
    console.print()

    # Install each skill
    succeeded = 0
    failed = 0
    for s in skills:
        ref = f"{s['org_slug']}/{s['skill_name']}"
        try:
            _install_single_skill(ref, version=version, agent=agent, allow_risky=allow_risky)
            succeeded += 1
        except (typer.Exit, httpx.HTTPStatusError) as exc:
            failed += 1
            detail = ""
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                detail = " (rate limited)"
            console.print(f"[yellow]Warning: Failed to install {ref}{detail}, continuing...[/]")

    console.print(f"\n[green]Installed {succeeded}/{len(skills)} skills from {repo_ref}[/]")
    if failed:
        console.print(f"[yellow]{failed} skills failed to install.[/]")


def install_command(
    skill_ref: str = typer.Argument(None, help="Skill name (e.g. 'myorg/my-skill')"),
    version: str = typer.Option("latest", "--version", "-v", help="Version spec"),
    agent: str = typer.Option(None, "--agent", help="Target agent (e.g. claude-code, cursor) or 'all'"),
    allow_risky: bool = typer.Option(False, "--allow-risky", help="Allow installing C-grade (risky) skills"),
    repo: str = typer.Option(None, "--repo", help="Install all skills from a GitHub repo (e.g. 'owner/repo')"),
) -> None:
    """Install a skill from the registry.

    Either provide a skill reference (org/skill) or use --repo to install
    all skills from a GitHub repository.
    """
    if repo and skill_ref:
        console.print("[red]Error: Cannot use both a skill reference and --repo.[/]")
        raise typer.Exit(1)
    if not repo and not skill_ref:
        console.print("[red]Error: Provide a skill reference or use --repo.[/]")
        raise typer.Exit(1)

    if repo:
        _install_from_repo(repo, version=version, agent=agent, allow_risky=allow_risky)
        return

    _install_single_skill(skill_ref, version=version, agent=agent, allow_risky=allow_risky)


def logs_command(
    skill_ref: str = typer.Argument(None, help="Skill ref (org/skill[@version]) or eval run ID"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Tail logs in real-time"),
) -> None:
    """View eval run logs. Tail them with --follow.

    Examples:
        dhub logs                              # list recent eval runs
        dhub logs org/skill --follow           # tail latest run for latest version
        dhub logs org/skill@1.0.0 --follow     # tail latest run for specific version
        dhub logs <run-id> --follow            # tail a specific run by ID
    """
    from dhub.cli.config import build_headers, get_api_url, get_token

    api_url = get_api_url()
    token = get_token()
    headers = build_headers(token)

    if skill_ref is None:
        # No args: list recent runs
        _list_recent_runs(api_url, headers)
        return

    # Try to resolve as a run ID (UUID format)
    run_id = _try_resolve_run_id(skill_ref, api_url, headers)

    if run_id is None:
        console.print(f"[red]Error: Could not resolve '{skill_ref}' to an eval run.[/]")
        raise typer.Exit(1)

    if follow:
        _tail_eval_logs(api_url, headers, run_id)
    else:
        # Show run status
        _show_run_status(api_url, headers, run_id)


def _try_resolve_run_id(skill_ref: str, api_url: str, headers: dict) -> str | None:
    """Try to resolve a skill_ref to an eval run ID.

    Tries in order:
    1. Direct UUID (run ID)
    2. org/skill@version -> latest run for that version
    3. org/skill -> latest version -> latest run
    """
    import re

    # Check if it looks like a UUID
    uuid_pattern = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
    if uuid_pattern.match(skill_ref):
        # Verify it exists
        with httpx.Client(timeout=60) as client:
            resp = client.get(f"{api_url}/v1/eval-runs/{skill_ref}", headers=headers)
            if resp.status_code == 200:
                return skill_ref
            return None

    # Parse org/skill[@version]
    if "@" in skill_ref:
        skill_path, version = skill_ref.rsplit("@", 1)
    else:
        skill_path = skill_ref
        version = None

    parts = skill_path.split("/", 1)
    if len(parts) != 2:
        return None
    org_slug, skill_name = parts

    # Resolve version to version_id
    if version is None:
        # Get latest version
        with httpx.Client(timeout=60) as client:
            resp = client.get(
                f"{api_url}/v1/skills/{org_slug}/{skill_name}/latest-version",
                headers=headers,
            )
            if resp.status_code != 200:
                return None
            version = resp.json()["version"]

    # Use eval-report endpoint to get version_id, then filter runs by it
    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{api_url}/v1/skills/{org_slug}/{skill_name}/eval-report",
            params={"semver": version},
            headers=headers,
        )
        if resp.status_code == 200 and resp.json() is not None:
            version_id = resp.json()["version_id"]
            # Fetch runs filtered by version_id
            resp = client.get(
                f"{api_url}/v1/eval-runs",
                params={"version_id": version_id},
                headers=headers,
            )
            if resp.status_code == 200:
                runs = resp.json()
                if runs:
                    return runs[0]["id"]
            return None

    # Fallback: no eval report for this version, list user's recent runs
    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{api_url}/v1/eval-runs",
            headers=headers,
        )
        if resp.status_code != 200:
            return None
        runs = resp.json()

    if runs:
        return runs[0]["id"]
    return None


def _list_recent_runs(api_url: str, headers: dict) -> None:
    """List recent eval runs for the current user."""
    from dhub.cli.config import raise_for_status

    with httpx.Client(timeout=60) as client:
        resp = client.get(f"{api_url}/v1/eval-runs", headers=headers)
        raise_for_status(resp)
        runs = resp.json()

    from dhub.cli.output import is_json, print_json

    if is_json():
        print_json(runs)
        return

    if not runs:
        console.print("No eval runs found.")
        return

    table = Table(title="Recent Eval Runs")
    table.add_column("Run ID", style="dim")
    table.add_column("Status")
    table.add_column("Agent", style="cyan")
    table.add_column("Cases")
    table.add_column("Stage")
    table.add_column("Created")

    status_colors = {
        "pending": "yellow",
        "provisioning": "yellow",
        "running": "blue",
        "judging": "blue",
        "completed": "green",
        "failed": "red",
    }

    for run in runs:
        status = run["status"]
        color = status_colors.get(status, "white")
        case_info = (
            f"{run.get('current_case_index', '?')}/{run['total_cases']}"
            if run.get("current_case_index") is not None
            else f"0/{run['total_cases']}"
        )
        table.add_row(
            run["id"][:8] + "...",
            f"[{color}]{status}[/]",
            run["agent"],
            case_info,
            run.get("stage") or "-",
            run.get("created_at", "")[:19] if run.get("created_at") else "-",
        )

    console.print(table)
    console.print("\n[dim]Use 'dhub logs <run-id> --follow' to tail a run.[/]")


def _show_run_status(api_url: str, headers: dict, run_id: str) -> None:
    """Show current status of an eval run."""
    from dhub.cli.config import raise_for_status

    with httpx.Client(timeout=60) as client:
        resp = client.get(f"{api_url}/v1/eval-runs/{run_id}", headers=headers)
        raise_for_status(resp)
        run = resp.json()

    from dhub.cli.output import is_json, print_json

    if is_json():
        print_json(run)
        return

    status = run["status"]
    status_colors = {
        "pending": "yellow",
        "provisioning": "yellow",
        "running": "blue",
        "judging": "blue",
        "completed": "green",
        "failed": "red",
    }
    color = status_colors.get(status, "white")

    console.print(f"Run:    [dim]{run['id']}[/]")
    console.print(f"Agent:  [cyan]{run['agent']}[/]")
    console.print(f"Status: [{color}]{status}[/]")
    if run.get("stage"):
        console.print(f"Stage:  {run['stage']}")
    if run.get("current_case"):
        console.print(f"Case:   {run['current_case']} ({run.get('current_case_index', '?')}/{run['total_cases']})")
    if run.get("error_message"):
        console.print(f"[red]Error:  {run['error_message']}[/]")

    console.print(f"\n[dim]Use 'dhub logs {run_id} --follow' to tail logs.[/]")


def _tail_eval_logs(api_url: str, headers: dict, run_id: str) -> None:
    """Tail eval run logs with polling."""
    import time

    from dhub.cli.config import raise_for_status
    from dhub.cli.output import is_json, print_json

    cursor = 0
    json_mode = is_json()
    if not json_mode:
        console.print(f"[dim]Tailing eval run {run_id[:8]}...[/]\n")

    while True:
        with httpx.Client(timeout=60) as client:
            resp = client.get(
                f"{api_url}/v1/eval-runs/{run_id}/logs",
                params={"cursor": cursor},
                headers=headers,
            )
            raise_for_status(resp)
            data = resp.json()

        for event in data["events"]:
            if json_mode:
                print_json(event)
            else:
                _render_event(event)

        cursor = data["next_cursor"]

        if data["run_status"] in ("completed", "failed"):
            if data["run_status"] == "failed":
                console.print("\n[red]Eval run failed.[/]")
            break

        time.sleep(1.5)


def _render_event(event: dict) -> None:
    """Render a single eval event to the console."""
    event_type = event.get("type", "")

    if event_type == "setup":
        console.print(f"[dim]{event.get('content', '')}[/]")

    elif event_type == "case_start":
        idx = event.get("case_index", 0)
        total = event.get("total_cases", "?")
        name = event.get("case_name", "")
        console.print(f"\n[bold][{idx + 1}/{total}] {name}[/]")

    elif event_type == "log":
        stream = event.get("stream", "stdout")
        content = event.get("content", "")
        # Truncate long log lines for display
        display = content[:200] + "..." if len(content) > 200 else content
        display = display.rstrip("\n")
        if display:
            if stream == "stderr":
                console.print(f"  [dim red]{display}[/]")
            else:
                console.print(f"  [dim]{display}[/]")

    elif event_type == "judge_start":
        console.print("  [dim]Judging with LLM...[/]")

    elif event_type == "case_result":
        verdict = event.get("verdict", "")
        name = event.get("case_name", "")
        reasoning = event.get("reasoning", "")
        duration = event.get("duration_ms", 0) / 1000

        if verdict == "pass":
            console.print(f"  [green]PASS[/] ({duration:.1f}s)")
        elif verdict == "fail":
            console.print(f"  [red]FAIL[/] ({duration:.1f}s)")
            if reasoning:
                console.print(f"    [dim]{reasoning[:200]}[/]")
        else:
            console.print(f"  [red]{verdict.upper()}[/] ({duration:.1f}s)")
            if reasoning:
                console.print(f"    [dim]{reasoning[:200]}[/]")

    elif event_type == "report":
        passed = event.get("passed", 0)
        total = event.get("total", 0)
        duration = event.get("total_duration_ms", 0) / 1000
        status = event.get("status", "")

        console.print()
        if status == "completed":
            console.print(f"[green]Assessment complete: {passed}/{total} passed in {duration:.1f}s[/]")
        else:
            console.print(f"[red]Assessment done: {passed}/{total} passed in {duration:.1f}s[/]")


def uninstall_command(
    skill_ref: str = typer.Argument(help="Skill name (e.g. 'myorg/my-skill')"),
) -> None:
    """Remove a locally installed skill and its agent symlinks."""
    from dhub.core.install import uninstall_skill
    from dhub.core.validation import parse_skill_ref

    try:
        org_slug, skill_name = parse_skill_ref(skill_ref)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/]")
        raise typer.Exit(1) from None

    try:
        unlinked = uninstall_skill(org_slug, skill_name)
    except FileNotFoundError:
        console.print(f"[red]Error: Skill '{skill_ref}' is not installed.[/]")
        raise typer.Exit(1) from None

    console.print(f"[green]Uninstalled {org_slug}/{skill_name}[/]")
    if unlinked:
        console.print(f"[green]Removed symlinks from: {', '.join(unlinked)}[/]")


def visibility_command(
    skill_ref: str = typer.Argument(help="Skill reference (org/skill)"),
    visibility: str = typer.Argument(help="Visibility level: 'public' or 'org'"),
) -> None:
    """Change the visibility of a published skill."""
    from dhub.cli.config import build_headers, get_api_url, get_token, raise_for_status
    from dhub.core.validation import parse_skill_ref

    valid = {"public", "org"}
    if visibility not in valid:
        console.print(f"[red]Error: Visibility must be 'public' or 'org', got '{visibility}'.[/]")
        raise typer.Exit(1)

    try:
        org_slug, skill_name = parse_skill_ref(skill_ref)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/]")
        raise typer.Exit(1) from None

    api_url = get_api_url()
    headers = build_headers(get_token())

    with httpx.Client(timeout=60) as client:
        resp = client.put(
            f"{api_url}/v1/skills/{org_slug}/{skill_name}/visibility",
            headers=headers,
            json={"visibility": visibility},
        )
        if resp.status_code == 404:
            console.print(f"[red]Error: {resp.json().get('detail', 'Not found')}[/]")
            raise typer.Exit(1)
        if resp.status_code == 403:
            console.print("[red]Error: Only org owners and admins can change visibility.[/]")
            raise typer.Exit(1)
        if resp.status_code == 422:
            console.print(f"[red]Error: {resp.json().get('detail', 'Invalid visibility')}[/]")
            raise typer.Exit(1)
        raise_for_status(resp)

    from dhub.cli.output import is_json, print_json

    if is_json():
        print_json({"org": org_slug, "skill": skill_name, "visibility": visibility})
        return

    label = "org-private" if visibility == "org" else "public"
    console.print(f"[green]Visibility for {org_slug}/{skill_name} set to {label}.[/]")


# ---------------------------------------------------------------------------
# Frontend URL mapping
# ---------------------------------------------------------------------------

_FRONTEND_URLS: dict[str, str] = {
    "local": "http://localhost:5173",
    "dev": "https://hub-dev.decision.ai",
    "prod": "https://hub.decision.ai",
}


def _get_frontend_url() -> str:
    """Return the frontend URL for the current environment."""
    from dhub.cli.config import get_env

    env = get_env()
    return _FRONTEND_URLS.get(env, _FRONTEND_URLS["prod"])


# ---------------------------------------------------------------------------
# info command
# ---------------------------------------------------------------------------


def info_command(
    skill_ref: str = typer.Argument(help="Skill reference (e.g. 'myorg/my-skill')"),
) -> None:
    """Show detailed information about a published skill."""
    from dhub.cli.config import build_headers, get_api_url, get_optional_token, raise_for_status
    from dhub.core.validation import parse_skill_ref

    try:
        org_slug, skill_name = parse_skill_ref(skill_ref)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/]")
        raise typer.Exit(1) from None

    api_url = get_api_url()
    headers = build_headers(get_optional_token())

    # Fetch skill summary
    with httpx.Client(timeout=60) as client:
        resp = client.get(
            f"{api_url}/v1/skills/{org_slug}/{skill_name}/summary",
            headers=headers,
        )
        if resp.status_code == 404:
            console.print(f"[red]Error: Skill '{org_slug}/{skill_name}' not found.[/]")
            raise typer.Exit(1)
        raise_for_status(resp)
        summary = resp.json()

        # Fetch latest audit log entry (best-effort)
        audit_entry = None
        try:
            resp = client.get(
                f"{api_url}/v1/skills/{org_slug}/{skill_name}/audit-log",
                headers=headers,
                params={"page_size": 1},
            )
            if resp.status_code == 200:
                audit_data = resp.json()
                if audit_data.get("items"):
                    audit_entry = audit_data["items"][0]
        except httpx.HTTPError:
            console.print("[dim]  (could not fetch audit log)[/]")

        # Fetch eval report for latest version (best-effort)
        eval_report = None
        latest_version = summary.get("latest_version", "")
        if latest_version:
            try:
                resp = client.get(
                    f"{api_url}/v1/skills/{org_slug}/{skill_name}/eval-report",
                    headers=headers,
                    params={"semver": latest_version},
                )
                if resp.status_code == 200:
                    eval_report = resp.json()
            except httpx.HTTPError:
                console.print("[dim]  (could not fetch eval report)[/]")

    from dhub.cli.output import is_json, print_json

    if is_json():
        print_json({"summary": summary, "audit_log": audit_entry, "eval_report": eval_report})
        return

    _render_skill_info(org_slug, skill_name, summary, audit_entry, eval_report)


def _render_skill_info(
    org_slug: str,
    skill_name: str,
    summary: dict,
    audit_entry: dict | None,
    eval_report: dict | None,
) -> None:
    """Render a rich, well-formatted skill info panel."""
    frontend_url = _get_frontend_url()
    skill_url = f"{frontend_url}/skills/{org_slug}/{skill_name}"

    # ── Title ──
    console.print()
    console.print(f"[bold cyan]{org_slug}[/]/[bold green]{skill_name}[/]", highlight=False)
    console.print(f"[dim]{summary.get('description', '')}[/]")
    console.print()

    # ── Overview ──
    version = summary.get("latest_version", "-")
    updated = summary.get("updated_at", "-")
    author = summary.get("author", "-")
    downloads = summary.get("download_count", 0)
    category = summary.get("category", "") or "-"
    visibility = summary.get("visibility", "public")
    safety = summary.get("safety_rating", "-")

    vis_label = "[yellow]org-private[/]" if visibility == "org" else "[green]public[/]"

    overview_lines = [
        f"  [bold]Version:[/]     {version}",
        f"  [bold]Safety:[/]      {safety}",
        f"  [bold]Category:[/]    {category}",
        f"  [bold]Visibility:[/]  {vis_label}",
        f"  [bold]Author:[/]      {author}",
        f"  [bold]Downloads:[/]   {downloads:,}",
        f"  [bold]Updated:[/]     {updated}",
    ]
    console.print(Panel("\n".join(overview_lines), title="Overview", border_style="cyan"))

    # ── GitHub ──
    source_repo: str | None = summary.get("source_repo_url")
    if source_repo:
        stars = summary.get("github_stars")
        forks = summary.get("github_forks")
        license_name = summary.get("github_license")
        is_archived = summary.get("github_is_archived", False)
        is_synced = summary.get("is_auto_synced", False)

        gh_lines = [f"  [bold]Repository:[/]  [link={source_repo}]{source_repo}[/link]"]
        stats_parts = []
        if stars is not None:
            stats_parts.append(f"[yellow]★[/] {stars:,}")
        if forks is not None:
            stats_parts.append(f"⑂ {forks:,}")
        if stats_parts:
            gh_lines.append(f"  [bold]Stats:[/]       {' · '.join(stats_parts)}")
        if license_name:
            gh_lines.append(f"  [bold]License:[/]     {license_name}")
        if is_archived:
            gh_lines.append("  [bold]Status:[/]      [red]Archived[/]")
        if is_synced:
            gh_lines.append("  [bold]Auto-sync:[/]   [green]Enabled[/]")
        console.print(Panel("\n".join(gh_lines), title="GitHub", border_style="dim"))

    # ── Eval Results ──
    if eval_report:
        status = eval_report.get("status", "-")
        passed = eval_report.get("passed", 0)
        total = eval_report.get("total", 0)
        agent = eval_report.get("agent", "-")
        duration_ms = eval_report.get("total_duration_ms", 0)
        duration_s = duration_ms / 1000

        status_colors = {"completed": "green", "failed": "red", "error": "red", "pending": "yellow"}
        status_color = status_colors.get(status, "white")
        result_color = "green" if passed == total else "red" if passed == 0 else "yellow"

        eval_lines = [
            f"  [bold]Agent:[/]     {agent}",
            f"  [bold]Status:[/]    [{status_color}]{status.upper()}[/]",
            f"  [bold]Results:[/]   [{result_color}]{passed}/{total} passed[/]",
            f"  [bold]Duration:[/]  {duration_s:.1f}s",
        ]

        # Show individual case results
        case_results = eval_report.get("case_results", [])
        if case_results:
            eval_lines.append("")
            for case in case_results:
                verdict = case.get("verdict", "-")
                name = case.get("name", "-")
                v_color = "green" if verdict == "pass" else "red"
                eval_lines.append(f"    [{v_color}]{'✓' if verdict == 'pass' else '✗'}[/] {name}")

        console.print(Panel("\n".join(eval_lines), title="Eval Results", border_style="blue"))
    else:
        console.print(Panel("  [dim]No eval report available[/]", title="Eval Results", border_style="dim"))

    # ── Latest Audit Log ──
    if audit_entry:
        grade = audit_entry.get("grade", "-")
        semver = audit_entry.get("semver", "-")
        publisher = audit_entry.get("publisher", "-")
        audit_date = audit_entry.get("created_at", "-")
        if audit_date and audit_date != "-":
            audit_date = audit_date[:19].replace("T", " ")

        grade_colors = {"A": "green", "B": "cyan", "C": "yellow", "F": "red"}
        grade_color = grade_colors.get(grade, "white")

        audit_lines = [
            f"  [bold]Grade:[/]      [{grade_color}]{grade}[/]",
            f"  [bold]Version:[/]    {semver}",
            f"  [bold]Publisher:[/]  {publisher}",
            f"  [bold]Date:[/]       {audit_date}",
        ]

        checks = audit_entry.get("check_results", [])
        if checks:
            audit_lines.append("")
            for check in checks:
                sev = check.get("severity", "-")
                name = check.get("check_name", "-")
                sev_color = "green" if sev == "pass" else ("yellow" if sev == "warn" else "red")
                icon = "✓" if sev == "pass" else ("⚠" if sev == "warn" else "✗")
                audit_lines.append(f"    [{sev_color}]{icon}[/] {name}")

        console.print(Panel("\n".join(audit_lines), title="Latest Audit", border_style="magenta"))

    # ── Links ──
    console.print()
    console.print(f"  [bold]Hub page:[/]  [link={skill_url}]{skill_url}[/link]")
    if source_repo:
        console.print(f"  [bold]GitHub:[/]    [link={source_repo}]{source_repo}[/link]")
    console.print()
