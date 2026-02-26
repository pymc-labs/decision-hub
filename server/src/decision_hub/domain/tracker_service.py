"""Tracker processing orchestrator.

Discovers skills in tracked repos and republishes them through the
full publish pipeline (zip, gauntlet, S3, version record, eval trigger).
"""

from __future__ import annotations

import dataclasses
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from decision_hub.models import SkillTracker, TrackerBatchResult
from decision_hub.settings import Settings

# How close to the deadline we stop accepting new work.  Used by both the
# outer loop in modal_app.py (via check_all_due_trackers) and the dispatch
# function to avoid overrunning the hard Modal timeout.
DEADLINE_BUFFER_SECONDS = 30

# ---------------------------------------------------------------------------
# Serialization helpers for Modal transport
# ---------------------------------------------------------------------------


def tracker_to_dict(tracker: SkillTracker) -> dict[str, Any]:
    """Serialize a frozen SkillTracker dataclass to a plain dict for Modal transport.

    UUID and datetime fields are converted to strings so the dict is JSON-safe.
    """
    d = dataclasses.asdict(tracker)
    for key, value in d.items():
        if isinstance(value, datetime):
            d[key] = value.isoformat()
        elif hasattr(value, "hex"):
            # UUID → string
            d[key] = str(value)
    return d


