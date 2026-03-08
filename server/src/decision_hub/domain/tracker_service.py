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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from decision_hub.infra.github_client import GitHubClient

from loguru import logger

from decision_hub.domain.publish import validate_skill_name
from decision_hub.domain.repo_utils import (
    bump_version,
    clone_repo,
    create_zip,
    discover_skills,
    parse_semver,
)
from decision_hub.domain.skill_manifest import parse_skill_md
from decision_hub.domain.tracker import has_new_commits, parse_github_repo_url
from decision_hub.models import SkillTracker, TrackerBatchResult
from decision_hub.settings import Settings

# How close to the deadline we stop accepting new work.  Used by both the
# outer loop in modal_app.py (via check_all_due_trackers) and the dispatch
# function to avoid overrunning the hard Modal timeout.
DEADLINE_BUFFER_SECONDS = 30


# ---------------------------------------------------------------------------
# REST verification helpers
# ---------------------------------------------------------------------------


def _verify_repos_removed(
    gh: GitHubClient,
    candidate_urls: list[str],
) -> list[str]:
    """Filter candidate URLs to only those confirmed deleted by REST API.

    GraphQL returning null for a repo does NOT reliably mean the repo is
    deleted — it can also mean renamed, transient outage, or permission gap.
    A REST GET returning 404 is a much stronger signal.
    """
    if not candidate_urls:
        return []
    verified: list[str] = []
    for url in candidate_urls:
        try:
            owner, repo = parse_github_repo_url(url)
        except ValueError:
            logger.warning("Skipping invalid URL during removal verification: {}", url)
            continue
        resp = gh.get(f"/repos/{owner}/{repo}")
        if resp.status_code == 404:
            verified.append(url)
        else:
            logger.info(
                "REST check says {} still exists (HTTP {}), skipping removal",
                url,
                resp.status_code,
            )
    return verified


