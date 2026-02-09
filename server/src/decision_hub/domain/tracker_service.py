"""Tracker service — orchestrates periodic GitHub polling and auto-republishing.

Runs server-side (in Modal scheduled function). Reuses the same gauntlet and
publish pipeline as the normal publish endpoint, but bypasses HTTP — calling
service functions directly.
"""

import io
import logging
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from decision_hub.domain.publish import (
    build_s3_key,
    extract_for_evaluation,
    validate_skill_name,
)
from decision_hub.domain.skill_manifest import extract_body, extract_description
from decision_hub.domain.tracker import has_new_commits, parse_github_repo_url
from decision_hub.models import SkillTracker
from decision_hub.settings import Settings

logger = logging.getLogger(__name__)


def process_tracker(tracker: SkillTracker, settings: Settings, engine) -> None:
    """Check a single tracker for updates and republish if needed.

    This is the main entry point called by the scheduled function.
    On any error, updates last_error on the tracker row.
    """
    from decision_hub.infra.database import (
        find_org_by_slug,
        find_skill,
        find_version,
        insert_audit_log,
        insert_skill,
        insert_version,
        resolve_latest_version,
        update_skill_description,
        update_skill_tracker,
    )
    from decision_hub.infra.storage import compute_checksum, create_s3_client, upload_skill_zip

    now = datetime.now(timezone.utc)
    github_token = _resolve_github_token(engine, tracker, settings)

    try:
        owner, repo = parse_github_repo_url(tracker.repo_url)
        changed, current_sha = has_new_commits(
            owner, repo, tracker.branch, tracker.last_commit_sha,
            github_token=github_token,
        )

        if not changed:
            with engine.connect() as conn:
                update_skill_tracker(
                    conn, tracker.id,
                    last_checked_at=now,
                    last_error=None,
                )
                conn.commit()
            logger.info(
                "Tracker %s: no changes on %s/%s@%s",
                tracker.id, owner, repo, tracker.branch,
            )
            return

        # Clone the repo at the target branch
        repo_root = _clone_repo(tracker.repo_url, tracker.branch, github_token=github_token)

        try:
            skill_dirs = _discover_skills(repo_root)
            if not skill_dirs:
                with engine.connect() as conn:
                    update_skill_tracker(
                        conn, tracker.id,
                        last_commit_sha=current_sha,
                        last_checked_at=now,
                        last_error="No skills found in repository",
                    )
                    conn.commit()
                return

            s3_client = create_s3_client(
                region=settings.aws_region,
                access_key_id=settings.aws_access_key_id,
                secret_access_key=settings.aws_secret_access_key,
            )

            published_count = 0
            for skill_dir in skill_dirs:
                try:
                    _publish_skill_from_tracker(
                        skill_dir=skill_dir,
                        org_slug=tracker.org_slug,
                        tracker=tracker,
                        settings=settings,
                        engine=engine,
                        s3_client=s3_client,
                    )
                    published_count += 1
                except Exception as e:
                    logger.warning(
                        "Tracker %s: failed to publish skill from %s: %s",
                        tracker.id, skill_dir, e,
                    )

            with engine.connect() as conn:
                update_skill_tracker(
                    conn, tracker.id,
                    last_commit_sha=current_sha,
                    last_checked_at=now,
                    last_published_at=now if published_count > 0 else None,
                    last_error=None,
                )
                conn.commit()

            logger.info(
                "Tracker %s: published %d skill(s) from %s/%s@%s (sha=%s)",
                tracker.id, published_count, owner, repo,
                tracker.branch, current_sha[:8],
            )

        finally:
            shutil.rmtree(repo_root.parent, ignore_errors=True)

    except Exception as e:
        logger.error("Tracker %s failed: %s", tracker.id, e)
        try:
            with engine.connect() as conn:
                update_skill_tracker(
                    conn, tracker.id,
                    last_checked_at=now,
                    last_error=str(e)[:500],
                )
                conn.commit()
        except Exception as inner:
            logger.error("Failed to update tracker %s error state: %s", tracker.id, inner)


