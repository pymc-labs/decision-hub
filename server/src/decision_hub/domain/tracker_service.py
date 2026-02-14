"""Tracker processing orchestrator.

Discovers skills in tracked repos and republishes them through the
full publish pipeline (zip, gauntlet, S3, version record, eval trigger).
"""

import shutil
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from decision_hub.domain.publish import build_s3_key, extract_for_evaluation, validate_skill_name
from decision_hub.domain.repo_utils import (
    bump_version,
    clone_repo,
    create_zip,
    discover_skills,
    parse_semver,
)
from decision_hub.domain.skill_manifest import extract_body, extract_description
from decision_hub.domain.tracker import has_new_commits, parse_github_repo_url
from decision_hub.models import SkillTracker
from decision_hub.settings import Settings


def check_all_due_trackers(settings: Settings) -> int:
    """Find all due trackers and process them. Returns count of trackers processed."""
    from decision_hub.infra.database import claim_due_trackers, create_engine

    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        trackers = claim_due_trackers(conn, batch_size=settings.tracker_batch_size)
        conn.commit()

    logger.info("Found {} due tracker(s)", len(trackers))

    processed = 0
    for tracker in trackers:
        try:
            process_tracker(tracker, settings, engine)
            processed += 1
        except Exception as e:
            logger.error("Tracker {} failed: {}", tracker.id, e)

    return processed