def resurrect_removed_skills(settings: Settings) -> dict[str, int]:
    """Re-check all skills marked source_repo_removed and clear false positives.

    Queries all distinct source_repo_url values where source_repo_removed=true,
    checks each via REST API, and clears the flag + re-enables trackers for
    repos that are still accessible.

    Returns a summary dict with counts.
    """
    from decision_hub.infra.database import (
        clear_source_removed_for_urls,
        create_engine,
        fetch_removed_source_repo_urls,
        reenable_trackers_for_urls,
    )

    engine = create_engine(settings.database_url)

    with engine.connect() as conn:
        removed_urls = fetch_removed_source_repo_urls(conn)

    if not removed_urls:
        logger.info("resurrect_removed_skills: no removed skills to check")
        return {"checked": 0, "resurrected": 0, "confirmed_removed": 0}

    logger.info("resurrect_removed_skills: checking {} removed repo URLs", len(removed_urls))

    from decision_hub.infra.github_client import GitHubClient

    github_token = _resolve_github_token(settings)

    # TODO: at scale (1000+ URLs), consider batching to avoid GitHub secondary rate limits
    with GitHubClient(token=github_token) as gh:
        confirmed_removed_urls = set(_verify_repos_removed(gh, removed_urls))
    still_alive = [url for url in removed_urls if url not in confirmed_removed_urls]

    resurrected_skills = 0
    resurrected_trackers = 0
    if still_alive:
        with engine.connect() as conn:
            resurrected_skills = clear_source_removed_for_urls(conn, still_alive)
            resurrected_trackers = reenable_trackers_for_urls(conn, still_alive)
            conn.commit()

    confirmed_removed = len(removed_urls) - len(still_alive)
    logger.info(
        "resurrect_removed_skills: checked={} alive={} confirmed_removed={} "
        "skills_resurrected={} trackers_reenabled={}",
        len(removed_urls),
        len(still_alive),
        confirmed_removed,
        resurrected_skills,
        resurrected_trackers,
    )
    return {
        "checked": len(removed_urls),
        "resurrected": len(still_alive),
        "confirmed_removed": confirmed_removed,
        "skills_resurrected": resurrected_skills,
        "trackers_reenabled": resurrected_trackers,
    }


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
        batch_increment_permanent_failures,
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
            trackers_disabled=0,
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

        # Note: `errored` is computed before the circuit breaker check, so it
        # includes IDs that may be downgraded to transient below.  This is
        # intentional — they did error, even if we choose not to count them as
        # permanent for failure-counter purposes.
        errored = len(errored_ids_transient) + len(errored_ids_permanent)
        unchanged = len(unchanged_ids)

        # Circuit breaker: if permanent errors dominate, it's likely a
        # systemic GitHub issue (outage, token failure), not mass deletion.
        # Downgrade all permanent errors to transient so they retry next tick
        # without incrementing the consecutive failure counter.
        total_resolved = len(unchanged_ids) + len(errored_ids_permanent) + len(changed_trackers)
        if (
            errored_ids_permanent
            and total_resolved > 0
            and len(errored_ids_permanent) / total_resolved > settings.tracker_circuit_breaker_ratio
        ):
            logger.warning(
                "Circuit breaker tripped: {}/{} resolved trackers returned permanent errors, "
                "downgrading all to transient",
                len(errored_ids_permanent),
                total_resolved,
            )
            circuit_breaker_ids = list(errored_ids_permanent)
            errored_ids_permanent = []
        else:
            circuit_breaker_ids = []

        # Batch DB writes — one UPDATE per category, single commit
        with engine.connect() as conn:
            batch_clear_tracker_errors(conn, unchanged_ids)
            batch_set_tracker_errors(conn, errored_ids_permanent, "GraphQL: repo not found or inaccessible")
            batch_set_tracker_errors(conn, errored_ids_transient, "transient: GraphQL chunk failed, will retry")
            if circuit_breaker_ids:
                batch_set_tracker_errors(
                    conn,
                    circuit_breaker_ids,
                    "transient: circuit breaker tripped, mass permanent errors downgraded",
                )
            # Increment consecutive failure counter; only disable after threshold
            disabled_count = 0
            if errored_ids_permanent:
                threshold = settings.tracker_permanent_failure_threshold
                over_threshold_ids = batch_increment_permanent_failures(
                    conn,
                    errored_ids_permanent,
                    threshold=threshold,
                )
                if over_threshold_ids:
                    disabled_count = len(over_threshold_ids)
                    over_threshold_set = set(over_threshold_ids)
                    batch_disable_trackers(conn, over_threshold_ids)
                    candidate_urls = list(
                        {
                            t.repo_url
                            for key, kts in repo_key_to_trackers.items()
                            if key not in failed_chunk_keys and sha_map.get(key) is None
                            for t in kts
                            if t.id in over_threshold_set
                        }
                    )
                    # REST verification: only mark removed if GitHub REST API
                    # confirms 404.  GraphQL null can be caused by renames,
                    # transient issues, or permission gaps — not just deletion.
                    verified_removed = _verify_repos_removed(gh, candidate_urls)
                    mark_skills_source_removed(conn, verified_removed)
                    logger.info(
                        "permanent_failures: {} incremented, {} crossed threshold (>={}), "
                        "{} candidates, {} verified removed via REST",
                        len(errored_ids_permanent),
                        len(over_threshold_ids),
                        threshold,
                        len(candidate_urls),
                        len(verified_removed),
                    )
                else:
                    logger.info(
                        "permanent_failures: {} incremented (threshold={}, none crossed yet)",
                        len(errored_ids_permanent),
                        threshold,
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
            trackers_disabled=0,
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
                trackers_disabled=0,
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
        trackers_disabled=disabled_count,
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
            wrap_returned_exceptions=False,
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

            # Detect skills removed from repo: compare discovered skill names
            # against DB skills for this org+repo and mark missing ones.
            _detect_removed_skills(skill_dirs, tracker, engine)

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


def _detect_removed_skills(
    skill_dirs: list[Path],
    tracker: SkillTracker,
    engine: Any,
) -> None:
    """Compare discovered skill names against DB and mark missing ones as removed.

    Parses each discovered SKILL.md to extract the canonical skill name, then
    queries the DB for existing (non-removed) skills under the same org+repo.
    Any DB skills not found in the current discovery are marked source_repo_removed=true.
    """
    from decision_hub.infra.database import fetch_skill_names_by_source_repo, mark_skills_removed_by_name

    discovered_names: set[str] = set()
    for skill_dir in skill_dirs:
        try:
            manifest = parse_skill_md(skill_dir / "SKILL.md")
            discovered_names.add(manifest.name)
        except (ValueError, FileNotFoundError):
            continue

    # Guard: if skill_dirs were provided but every parse failed,
    # discovered_names is empty and the subtraction would incorrectly
    # mark all DB skills as removed.  Bail out instead.
    if skill_dirs and not discovered_names:
        logger.warning(
            "tracker_id={} repo={} all {} SKILL.md parses failed, skipping removal detection",
            tracker.id,
            tracker.repo_url,
            len(skill_dirs),
        )
        return

    with engine.connect() as conn:
        db_names = fetch_skill_names_by_source_repo(conn, tracker.org_slug, tracker.repo_url)
        removed_names = db_names - discovered_names
        if removed_names:
            mark_skills_removed_by_name(conn, tracker.org_slug, removed_names)
            conn.commit()
            logger.info(
                "tracker_id={} repo={} marked_removed={}",
                tracker.id,
                tracker.repo_url,
                removed_names,
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

    Delegates to ``execute_publish()`` for the core pipeline.  This
    function handles tracker-specific concerns: checksum deduplication,
    version determination, and mapping ``GauntletRejectionError`` to a
    ``False`` return value (so the tracker retries on the next tick).

    Returns True if a new version was actually published to S3,
    False if skipped (no content changes) or rejected by the gauntlet.
    """
    from decision_hub.domain.publish_pipeline import GauntletRejectionError, VersionConflictError, execute_publish
    from decision_hub.infra.database import (
        find_org_by_slug,
        has_recent_quarantine,
        resolve_latest_version,
    )
    from decision_hub.infra.storage import compute_checksum

    skill_md_path = skill_dir / "SKILL.md"
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

        # Skip re-running gauntlet if identical content was quarantined recently
        if has_recent_quarantine(
            conn,
            org_slug=org_slug,
            skill_name=skill_name,
            checksum=checksum,
            max_age_hours=settings.tracker_quarantine_skip_hours,
        ):
            logger.info(
                "tracker_id={} repo={} skill={}/{} status=quarantine_dedup checksum={}",
                tracker.id,
                tracker.repo_url,
                org_slug,
                skill_name,
                checksum[:12],
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

        try:
            result = execute_publish(
                conn=conn,
                s3_client=s3_client,
                settings=settings,
                org_id=org.id,
                org_slug=org_slug,
                skill_name=skill_name,
                version=version,
                checksum=checksum,
                file_bytes=zip_data,
                publisher=f"tracker:{tracker.id}",
                user_id=tracker.user_id,
                source_repo_url=tracker.repo_url,
                auto_bump_version=True,
            )
        except GauntletRejectionError:
            logger.warning(
                "tracker_id={} repo={} skill={}/{}@{} status=rejected",
                tracker.id,
                tracker.repo_url,
                org_slug,
                skill_name,
                version,
            )
            return False
        except VersionConflictError:
            logger.warning(
                "tracker_id={} repo={} skill={}/{}@{} status=version_conflict (race condition)",
                tracker.id,
                tracker.repo_url,
                org_slug,
                skill_name,
                version,
            )
            return False

    logger.info(
        "tracker_id={} repo={} skill={}/{}@{} status=published grade={}",
        tracker.id,
        tracker.repo_url,
        org_slug,
        skill_name,
        result.version,
        result.eval_status,
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