def dict_to_tracker(d: dict[str, Any]) -> SkillTracker:
    """Deserialize a plain dict back to a SkillTracker dataclass.

    Reverses the string conversions from tracker_to_dict.
    """
    from uuid import UUID

    copy = dict(d)
    copy["id"] = UUID(copy["id"])
    copy["user_id"] = UUID(copy["user_id"])
    for dt_field in ("last_checked_at", "last_published_at", "next_check_at", "created_at"):
        if copy.get(dt_field) is not None:
            copy[dt_field] = datetime.fromisoformat(copy[dt_field])
    return SkillTracker(**copy)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def check_all_due_trackers(settings: Settings, *, deadline: float | None = None) -> TrackerBatchResult:
    """Find all due trackers and process them. Returns structured metrics.

    The caller loop in ``check_trackers`` breaks when ``result.checked == 0``,
    meaning no more trackers are due. Returning ``checked=len(trackers)``
    instead of the changed count ensures the loop keeps going through
    subsequent batches even when one batch has zero changes.

    Uses batch GraphQL to check all claimed trackers for new commits in a
    single API call (per 250 repos), then only clones + republishes those
    that actually changed. Changed trackers are processed via Modal fan-out
    when available, falling back to sequential processing for local dev.

    Deduplicates repos so that N trackers pointing at the same
    ``(owner, repo, branch)`` produce only 1 GraphQL alias. DB writes
    are batched (one UPDATE per category) instead of N+1 per-tracker commits.
    """
    from decision_hub.infra.database import (
        batch_clear_tracker_errors,
        batch_defer_trackers,
        batch_disable_trackers,
        batch_set_tracker_errors,
        batch_update_github_repo_metadata,
        batch_update_github_stars,
        claim_due_trackers,
        create_engine,
        mark_skills_source_removed,
    )
    from decision_hub.infra.github_client import GitHubClient, batch_fetch_commit_shas

    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        trackers = claim_due_trackers(
            conn,
            batch_size=settings.tracker_batch_size,
            jitter_seconds=settings.tracker_jitter_seconds,
        )
        conn.commit()

    if not trackers:
        logger.info("tracker_batch due=0 checked=0 changed=0 failed=0")
        return TrackerBatchResult(
            checked=0,
            due=0,
            unchanged=0,
            changed=0,
            errored=0,
            processed=0,
            failed=0,
            skipped_rate_limit=0,
            deadline_deferred=0,
            github_rate_remaining=None,
        )

    # Build reverse index for deduplication: repo_key -> [tracker, ...]
    repo_key_to_trackers: dict[str, list[SkillTracker]] = {}
    for tracker in trackers:
        owner, repo = parse_github_repo_url(tracker.repo_url)
        key = f"{owner}/{repo}:{tracker.branch}"
        repo_key_to_trackers.setdefault(key, []).append(tracker)

    # Deduplicated repo list for GraphQL
    unique_repos: list[tuple[str, str, str]] = []
    for key in repo_key_to_trackers:
        owner_repo, branch = key.rsplit(":", 1)
        owner, repo = owner_repo.split("/", 1)
        unique_repos.append((owner, repo, branch))

    # Batch-fetch latest commit SHAs and star counts via GraphQL
    github_token = _resolve_github_token(settings)
    with GitHubClient(token=github_token) as gh:
        sha_map, failed_chunk_keys, stars_map, repo_metadata_map = batch_fetch_commit_shas(gh, unique_repos)
        rate_remaining = gh.rate_limit_remaining

    # Classify trackers with transient awareness
    unchanged_ids: list = []
    errored_ids_transient: list = []
    errored_ids_permanent: list = []
    changed_trackers: list[tuple[SkillTracker, str]] = []

    for key, key_trackers in repo_key_to_trackers.items():
        if key in failed_chunk_keys:
            # Entire GraphQL chunk failed — transient error, will retry
            errored_ids_transient.extend(t.id for t in key_trackers)
            continue

        current_sha = sha_map.get(key)
        if current_sha is None:
            # Repo resolved but returned no data — permanent error
            errored_ids_permanent.extend(t.id for t in key_trackers)
            continue

        for t in key_trackers:
            if current_sha == t.last_commit_sha:
                unchanged_ids.append(t.id)
            else:
                changed_trackers.append((t, current_sha))

    errored = len(errored_ids_transient) + len(errored_ids_permanent)
    unchanged = len(unchanged_ids)

    # Batch DB writes — one UPDATE per category, single commit
    with engine.connect() as conn:
        batch_clear_tracker_errors(conn, unchanged_ids)
        batch_set_tracker_errors(conn, errored_ids_permanent, "GraphQL: repo not found or inaccessible")
        batch_set_tracker_errors(conn, errored_ids_transient, "transient: GraphQL chunk failed, will retry")
        # Auto-disable permanent errors and mark their skills as removed
        if errored_ids_permanent:
            batch_disable_trackers(conn, errored_ids_permanent)
            removed_urls = list(
                {
                    t.repo_url
                    for key, kts in repo_key_to_trackers.items()
                    if key not in failed_chunk_keys and sha_map.get(key) is None
                    for t in kts
                }
            )
            mark_skills_source_removed(conn, removed_urls)
            logger.info(
                "auto_disabled {} permanent-error trackers, marked {} repo URLs as removed",
                len(errored_ids_permanent),
                len(removed_urls),
            )
        conn.commit()

    # Update github_stars on skills whose source_repo_url matches the tracked repos.
    # This runs every tick for all resolved repos — star counts change independently
    # of code commits. Uses a separate transaction so failures don't block tracking.
    if stars_map:
        try:
            repo_stars = {f"https://github.com/{owner_repo}": count for owner_repo, count in stars_map.items()}
            with engine.connect() as conn:
                batch_update_github_stars(conn, repo_stars)
                conn.commit()
            logger.debug("Updated github_stars for {} repos", len(repo_stars))
        except Exception:
            logger.opt(exception=True).warning("Failed to update github_stars (non-critical)")

    if repo_metadata_map:
        try:
            repo_meta = {f"https://github.com/{owner_repo}": meta for owner_repo, meta in repo_metadata_map.items()}
            with engine.connect() as conn:
                batch_update_github_repo_metadata(conn, repo_meta)
                conn.commit()
            logger.debug("Updated github repo metadata for {} repos", len(repo_meta))
        except Exception:
            logger.opt(exception=True).warning("Failed to update github repo metadata (non-critical)")

    # Rate-limit budget guardrail: skip clone+publish if GitHub budget is low.
    # Changed trackers that aren't processed will be picked up next tick
    # (their next_check_at was already bumped by claim_due_trackers).
    if rate_remaining < settings.tracker_rate_limit_floor:
        logger.warning(
            "GitHub rate limit low ({} < {}), skipping processing of {} changed trackers",
            rate_remaining,
            settings.tracker_rate_limit_floor,
            len(changed_trackers),
        )
        # Mark skipped trackers so they don't appear stuck (no SHA, no error).
        # Clear next_check_at so they're immediately due on the next tick
        # rather than waiting the full poll interval.
        deferred_ids = [t.id for t, _ in changed_trackers]
        with engine.connect() as conn:
            batch_defer_trackers(conn, deferred_ids, "rate_limit: deferred to next tick")
            conn.commit()
        logger.info(
            "tracker_batch due={} unchanged={} changed={} errored={} processed=0 failed=0 skipped_rate_limit={}",
            len(trackers),
            unchanged,
            len(changed_trackers),
            errored,
            len(changed_trackers),
        )
        return TrackerBatchResult(
            checked=len(trackers),
            due=len(trackers),
            unchanged=unchanged,
            changed=len(changed_trackers),
            errored=errored,
            processed=0,
            failed=0,
            skipped_rate_limit=len(changed_trackers),
            deadline_deferred=0,
            github_rate_remaining=rate_remaining,
        )

    # Time-budget guardrail: fn.map() blocks the thread while waiting for
    # tracker_process_repo results (up to 300s timeout + cold start).  If the
    # deadline is too close, dispatching would risk hitting the hard Modal
    # timeout.  Defer changed trackers so they're immediately due next tick.
    _MIN_DISPATCH_BUDGET_SECONDS = 60
    if deadline is not None and changed_trackers:
        remaining = deadline - time.monotonic()
        if remaining < _MIN_DISPATCH_BUDGET_SECONDS:
            logger.warning(
                "Insufficient time budget ({:.0f}s < {}s) for dispatch, deferring {} changed trackers",
                remaining,
                _MIN_DISPATCH_BUDGET_SECONDS,
                len(changed_trackers),
            )
            deferred_ids = [t.id for t, _ in changed_trackers]
            with engine.connect() as conn:
                batch_defer_trackers(conn, deferred_ids, "deadline: deferred to next tick")
                conn.commit()
            return TrackerBatchResult(
                checked=len(trackers),
                due=len(trackers),
                unchanged=unchanged,
                changed=len(changed_trackers),
                errored=errored,
                processed=0,
                failed=0,
                skipped_rate_limit=0,
                deadline_deferred=len(changed_trackers),
                github_rate_remaining=rate_remaining,
            )

    # Dispatch changed trackers (Modal fan-out with sequential fallback)
    processed, failed = _dispatch_changed_trackers(changed_trackers, settings, engine, deadline=deadline)

    logger.info(
        "tracker_batch due={} unchanged={} changed={} errored={} processed={} failed={}",
        len(trackers),
        unchanged,
        len(changed_trackers),
        errored,
        processed,
        failed,
    )
    return TrackerBatchResult(
        checked=len(trackers),
        due=len(trackers),
        unchanged=unchanged,
        changed=len(changed_trackers),
        errored=errored,
        processed=processed,
        failed=failed,
        skipped_rate_limit=0,
        deadline_deferred=0,
        github_rate_remaining=rate_remaining,
    )


