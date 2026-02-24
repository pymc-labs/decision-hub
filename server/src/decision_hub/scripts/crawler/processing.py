"""Modal container processing logic for the GitHub skills crawler.

Each Modal container processes exactly one repo: clone, discover skills,
run gauntlet, publish or quarantine. No shared state between containers.
"""

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
from loguru import logger

from decision_hub.domain.orgs import METADATA_CACHE_TTL
from decision_hub.domain.publish import (
    build_quarantine_s3_key,
    build_s3_key,
    extract_for_evaluation,
    validate_skill_name,
)
from decision_hub.domain.repo_utils import (
    bump_version,
    clone_repo,
    create_zip,
    discover_skills,
)
from decision_hub.domain.skill_manifest import extract_body, extract_description

CLONE_TIMEOUT_SECONDS = 120
BOT_GITHUB_ID = "0"
BOT_USERNAME = "dhub-crawler"
_SLUG_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")


def fetch_owner_metadata(
    login: str,
    owner_type: str,
    token: str | None = None,
) -> dict:
    """Fetch public metadata for a GitHub user/org. Works inside Modal containers.

    Returns a dict with keys: avatar_url, email, description, blog.
    On error returns an empty dict.
    """
    headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    endpoint = (
        f"https://api.github.com/orgs/{login}"
        if owner_type == "Organization"
        else f"https://api.github.com/users/{login}"
    )
    try:
        resp = httpx.get(endpoint, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            # GitHub users have "bio" instead of "description"
            description = data.get("description") if owner_type == "Organization" else data.get("bio")
            return {
                "avatar_url": data.get("avatar_url") or None,
                "email": data.get("email") or None,
                "description": description or None,
                "blog": data.get("blog") or None,
            }
    except httpx.HTTPError:
        return {}
    return {}


def process_repo_on_modal(
    repo_dict: dict,
    bot_user_id_str: str,
    github_token: str | None,
    set_tracker: bool = True,
) -> dict:
    """Process a single repo inside a Modal container.

    Clones the repo, discovers SKILL.md files, runs the gauntlet pipeline,
    and publishes or quarantines each skill.
    """
    import subprocess

    from decision_hub.infra.database import (
        create_engine,
        find_org_by_slug,
        find_org_member,
        insert_org_member,
        insert_organization,
        update_org_github_metadata,
        upsert_user,
    )
    from decision_hub.infra.storage import (
        create_s3_client,
    )
    from decision_hub.settings import create_settings

    result: dict = {
        "repo": repo_dict["full_name"],
        "status": "ok",
        "commit_sha": None,
        "skills_published": 0,
        "skills_skipped": 0,
        "skills_failed": 0,
        "skills_quarantined": 0,
        "org_created": False,
        "metadata_synced": False,
        "error": None,
    }

    try:
        settings = create_settings()
        engine = create_engine(settings.database_url)
        s3_client = create_s3_client(
            region=settings.aws_region,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
        )

        slug = repo_dict["owner_login"].lower()
        if not _SLUG_PATTERN.match(slug):
            result["status"] = "skipped"
            result["error"] = f"Invalid org slug: {slug}"
            return result

        bot_user_id = UUID(bot_user_id_str)

        # Ensure org exists and bot is a member (short-lived transaction)
        with engine.connect() as conn:
            upsert_user(conn, github_id=BOT_GITHUB_ID, username=BOT_USERNAME)

            org = find_org_by_slug(conn, slug)
            if org is None:
                is_personal = repo_dict["owner_type"] == "User"
                org = insert_organization(conn, slug, bot_user_id, is_personal=is_personal)
                insert_org_member(conn, org.id, bot_user_id, "owner")
                result["org_created"] = True
            else:
                existing = find_org_member(conn, org.id, bot_user_id)
                if existing is None:
                    insert_org_member(conn, org.id, bot_user_id, "admin")

            conn.commit()

        # Sync GitHub metadata outside the DB transaction to avoid
        # holding a connection during the HTTP call (up to 15s timeout).
        # Best-effort: failures must not block skill publishing.
        try:
            needs_sync = org.github_synced_at is None or (datetime.now(UTC) - org.github_synced_at) > METADATA_CACHE_TTL
            if needs_sync:
                meta = fetch_owner_metadata(
                    repo_dict["owner_login"],
                    repo_dict["owner_type"],
                    github_token,
                )
                if meta:
                    with engine.connect() as conn:
                        update_org_github_metadata(
                            conn,
                            org.id,
                            avatar_url=meta.get("avatar_url"),
                            email=meta.get("email"),
                            description=meta.get("description"),
                            blog=meta.get("blog"),
                        )
                        conn.commit()
                    result["metadata_synced"] = True
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to sync GitHub metadata for {}; continuing with skill publishing",
                repo_dict["owner_login"],
            )

        # Clone and discover
        repo_root = clone_repo(
            repo_dict["clone_url"],
            github_token=github_token,
            timeout=CLONE_TIMEOUT_SECONDS,
        )
        tmp_dir = repo_root.parent

        # Capture commit SHA for checkpoint change-detection
        sha_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if sha_proc.returncode == 0:
            result["commit_sha"] = sha_proc.stdout.strip()

        try:
            skill_dirs = discover_skills(repo_root)
            if not skill_dirs:
                result["status"] = "no_skills"
                return result

            source_repo_url = f"https://github.com/{repo_dict['full_name']}"
            with engine.connect() as conn:
                for skill_dir in skill_dirs:
                    try:
                        _publish_one_skill(
                            conn,
                            s3_client,
                            settings,
                            org,
                            skill_dir,
                            result,
                            source_repo_url=source_repo_url,
                            bot_user_id=bot_user_id,
                            set_tracker=set_tracker,
                        )
                        conn.commit()
                    except Exception:
                        result["skills_failed"] += 1
                        conn.rollback()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    except subprocess.TimeoutExpired:
        result["status"] = "error"
        result["error"] = f"git clone timed out after {CLONE_TIMEOUT_SECONDS}s"
    except subprocess.CalledProcessError as exc:
        result["status"] = "error"
        result["error"] = f"git clone failed: {exc.stderr[:200] if exc.stderr else str(exc)}"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)[:500]

    return result