def process_tracker(tracker: SkillTracker, settings: Settings, engine) -> None:
    """Check a single tracker for updates and republish if needed.

    This is the main entry point called by the scheduled function.
    On any error, updates last_error on the tracker row.
    """
    from decision_hub.infra.database import update_skill_tracker
    from decision_hub.infra.storage import create_s3_client

    now = datetime.now(UTC)

    try:
        github_token = _resolve_github_token(engine, tracker, settings)
        owner, repo = parse_github_repo_url(tracker.repo_url)
        changed, current_sha = has_new_commits(
            owner,
            repo,
            tracker.branch,
            tracker.last_commit_sha,
            github_token=github_token,
        )

        if not changed:
            with engine.connect() as conn:
                update_skill_tracker(
                    conn,
                    tracker.id,
                    last_checked_at=now,
                    last_error=None,
                )
                conn.commit()
            logger.info(
                "Tracker {}: no changes on {}/{}@{}",
                tracker.id,
                owner,
                repo,
                tracker.branch,
            )
            return

        # Clone the repo at the target branch
        repo_root = clone_repo(tracker.repo_url, tracker.branch, github_token=github_token)

        try:
            skill_dirs = discover_skills(repo_root)
            if not skill_dirs:
                with engine.connect() as conn:
                    update_skill_tracker(
                        conn,
                        tracker.id,
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
            errors: list[str] = []
            for skill_dir in skill_dirs:
                try:
                    actually_published = _publish_skill_from_tracker(
                        skill_dir=skill_dir,
                        org_slug=tracker.org_slug,
                        tracker=tracker,
                        settings=settings,
                        engine=engine,
                        s3_client=s3_client,
                    )
                    if actually_published:
                        published_count += 1
                except Exception as e:
                    errors.append(f"{skill_dir.name}: {e}")
                    logger.warning(
                        "Tracker {}: failed to publish skill from {}: {}",
                        tracker.id,
                        skill_dir,
                        e,
                    )

            all_failed = published_count == 0 and len(errors) > 0
            with engine.connect() as conn:
                update_skill_tracker(
                    conn,
                    tracker.id,
                    # Don't advance SHA when all publishes failed so
                    # the commit is retried on the next check cycle.
                    last_commit_sha=current_sha if not all_failed else None,
                    last_checked_at=now,
                    last_published_at=now if published_count > 0 else None,
                    last_error="; ".join(errors)[:500] if all_failed else None,
                )
                conn.commit()

            logger.info(
                "Tracker {}: published {} skill(s) from {}/{}@{} (sha={})",
                tracker.id,
                published_count,
                owner,
                repo,
                tracker.branch,
                current_sha[:8],
            )

        finally:
            shutil.rmtree(repo_root.parent, ignore_errors=True)

    except Exception as e:
        logger.error("Tracker {} failed: {}", tracker.id, e)
        try:
            with engine.connect() as conn:
                update_skill_tracker(
                    conn,
                    tracker.id,
                    last_checked_at=now,
                    last_error=str(e)[:500],
                )
                conn.commit()
        except Exception as inner:
            logger.error("Failed to update tracker {} error state: {}", tracker.id, inner)


def _publish_skill_from_tracker(
    skill_dir: Path,
    org_slug: str,
    tracker: SkillTracker,
    settings: Settings,
    engine,
    s3_client,
) -> bool:
    """Publish a single skill directory through the full pipeline.

    Mirrors the publish endpoint logic: zip -> extract -> gauntlet -> upload -> record.
    Skips republish if the zip checksum hasn't changed from the latest version.

    Returns True if a new version was actually published to S3,
    False if skipped (no content changes) or rejected by the gauntlet.
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

    zip_data = create_zip(skill_dir)
    checksum = compute_checksum(zip_data)

    with engine.connect() as conn:
        org = find_org_by_slug(conn, org_slug)
        if org is None:
            raise ValueError(f"Organization '{org_slug}' not found")

        # Check if latest version already has the same checksum (no changes)
        latest = resolve_latest_version(conn, org_slug, skill_name)
        if latest is not None and latest.checksum == checksum:
            logger.info("Tracker: no content changes for {}/{}, skipping", org_slug, skill_name)
            return False

        # Determine version: prefer manifest version_hint if present and higher
        manifest_version = manifest.runtime.version_hint if manifest.runtime else None
        if latest is None:
            version = manifest_version or "0.1.0"
        elif manifest_version and parse_semver(manifest_version) > parse_semver(latest.semver):
            version = manifest_version
        else:
            version = bump_version(latest.semver)

        # Extract evaluation files and parse manifest
        bundle = extract_for_evaluation(zip_data)
        skill_md_content = bundle.skill_md_content
        source_files = bundle.source_files
        lockfile_content = bundle.lockfile_content
        runtime_config_dict, eval_config, eval_cases, allowed_tools = parse_manifest_from_content(
            skill_md_content,
            zip_data,
        )
        description = extract_description(skill_md_content)
        skill_md_body = extract_body(skill_md_content)

        # Run gauntlet security checks
        report, check_results_dicts, llm_reasoning = run_gauntlet_pipeline(
            skill_md_content,
            lockfile_content,
            source_files,
            skill_name,
            description,
            skill_md_body,
            settings,
            allowed_tools=allowed_tools,
            # TODO: implement org verification — default to False (conservative)
            is_verified_org=False,
            zip_entries=bundle.zip_entries,
        )

        if not report.passed:
            logger.warning(
                "Tracker: gauntlet rejected {}/{}@{} (grade {})",
                org_slug,
                skill_name,
                version,
                report.grade,
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
            return False

        # Upsert skill record
        skill = find_skill(conn, org.id, skill_name)
        if skill is None:
            skill = insert_skill(conn, org.id, skill_name, description)
        else:
            update_skill_description(conn, skill.id, description)

        # Generate embedding (fail-open: never blocks publish)
        from decision_hub.infra.embeddings import generate_and_store_skill_embedding

        generate_and_store_skill_embedding(conn, skill.id, skill_name, org_slug, "", description, settings)

        # Check duplicate version
        if find_version(conn, skill.id, version) is not None:
            version = bump_version(version)

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
        logger.warning("Tracker: eval trigger failed for {}/{}: {}", org_slug, skill_name, e)

    logger.info(
        "Tracker: published {}/{}@{} (grade {})",
        org_slug,
        skill_name,
        version,
        report.grade,
    )
    return True


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