def _dispatch_changed_trackers(
    changed_trackers: list[tuple[SkillTracker, str]],
    settings: Settings,
    engine: Any,
    *,
    deadline: float | None = None,
) -> tuple[int, int]:
    """Fan out processing of changed trackers via Modal, with sequential fallback.

    Returns (processed_count, failed_count).
    Each Modal container mints its own GitHub App token from environment
    credentials, so no token passthrough is needed.

    Uses ``fn.map()`` (blocking) instead of ``fn.spawn()`` (fire-and-forget)
    deliberately — fn.map gives us real processed/failed counts for
    tracker_metrics, catches silent container failures (OOM, timeout before
    DB write), and makes errors visible in orchestrator logs.  The downside
    is that fn.map blocks the thread; the caller guards against this with a
    reduced loop budget and a pre-dispatch deadline check so we never
    overrun the hard Modal timeout.

    When *deadline* is set (monotonic clock), the function will stop
    consuming ``fn.map`` results once the deadline is within 30 seconds,
    preventing the orchestrator from hitting the hard Modal timeout.
    Unprocessed trackers will be retried on the next tick.
    """
    processed = 0
    failed = 0

    try:
        import modal

        fn = modal.Function.from_name(settings.modal_app_name, "tracker_process_repo")
        tracker_dicts = [tracker_to_dict(t) for t, _ in changed_trackers]
        known_shas = [sha for _, sha in changed_trackers]

        # fn.map blocks until results arrive — see docstring for why this is
        # preferred over fn.spawn.  The deadline check below breaks early if
        # the budget runs low.
        for batch_result in fn.map(
            tracker_dicts,
            known_shas,
            return_exceptions=True,
            order_outputs=False,
        ):
            # Process the already-received result before checking the deadline —
            # the for-loop already blocked to receive it, so discarding it would
            # undercount processed/failed.
            if isinstance(batch_result, Exception):
                logger.opt(exception=batch_result).error("Modal tracker_process_repo failed")
                failed += 1
            else:
                if batch_result.get("status") == "ok":
                    processed += 1
                else:
                    failed += 1
                    logger.error(
                        "tracker_process_repo error: repo={} error={}",
                        batch_result.get("repo_url", "?"),
                        batch_result.get("error", "unknown"),
                    )

            if deadline is not None and time.monotonic() > deadline - DEADLINE_BUFFER_SECONDS:
                logger.warning(
                    "Deadline approaching, stopping fn.map consumption after {}/{} results",
                    processed + failed,
                    len(changed_trackers),
                )
                break
    except Exception as modal_err:
        # Modal unavailable (local dev, import error, lookup failure) — fall back to sequential
        logger.info("Modal fan-out unavailable ({}), falling back to sequential processing", modal_err)
        for tracker, known_sha in changed_trackers:
            if deadline is not None and time.monotonic() > deadline - DEADLINE_BUFFER_SECONDS:
                logger.warning("Deadline approaching, stopping sequential processing")
                break
            try:
                process_tracker(tracker, settings, engine, known_sha=known_sha)
                processed += 1
            except Exception:
                logger.opt(exception=True).error(
                    "tracker_id={} repo={} status=failed",
                    tracker.id,
                    tracker.repo_url,
                )
                failed += 1

    return processed, failed