def _clone_repo(repo_url: str, branch: str, *, github_token: str | None = None) -> Path:
    """Clone a git repo into a temp directory.

    When a github_token is provided, rewrites the URL to use HTTPS
    token authentication (supports private repos).
    """
    clone_url = repo_url
    if github_token:
        clone_url = _build_authenticated_url(repo_url, github_token)

    tmp_dir = Path(tempfile.mkdtemp(prefix="dhub-tracker-"))
    cmd = ["git", "clone", "--depth", "1", "--branch", branch, clone_url, str(tmp_dir / "repo")]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Sanitize token from error messages
        stderr = result.stderr.strip()
        if github_token:
            stderr = stderr.replace(github_token, "***")
        raise RuntimeError(f"git clone failed: {stderr}")
    return tmp_dir / "repo"


def _discover_skills(root: Path) -> list[Path]:
    """Find skill directories (containing SKILL.md) under a root path."""
    from decision_hub.domain.skill_manifest import parse_skill_md

    skill_dirs: list[Path] = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        parts = skill_md.relative_to(root).parts
        if any(p.startswith(".") or p in ("node_modules", "__pycache__") for p in parts):
            continue
        try:
            parse_skill_md(skill_md)
            skill_dirs.append(skill_md.parent)
        except (ValueError, FileNotFoundError):
            continue
    return skill_dirs


