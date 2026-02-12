"""Modal container processing logic for the GitHub skills crawler.

Each Modal container processes exactly one repo: clone, discover skills,
run gauntlet, publish or quarantine. No shared state between containers.
"""

import re
import shutil
from pathlib import Path
from uuid import UUID

import httpx

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


def fetch_owner_email(
    login: str,
    owner_type: str,
    token: str | None = None,
) -> str | None:
    """Fetch public email for a GitHub user/org. Works inside Modal containers."""
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
            email = resp.json().get("email")
            return email if email else None
    except httpx.HTTPError:
        return None
    return None


def process_repo_on_modal(
    repo_dict: dict,
    bot_user_id_str: str,
    github_token: str | None,
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
        update_org_email,
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
        "email_saved": False,
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

        # Fetch owner email
        email = fetch_owner_email(
            repo_dict["owner_login"],
            repo_dict["owner_type"],
            github_token,
        )

        with engine.connect() as conn:
            # Ensure bot user exists
            upsert_user(conn, github_id=BOT_GITHUB_ID, username=BOT_USERNAME)

            # Ensure org exists and bot is a member
            org = find_org_by_slug(conn, slug)
            if org is None:
                org = insert_organization(conn, slug, bot_user_id, is_personal=False)
                insert_org_member(conn, org.id, bot_user_id, "owner")
                result["org_created"] = True
            else:
                existing = find_org_member(conn, org.id, bot_user_id)
                if existing is None:
                    insert_org_member(conn, org.id, bot_user_id, "admin")

            if email and not org.email:
                update_org_email(conn, org.id, email)
                result["email_saved"] = True

            conn.commit()

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

                for skill_dir in skill_dirs:
                    try:
                        _publish_one_skill(
                            conn,
                            s3_client,
                            settings,
                            org,
                            skill_dir,
                            result,
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


def _publish_one_skill(conn, s3_client, settings, org, skill_dir: Path, result: dict) -> None:
    """Parse, gauntlet-check, and publish a single skill. Mutates result counts."""
    from decision_hub.api.registry_service import run_gauntlet_pipeline
    from decision_hub.infra.database import (
        find_skill,
        find_version,
        insert_audit_log,
        insert_skill,
        insert_version,
        resolve_latest_version,
        update_skill_description,
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
        skill = insert_skill(conn, org.id, name, description)
    else:
        update_skill_description(conn, skill.id, description)

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
    except ValueError:
        source_files = []
        lockfile_content = None

    # Run Gauntlet
    report, check_results, llm_reasoning = run_gauntlet_pipeline(
        skill_md_content,
        lockfile_content,
        source_files,
        name,
        desc,
        skill_md_body,
        settings,
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