def _publish_one_skill(
    conn,
    s3_client,
    settings,
    org,
    skill_dir: Path,
    result: dict,
    *,
    source_repo_url: str | None = None,
    bot_user_id: UUID | None = None,
    set_tracker: bool = False,
) -> None:
    """Parse, gauntlet-check, and publish a single skill. Mutates result counts."""
    from decision_hub.api.registry_service import classify_skill_category, run_gauntlet_pipeline
    from decision_hub.infra.database import (
        find_skill,
        find_version,
        insert_audit_log,
        insert_skill,
        insert_version,
        resolve_latest_version,
        update_skill_category,
        update_skill_description,
        update_skill_source_repo_url,
    )
    from decision_hub.infra.storage import compute_checksum, upload_skill_zip
    from dhub_core.manifest import parse_skill_md

    manifest = parse_skill_md(skill_dir / "SKILL.md")
    name = manifest.name
    description = manifest.description
    validate_skill_name(name)

    # Create zip
    zip_data = create_zip(skill_dir)
    checksum = compute_checksum(zip_data)

    # Upsert skill record
    skill = find_skill(conn, org.id, name)
    if skill is None:
        skill = insert_skill(conn, org.id, name, description, source_repo_url=source_repo_url)
    else:
        update_skill_description(conn, skill.id, description)
        if source_repo_url and skill.source_repo_url != source_repo_url:
            update_skill_source_repo_url(conn, skill.id, source_repo_url)

    # Determine version (auto-bump patch or start at 0.1.0)
    latest = resolve_latest_version(conn, org.slug, name)
    if latest is not None:
        if latest.checksum == checksum:
            result["skills_skipped"] += 1
            return  # identical content — skip
        version = bump_version(latest.semver)
    else:
        version = "0.1.0"

    if find_version(conn, skill.id, version) is not None:
        result["skills_skipped"] += 1
        return

    # Extract content for gauntlet evaluation
    skill_md_content = (skill_dir / "SKILL.md").read_text()
    skill_md_body = extract_body(skill_md_content)
    desc = extract_description(skill_md_content)
    try:
        _, source_files, lockfile_content = extract_for_evaluation(zip_data)
    except ValueError as exc:
        logger.warning("Skipping {}/{}: extraction failed: {}", org.slug, name, exc)
        result["skills_failed"] += 1
        return

    # Run Gauntlet
    report, check_results, llm_reasoning = run_gauntlet_pipeline(
        skill_md_content,
        lockfile_content,
        source_files,
        name,
        desc,
        skill_md_body,
        settings,
        allowed_tools=manifest.allowed_tools,
    )

    if not report.passed:
        # Grade F — quarantine
        q_key = build_quarantine_s3_key(org.slug, name, version)
        insert_audit_log(
            conn,
            org_slug=org.slug,
            skill_name=name,
            semver=version,
            grade=report.grade,
            check_results=check_results,
            publisher=BOT_USERNAME,
            version_id=None,
            llm_reasoning=llm_reasoning,
            quarantine_s3_key=q_key,
        )
        conn.commit()
        upload_skill_zip(s3_client, settings.s3_bucket, q_key, zip_data)
        result["skills_quarantined"] += 1
        return

    # Grade A/B/C — publish
    # Classify category (non-critical, graceful fallback to empty string)
    category = classify_skill_category(name, desc, skill_md_body, settings)
    update_skill_category(conn, skill.id, category)

    # Generate embedding only for approved skills (fail-open: never blocks publish)
    from decision_hub.infra.embeddings import generate_and_store_skill_embedding

    generate_and_store_skill_embedding(conn, skill.id, name, org.slug, category, description, settings)

    s3_key = build_s3_key(org.slug, name, version)
    upload_skill_zip(s3_client, settings.s3_bucket, s3_key, zip_data)
    version_record = insert_version(
        conn,
        skill_id=skill.id,
        semver=version,
        s3_key=s3_key,
        checksum=checksum,
        runtime_config=None,
        published_by=BOT_USERNAME,
        eval_status=report.grade,
    )
    insert_audit_log(
        conn,
        org_slug=org.slug,
        skill_name=name,
        semver=version,
        grade=report.grade,
        check_results=check_results,
        publisher=BOT_USERNAME,
        version_id=version_record.id,
        llm_reasoning=llm_reasoning,
        quarantine_s3_key=None,
    )
    result["skills_published"] += 1

    if set_tracker and source_repo_url and bot_user_id is not None:
        from decision_hub.infra.database import upsert_skill_tracker

        upsert_skill_tracker(conn, bot_user_id, org.slug, source_repo_url)