# ---------------------------------------------------------------------------
# Remote entry point (runs inside Modal container)
# ---------------------------------------------------------------------------


def process_tracker_remote(
    tracker_dict: dict[str, Any],
    known_sha: str,
) -> dict[str, Any]:
    """Entry point for Modal containers — creates own settings+engine and processes one tracker.

    Each container has GitHub App credentials in its environment and mints
    its own installation token via ``_resolve_github_token()``.

    Returns a result dict with status, repo_url, and optional error.
    """
    from decision_hub.infra.database import create_engine
    from decision_hub.logging import setup_logging
    from decision_hub.settings import create_settings

    settings = create_settings()
    setup_logging(settings.log_level)

    tracker = dict_to_tracker(tracker_dict)
    engine = create_engine(settings.database_url)

    try:
        process_tracker(tracker, settings, engine, known_sha=known_sha)
        return {"status": "ok", "repo_url": tracker.repo_url, "tracker_id": str(tracker.id)}
    except Exception as e:
        logger.opt(exception=True).error(
            "tracker_id={} repo={} status=failed",
            tracker.id,
            tracker.repo_url,
        )
        return {"status": "error", "repo_url": tracker.repo_url, "tracker_id": str(tracker.id), "error": str(e)[:500]}


# ---------------------------------------------------------------------------
# Single tracker processing
# ---------------------------------------------------------------------------