def _create_zip(path: Path) -> bytes:
    """Create an in-memory zip archive of a skill directory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(path.rglob("*")):
            if not file.is_file():
                continue
            relative = file.relative_to(path)
            parts = relative.parts
            if any(part.startswith(".") or part == "__pycache__" for part in parts):
                continue
            zf.write(file, relative)
    return buf.getvalue()


def _bump_version(current_semver: str) -> str:
    """Bump patch version of a semver string."""
    parts = current_semver.split(".")
    parts[2] = str(int(parts[2]) + 1)
    return ".".join(parts)


def _parse_semver(v: str) -> tuple[int, int, int]:
    """Parse a semver string into a comparable (major, minor, patch) tuple."""
    parts = v.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _resolve_github_token(engine, tracker: SkillTracker, settings: Settings) -> str | None:
    """Resolve the best available GitHub token for a tracker.

    Priority:
    1. User's stored GITHUB_TOKEN from user_api_keys (decrypted)
    2. System-wide settings.github_token fallback
    3. None if neither exists
    """
    from decision_hub.domain.crypto import decrypt_value
    from decision_hub.infra.database import get_api_keys_for_eval

    with engine.connect() as conn:
        keys = get_api_keys_for_eval(conn, tracker.user_id, ["GITHUB_TOKEN"])

    if "GITHUB_TOKEN" in keys:
        return decrypt_value(keys["GITHUB_TOKEN"], settings.fernet_key)

    if settings.github_token:
        return settings.github_token

    return None


def _build_authenticated_url(repo_url: str, token: str) -> str:
    """Rewrite a GitHub repo URL to use HTTPS token authentication.

    Handles both HTTPS and SSH URL formats.
    """
    owner, repo = parse_github_repo_url(repo_url)
    return f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"


def _publish_skill_from_tracker(
    skill_dir: Path,
    org_slug: str,
    tracker: SkillTracker,
    settings: Settings,
    engine,
    s3_client,
) -> None:
    """Publish a single skill directory through the full pipeline.

    Mirrors the publish endpoint logic: zip -> extract -> gauntlet -> upload -> record.
    Skips republish if the zip checksum hasn't changed from the latest version.
    """
    from decision_hub.api.registry_service import (
        maybe_trigger_agent_assessment,
        parse_manifest_from_content,
        run_gauntlet_pipeline,
    )
    from decision_hub.infra.database import (
        find_org_by_slug,
        find_skill,
        find_version,
        insert_audit_log,
        insert_skill,
        insert_version,
        resolve_latest_version,
        update_skill_description,
    )
    from decision_hub.infra.storage import compute_checksum, upload_skill_zip

    skill_md_path = skill_dir / "SKILL.md"
    from decision_hub.domain.skill_manifest import parse_skill_md
    manifest = parse_skill_md(skill_md_path)
    skill_name = manifest.name

    validate_skill_name(skill_name)

    zip_data = _create_zip(skill_dir)
    checksum = compute_checksum(zip_data)

    with engine.connect() as conn:
        org = find_org_by_slug(conn, org_slug)
        if org is None:
            raise ValueError(f"Organization '{org_slug}' not found")

        # Check if latest version already has the same checksum (no changes)
        latest = resolve_latest_version(conn, org_slug, skill_name)
        if latest is not None and latest.checksum == checksum:
            logger.info("Tracker: no content changes for %s/%s, skipping", org_slug, skill_name)
            return

        # Determine version: prefer manifest version if present and higher
        if latest is None:
            version = manifest.version or "0.1.0"
        elif manifest.version and _parse_semver(manifest.version) > _parse_semver(latest.semver):
            version = manifest.version
        else:
            version = _bump_version(latest.semver)

        # Extract evaluation files and parse manifest
        skill_md_content, source_files, lockfile_content = extract_for_evaluation(zip_data)
        runtime_config_dict, eval_config, eval_cases = parse_manifest_from_content(
            skill_md_content, zip_data,
        )
        description = extract_description(skill_md_content)
        skill_md_body = extract_body(skill_md_content)

        # Run gauntlet security checks
        report, check_results_dicts, llm_reasoning = run_gauntlet_pipeline(
            skill_md_content, lockfile_content, source_files,
            skill_name, description, skill_md_body, settings,
        )

        if not report.passed:
            logger.warning(
                "Tracker: gauntlet rejected %s/%s@%s (grade %s)",
                org_slug, skill_name, version, report.grade,
            )
            insert_audit_log(
                conn,
                org_slug=org_slug,
                skill_name=skill_name,
                semver=version,
                grade=report.grade,
                check_results=check_results_dicts,
                publisher=f"tracker:{tracker.id}",
                llm_reasoning=llm_reasoning,
            )
            conn.commit()
            return

        # Upsert skill record
        skill = find_skill(conn, org.id, skill_name)
        if skill is None:
            skill = insert_skill(conn, org.id, skill_name, description)
        else:
            update_skill_description(conn, skill.id, description)

        # Check duplicate version
        if find_version(conn, skill.id, version) is not None:
            version = _bump_version(version)

        # Upload to S3 and create version record
        s3_key = build_s3_key(org_slug, skill_name, version)
        upload_skill_zip(s3_client, settings.s3_bucket, s3_key, zip_data)

        version_record = insert_version(
            conn,
            skill_id=skill.id,
            semver=version,
            s3_key=s3_key,
            checksum=checksum,
            runtime_config=runtime_config_dict,
            published_by=f"tracker:{tracker.id}",
            eval_status=report.grade,
        )

        insert_audit_log(
            conn,
            org_slug=org_slug,
            skill_name=skill_name,
            semver=version,
            grade=report.grade,
            check_results=check_results_dicts,
            publisher=f"tracker:{tracker.id}",
            version_id=version_record.id,
            llm_reasoning=llm_reasoning,
        )

        conn.commit()

    # Trigger eval assessment if configured (uses its own connection)
    try:
        maybe_trigger_agent_assessment(
            eval_config=eval_config,
            eval_cases=eval_cases,
            s3_key=s3_key,
            s3_bucket=settings.s3_bucket,
            version_id=version_record.id,
            org_slug=org_slug,
            skill_name=skill_name,
            settings=settings,
            user_id=tracker.user_id,
        )
    except Exception as e:
        # Don't fail the whole publish if eval trigger fails
        logger.warning("Tracker: eval trigger failed for %s/%s: %s", org_slug, skill_name, e)

    logger.info(
        "Tracker: published %s/%s@%s (grade %s)",
        org_slug, skill_name, version, report.grade,
    )


def check_all_due_trackers(settings: Settings) -> int:
    """Find all due trackers and process them. Returns count of trackers processed."""
    from decision_hub.infra.database import claim_due_trackers, create_engine

    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        trackers = claim_due_trackers(conn)
        conn.commit()

    logger.info("Found %d due tracker(s)", len(trackers))

    processed = 0
    for tracker in trackers:
        try:
            process_tracker(tracker, settings, engine)
            processed += 1
        except Exception as e:
            logger.error("Tracker %s failed: %s", tracker.id, e)

    return processed