def process_tracker(
    tracker: SkillTracker,
    settings: Settings,
    engine: Any,
    *,
    known_sha: str | None = None,
) -> None:
    """Check a single tracker for updates and republish if needed.

    This is the main entry point called by the scheduled function.
    On any error, updates last_error on the tracker row.

    When *known_sha* is provided (from batch GraphQL), skips the
    per-tracker REST commit check — the caller already determined
    that the repo has new commits.
    """
    from decision_hub.infra.database import update_skill_tracker
    from decision_hub.infra.storage import create_s3_client

    now = datetime.now(UTC)

    try:
        github_token = _resolve_github_token(settings)
        owner, repo = parse_github_repo_url(tracker.repo_url)

        if known_sha is not None:
            # Caller already verified new commits via batch GraphQL
            current_sha = known_sha
        else:
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
                    "tracker_id={} repo={}/{} status=checked",
                    tracker.id,
                    owner,
                    repo,
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
                        enabled=False,
                    )
                    conn.commit()
                logger.info(
                    "tracker_id={} repo={} status=disabled reason=no_skills_found",
                    tracker.id,
                    tracker.repo_url,
                )
                return

            s3_client = create_s3_client(
                region=settings.aws_region,
                access_key_id=settings.aws_access_key_id,
                secret_access_key=settings.aws_secret_access_key,
                endpoint_url=settings.s3_endpoint_url,
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
                        "tracker_id={} repo={} skill={} status=publish_failed error={}",
                        tracker.id,
                        tracker.repo_url,
                        skill_dir.name,
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
                "tracker_id={} repo={}/{} status=changed published={} sha={}",
                tracker.id,
                owner,
                repo,
                published_count,
                current_sha[:8],
            )

        finally:
            shutil.rmtree(repo_root.parent, ignore_errors=True)

    except Exception as e:
        logger.opt(exception=True).error(
            "tracker_id={} repo={} status=failed",
            tracker.id,
            tracker.repo_url,
        )
        try:
            with engine.connect() as conn:
                update_skill_tracker(
                    conn,
                    tracker.id,
                    last_checked_at=now,
                    last_error=str(e)[:500],
                )
                conn.commit()
        except Exception:
            logger.opt(exception=True).error(
                "tracker_id={} repo={} status=error_update_failed",
                tracker.id,
                tracker.repo_url,
            )


def _publish_skill_from_tracker(
    skill_dir: Path,
    org_slug: str,
    tracker: SkillTracker,
    settings: Settings,
    engine: Any,
    s3_client: Any,
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
        quarantine_and_log_rejection,
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
            logger.info(
                "tracker_id={} repo={} skill={}/{} status=unchanged", tracker.id, tracker.repo_url, org_slug, skill_name
            )
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
        skill_md_content, source_files, lockfile_content = extract_for_evaluation(zip_data)
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
        )

        if not report.passed:
            logger.warning(
                "tracker_id={} repo={} skill={}/{}@{} status=rejected grade={}",
                tracker.id,
                tracker.repo_url,
                org_slug,
                skill_name,
                version,
                report.grade,
            )
            quarantine_and_log_rejection(
                conn,
                s3_client,
                settings.s3_bucket,
                zip_data,
                org_slug=org_slug,
                skill_name=skill_name,
                version=version,
                report=report,
                check_results=check_results_dicts,
                llm_reasoning=llm_reasoning,
                publisher=f"tracker:{tracker.id}",
            )
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
        logger.warning(
            "tracker_id={} repo={} skill={}/{} status=eval_trigger_failed error={}",
            tracker.id,
            tracker.repo_url,
            org_slug,
            skill_name,
            e,
        )

    logger.info(
        "tracker_id={} repo={} skill={}/{}@{} status=published grade={}",
        tracker.id,
        tracker.repo_url,
        org_slug,
        skill_name,
        version,
        report.grade,
    )
    return True


def _resolve_github_token(settings: Settings) -> str:
    """Mint a GitHub App installation token for tracker polling.

    Uses the GitHub App credentials from settings to mint a short-lived
    installation token (~1 hr). Each cron tick / Modal container mints
    its own token, so there's no token-sharing across containers.

    Raises if App credentials are not configured.
    """
    from decision_hub.infra.github_app_token import mint_installation_token

    if not (settings.github_app_id and settings.github_app_private_key and settings.github_app_installation_id):
        raise RuntimeError(
            "GitHub App credentials not configured. "
            "Set GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY, and GITHUB_APP_INSTALLATION_ID."
        )
    return mint_installation_token(
        settings.github_app_id,
        settings.github_app_private_key,
        settings.github_app_installation_id,
    )
