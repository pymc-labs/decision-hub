"""Unified publish pipeline.

Both the HTTP publish endpoint (registry_routes) and the tracker
automation (tracker_service) funnel through ``execute_publish()`` so
every skill version goes through exactly the same gauntlet → upsert →
upload → version → audit → eval sequence.  Differences (visibility,
version bumping, source URL) are expressed as parameters.

This module also houses the business-logic helpers that the pipeline
depends on (gauntlet, classification, quarantine, manifest parsing,
eval triggering).  ``api.registry_service`` re-exports some of these
for backward compatibility with scripts and tests that import from
the old location.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from loguru import logger
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from decision_hub.domain.gauntlet import run_static_checks
from decision_hub.domain.publish import build_quarantine_s3_key, build_s3_key, extract_for_evaluation
from decision_hub.domain.skill_manifest import extract_body, extract_description, parse_skill_md
from decision_hub.infra.database import (
    delete_audit_logs_by_version_id,
    delete_version,
    find_skill,
    find_version,
    insert_audit_log,
    insert_skill,
    insert_version,
    update_skill_category,
    update_skill_description,
    update_skill_manifest_path,
    update_skill_source_repo_url,
    update_skill_visibility,
)
from decision_hub.infra.embeddings import generate_and_store_skill_embedding
from decision_hub.infra.storage import upload_skill_zip
from decision_hub.models import GauntletReport
from decision_hub.settings import Settings

# ---------------------------------------------------------------------------
# Result / error types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PublishResult:
    """Outcome of a successful publish."""

    skill_id: UUID
    version_id: UUID
    version: str
    s3_key: str
    checksum: str
    eval_status: str
    eval_report_status: str | None
    eval_run_id: str | None


class VersionConflictError(Exception):
    """Raised when the requested version already exists and auto-bump is off."""

    def __init__(self, org_slug: str, skill_name: str, version: str) -> None:
        self.org_slug = org_slug
        self.skill_name = skill_name
        self.version = version
        super().__init__(f"Version {version} already exists for {org_slug}/{skill_name}")


class GauntletRejectionError(Exception):
    """Raised when the gauntlet rejects a skill (grade F).

    Quarantine and audit logging have already been performed when this
    is raised — callers only need to map it to their response format.
    """

    def __init__(self, summary: str) -> None:
        self.summary = summary
        super().__init__(summary)


# ---------------------------------------------------------------------------
# Manifest parsing helpers
# ---------------------------------------------------------------------------


def extract_runtime_config_dict(manifest) -> dict | None:
    """Extract runtime config as a JSON-compatible dict for database storage."""
    if manifest.runtime is None:
        return None

    runtime_dict = {
        "language": manifest.runtime.language,
        "entrypoint": manifest.runtime.entrypoint,
        "version_hint": manifest.runtime.version_hint,
        "env": list(manifest.runtime.env),
        "capabilities": list(manifest.runtime.capabilities),
        "repair_strategy": manifest.runtime.repair_strategy,
    }

    if manifest.runtime.dependencies:
        runtime_dict["dependencies"] = {
            "system": list(manifest.runtime.dependencies.system),
            "package_manager": manifest.runtime.dependencies.package_manager,
            "packages": list(manifest.runtime.dependencies.packages),
            "lockfile": manifest.runtime.dependencies.lockfile,
        }

    return runtime_dict


def extract_assessment_config(manifest):
    """Extract eval config from manifest (returns None if not present)."""
    return manifest.evals


def try_parse_assessment_cases(file_bytes: bytes):
    """Parse eval cases from zip. Returns empty tuple if no evals/ directory.

    Raises ValueError if eval files exist but are malformed —
    fail-closed to prevent bypassing the eval pipeline with broken YAML.
    """
    from decision_hub.domain.skill_manifest import parse_eval_cases_from_zip

    return parse_eval_cases_from_zip(file_bytes)


def parse_manifest_from_content(
    skill_md_content: str,
    file_bytes: bytes,
) -> tuple[dict | None, object | None, tuple, str | None]:
    """Parse SKILL.md and extract runtime config, eval config, eval cases, and allowed_tools.

    Uses a temp file because parse_skill_md expects a file path.
    Returns (runtime_config_dict, eval_config, eval_cases, allowed_tools).

    Raises ValueError if the manifest is malformed — fail-closed
    to prevent publishing skills with unparseable manifests.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
        tmp.write(skill_md_content)
        tmp_path = Path(tmp.name)

    try:
        manifest = parse_skill_md(tmp_path)
        return (
            extract_runtime_config_dict(manifest),
            extract_assessment_config(manifest),
            try_parse_assessment_cases(file_bytes),
            manifest.allowed_tools,
        )
    except ValueError as exc:
        logger.warning("Manifest parse failed (rejecting publish): {}", exc)
        raise ValueError(f"SKILL.md manifest is malformed: {exc}") from exc
    finally:
        tmp_path.unlink()


# ---------------------------------------------------------------------------
# Gauntlet pipeline
# ---------------------------------------------------------------------------


def _build_analyze_fn(settings: Settings, gemini: dict | None = None):
    """Build a Gemini analyze callback if google_api_key is configured."""
    if not settings.google_api_key:
        return None

    from decision_hub.infra.gemini import analyze_code_safety, create_gemini_client

    gemini_client = gemini or create_gemini_client(settings.google_api_key)

    def analyze_fn(snippets, source_files, skill_name, skill_description):
        return analyze_code_safety(
            gemini_client,
            snippets,
            source_files,
            skill_name,
            skill_description,
            model=settings.gemini_model,
        )

    return analyze_fn


def _build_analyze_prompt_fn(settings: Settings, gemini: dict | None = None):
    """Build a Gemini prompt analyze callback if google_api_key is configured."""
    if not settings.google_api_key:
        return None

    from decision_hub.infra.gemini import analyze_prompt_safety, create_gemini_client

    gemini_client = gemini or create_gemini_client(settings.google_api_key)

    def analyze_prompt_fn(prompt_hits, skill_name, skill_description):
        return analyze_prompt_safety(
            gemini_client,
            prompt_hits,
            skill_name,
            skill_description,
            model=settings.gemini_model,
        )

    return analyze_prompt_fn


def _build_review_body_fn(settings: Settings, gemini: dict | None = None):
    """Build a Gemini holistic body review callback if google_api_key is configured."""
    if not settings.google_api_key:
        return None

    from decision_hub.infra.gemini import create_gemini_client, review_prompt_body_safety

    gemini_client = gemini or create_gemini_client(settings.google_api_key)

    def review_body_fn(body, skill_name, skill_description):
        return review_prompt_body_safety(
            gemini_client,
            body,
            skill_name,
            skill_description,
            model=settings.gemini_model,
        )

    return review_body_fn


def _build_review_code_fn(settings: Settings, gemini: dict | None = None):
    """Build a Gemini holistic code review callback if google_api_key is configured."""
    if not settings.google_api_key:
        return None

    from decision_hub.infra.gemini import create_gemini_client, review_code_body_safety

    gemini_client = gemini or create_gemini_client(settings.google_api_key)

    def review_code_fn(source_files, skill_name, skill_description):
        return review_code_body_safety(
            gemini_client,
            source_files,
            skill_name,
            skill_description,
            model=settings.gemini_model,
        )

    return review_code_fn


def _build_analyze_credential_fn(settings: Settings, gemini: dict | None = None):
    """Build a Gemini credential entropy review callback if google_api_key is configured."""
    if not settings.google_api_key:
        return None

    from decision_hub.infra.gemini import analyze_credential_entropy, create_gemini_client

    gemini_client = gemini or create_gemini_client(settings.google_api_key)

    def analyze_credential_fn(entropy_hits, skill_name, skill_description):
        return analyze_credential_entropy(
            gemini_client,
            entropy_hits,
            skill_name,
            skill_description,
            model=settings.gemini_model,
        )

    return analyze_credential_fn


def run_gauntlet_pipeline(
    skill_md_content: str,
    lockfile_content: str | None,
    source_files: list[tuple[str, str]],
    skill_name: str,
    description: str,
    skill_md_body: str,
    settings: Settings,
    *,
    allowed_tools: str | None = None,
    llm_required: bool = True,
    unscanned_files: list[str] | None = None,
) -> tuple[GauntletReport, list[dict], dict | None]:
    """Run Gauntlet static checks and serialize results for audit logging.

    Returns (report, check_results_dicts, llm_reasoning).

    Raises:
        RuntimeError: If llm_required=True but no Google API key is configured.
    """
    if llm_required and not settings.google_api_key:
        raise RuntimeError("LLM judge required for gauntlet but GOOGLE_API_KEY is not configured")

    from decision_hub.infra.gemini import create_gemini_client

    # Reuse one HTTP client for all Gemini calls in this gauntlet run,
    # saving ~100-200ms of TCP+TLS handshake per LLM call (2-4 calls typical).
    with httpx.Client(timeout=60) as shared_http:
        gemini = (
            create_gemini_client(settings.google_api_key, http_client=shared_http) if settings.google_api_key else None
        )

        report = run_static_checks(
            skill_md_content,
            lockfile_content,
            source_files,
            skill_name=skill_name,
            skill_description=description,
            analyze_fn=_build_analyze_fn(settings, gemini),
            skill_md_body=skill_md_body,
            allowed_tools=allowed_tools,
            analyze_prompt_fn=_build_analyze_prompt_fn(settings, gemini),
            review_body_fn=_build_review_body_fn(settings, gemini),
            analyze_credential_fn=_build_analyze_credential_fn(settings, gemini),
            review_code_fn=_build_review_code_fn(settings, gemini),
            unscanned_files=unscanned_files,
        )

    check_results_dicts = [
        {
            "check_name": r.check_name,
            "severity": r.severity,
            "message": r.message,
        }
        for r in report.results
    ]

    llm_reasoning = {r.check_name: r.details for r in report.results if r.details is not None} or None

    return report, check_results_dicts, llm_reasoning


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


def quarantine_and_log_rejection(
    conn: Connection,
    s3_client: Any,
    bucket: str,
    file_bytes: bytes,
    *,
    org_slug: str,
    skill_name: str,
    version: str,
    report: GauntletReport,
    check_results: list[dict],
    llm_reasoning: dict | None,
    publisher: str,
    checksum: str | None = None,
) -> None:
    """Upload rejected zip to quarantine and log the rejection.

    Inserts and commits the audit log before uploading to quarantine S3,
    so the rejection record is durable even if the S3 upload fails.

    Does NOT raise an exception — callers decide how to handle the rejection
    (HTTP endpoint raises 422, tracker returns False).
    """
    logger.warning(
        "Quarantining {}/{} v{} — grade={} summary={}",
        org_slug,
        skill_name,
        version,
        report.grade,
        report.summary,
    )
    q_key = build_quarantine_s3_key(org_slug, skill_name, version)

    insert_audit_log(
        conn,
        org_slug=org_slug,
        skill_name=skill_name,
        semver=version,
        grade=report.grade,
        check_results=check_results,
        publisher=publisher,
        version_id=None,
        llm_reasoning=llm_reasoning,
        quarantine_s3_key=q_key,
        checksum=checksum,
    )
    # Commit the audit record before uploading to S3 so it survives
    # any subsequent failure. This ensures rejection forensics are
    # always preserved.
    conn.commit()

    upload_skill_zip(s3_client, bucket, q_key, file_bytes)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_skill_category(
    skill_name: str,
    description: str,
    skill_md_body: str,
    settings: Settings,
) -> str:
    """Run LLM classification to assign a category to a skill.

    Returns the subcategory string (e.g. "Backend & APIs"). Falls back
    to DEFAULT_CATEGORY if the LLM is unavailable or returns garbage.
    """
    from dhub_core.taxonomy import DEFAULT_CATEGORY

    if not settings.google_api_key:
        return DEFAULT_CATEGORY

    from decision_hub.domain.classification import build_taxonomy_prompt_fragment, parse_classification_response
    from decision_hub.infra.gemini import classify_skill, create_gemini_client

    try:
        gemini_client = create_gemini_client(settings.google_api_key)
        taxonomy_fragment = build_taxonomy_prompt_fragment()
        raw_response = classify_skill(
            gemini_client,
            skill_name,
            description,
            skill_md_body,
            taxonomy_fragment,
            model=settings.gemini_model,
        )
        result = parse_classification_response(raw_response)
        logger.info(
            "Classified {} as {} (group={}, confidence={:.2f})",
            skill_name,
            result.category,
            result.group,
            result.confidence,
        )
        return result.category
    except Exception:
        logger.opt(exception=True).warning("Skill classification failed for {}, using default", skill_name)
        return DEFAULT_CATEGORY


# ---------------------------------------------------------------------------
# Eval triggering
# ---------------------------------------------------------------------------


def maybe_trigger_agent_assessment(
    eval_config,
    eval_cases: tuple,
    s3_key: str,
    s3_bucket: str,
    version_id,
    org_slug: str,
    skill_name: str,
    settings: Settings,
    user_id,
) -> tuple[str | None, str | None]:
    """Conditionally trigger background agent assessment if config present.

    Creates an eval_run row BEFORE spawning the Modal function, so the
    CLI can immediately start tailing logs.

    Uses a fresh DB connection because the caller's engine.begin()
    transaction is already committed and closed.

    Returns (eval_report_status, eval_run_id) — both None if no assessment config.

    Raises ValueError if config is declared but no case files found.
    """
    if eval_config and not eval_cases:
        raise ValueError("Assessment config declared in manifest but no case files found in evals/")
    if eval_config and eval_cases:
        # Use a fresh connection — the caller's transaction is already closed
        # after the explicit conn.commit() that makes the version row visible.
        # Generate the run ID client-side so the S3 prefix is known before insert.
        from uuid import uuid4

        import modal

        from decision_hub.infra.database import create_engine, insert_eval_run

        run_uuid = uuid4()
        log_s3_prefix = f"eval-logs/{run_uuid}/"

        engine = create_engine(settings.database_url)
        with engine.connect() as eval_conn:
            eval_run = insert_eval_run(
                eval_conn,
                run_id=run_uuid,
                version_id=version_id,
                user_id=user_id,
                agent=eval_config.agent,
                judge_model=eval_config.judge_model,
                total_cases=len(eval_cases),
                log_s3_prefix=log_s3_prefix,
            )
            eval_conn.commit()

        logger.info(
            "Spawning eval task run_id={} agent={} cases={} for {}/{}",
            eval_run.id,
            eval_config.agent,
            len(eval_cases),
            org_slug,
            skill_name,
        )

        # Serialize EvalCase dataclasses to dicts for Modal transport
        cases_dicts = [
            {
                "name": c.name,
                "description": c.description,
                "prompt": c.prompt,
                "judge_criteria": c.judge_criteria,
            }
            for c in eval_cases
        ]

        run_eval = modal.Function.from_name(
            settings.modal_app_name,
            "run_eval_task",
        )
        run_eval.spawn(
            version_id=str(version_id),
            eval_run_id=str(eval_run.id),
            eval_agent=eval_config.agent,
            eval_judge_model=eval_config.judge_model,
            eval_cases_dicts=cases_dicts,
            s3_key=s3_key,
            s3_bucket=s3_bucket,
            org_slug=org_slug,
            skill_name=skill_name,
            user_id=str(user_id),
        )
        return "pending", str(eval_run.id)
    return None, None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def execute_publish(
    *,
    conn: Connection,
    s3_client: Any,
    settings: Settings,
    org_id: UUID,
    org_slug: str,
    skill_name: str,
    version: str,
    checksum: str,
    file_bytes: bytes,
    publisher: str,
    user_id: UUID,
    visibility: str | None = None,
    source_repo_url: str | None = None,
    manifest_path: str | None = None,
    auto_bump_version: bool = False,
) -> PublishResult:
    """Run the full publish pipeline for a single skill version.

    This is the single source of truth for publishing. Both the HTTP
    endpoint and the tracker automation call this function.

    Args:
        conn: Active DB connection (caller manages the transaction).
        s3_client: Boto3 S3 client.
        settings: Application settings.
        org_id: UUID of the owning organization.
        org_slug: Organization slug (for S3 keys and audit logs).
        skill_name: Validated skill name.
        version: Semver version string.
        checksum: SHA-256 hex digest of *file_bytes*.
        file_bytes: Raw zip bytes.
        publisher: Attribution string (username or ``tracker:<id>``).
        user_id: UUID of the publishing user (for eval triggering).
        visibility: ``"public"`` or ``"org"``; ``None`` keeps existing
            or defaults to ``"public"`` on first publish.
        source_repo_url: GitHub repo URL to store on the skill record.
        manifest_path: Relative path to SKILL.md within the repo.
        auto_bump_version: When ``True``, auto-bump patch if *version*
            already exists instead of raising ``VersionConflictError``.

    Returns:
        A ``PublishResult`` with IDs, version, S3 key, and eval info.

    Raises:
        ValueError: If zip extraction fails (missing SKILL.md, zip bomb).
        GauntletRejectionError: If the gauntlet grades the skill F.
            Quarantine upload and audit logging have already happened.
        VersionConflictError: If the version already exists and
            *auto_bump_version* is ``False``.
    """
    # 1. Extract files for evaluation
    skill_md_content, source_files, lockfile_content, unscanned_files = extract_for_evaluation(file_bytes)

    # 2. Parse manifest
    runtime_config_dict, eval_config, eval_cases, allowed_tools = parse_manifest_from_content(
        skill_md_content,
        file_bytes,
    )

    # 2b. Validate eval config consistency before we publish anything
    if eval_config and not eval_cases:
        raise ValueError("Assessment config declared in manifest but no case files found in evals/")

    description = extract_description(skill_md_content)
    skill_md_body = extract_body(skill_md_content)

    # 3. Run gauntlet security pipeline
    report, check_results_dicts, llm_reasoning = run_gauntlet_pipeline(
        skill_md_content,
        lockfile_content,
        source_files,
        skill_name,
        description,
        skill_md_body,
        settings,
        allowed_tools=allowed_tools,
        unscanned_files=unscanned_files,
    )
    logger.info(
        "Gauntlet result for {}/{} v{}: grade={} passed={}",
        org_slug,
        skill_name,
        version,
        report.grade,
        report.passed,
    )

    # 4. Quarantine if rejected
    if not report.passed:
        quarantine_and_log_rejection(
            conn,
            s3_client,
            settings.s3_bucket,
            file_bytes,
            org_slug=org_slug,
            skill_name=skill_name,
            version=version,
            report=report,
            check_results=check_results_dicts,
            llm_reasoning=llm_reasoning,
            publisher=publisher,
            checksum=checksum,
        )
        raise GauntletRejectionError(report.summary)

    # 5. Classify category (non-critical, graceful fallback)
    category = classify_skill_category(skill_name, description, skill_md_body, settings)

    # 6. Upsert skill record
    skill = find_skill(conn, org_id, skill_name)
    if skill is None:
        skill = insert_skill(
            conn,
            org_id,
            skill_name,
            description,
            category=category,
            visibility=visibility or "public",
            source_repo_url=source_repo_url,
            manifest_path=manifest_path,
        )
    else:
        update_skill_description(conn, skill.id, description)
        update_skill_category(conn, skill.id, category)
        if source_repo_url and skill.source_repo_url != source_repo_url:
            update_skill_source_repo_url(conn, skill.id, source_repo_url)
        if manifest_path and skill.manifest_path != manifest_path:
            update_skill_manifest_path(conn, skill.id, manifest_path)
        if visibility is not None:
            update_skill_visibility(conn, skill.id, visibility)

    # 7. Handle duplicate version
    if find_version(conn, skill.id, version) is not None:
        if auto_bump_version:
            from decision_hub.domain.repo_utils import bump_version

            version = bump_version(version)
        else:
            raise VersionConflictError(org_slug, skill_name, version)

    # 8. Generate embedding (fail-open: never blocks publish)
    generate_and_store_skill_embedding(conn, skill.id, skill_name, org_slug, category, description, settings)

    # 9. Record the version and audit log in DB, then commit before
    # uploading to S3. This avoids orphaned S3 objects when the DB
    # commit fails.
    s3_key = build_s3_key(org_slug, skill_name, version)

    try:
        version_record = insert_version(
            conn,
            skill_id=skill.id,
            semver=version,
            s3_key=s3_key,
            checksum=checksum,
            runtime_config=runtime_config_dict,
            published_by=publisher,
            eval_status=report.grade,
            gauntlet_summary=report.gauntlet_summary,
        )
    except IntegrityError:
        raise VersionConflictError(org_slug, skill_name, version) from None

    # 10. Audit log
    insert_audit_log(
        conn,
        org_slug=org_slug,
        skill_name=skill_name,
        semver=version,
        grade=report.grade,
        check_results=check_results_dicts,
        publisher=publisher,
        version_id=version_record.id,
        llm_reasoning=llm_reasoning,
        checksum=checksum,
    )

    # 11. Commit DB first so the version row is visible to the background
    # eval thread.  S3 upload follows — if it fails we roll back the DB rows.
    conn.commit()

    try:
        upload_skill_zip(s3_client, settings.s3_bucket, s3_key, file_bytes)
    except Exception:
        logger.opt(exception=True).error(
            "S3 upload failed for {}/{} v{} — rolling back version {}",
            org_slug,
            skill_name,
            version,
            version_record.id,
        )
        delete_audit_logs_by_version_id(conn, version_record.id)
        delete_version(conn, skill.id, version)
        conn.commit()
        raise

    # 12. Trigger eval assessment if configured (non-critical post-commit)
    eval_report_status: str | None = None
    eval_run_id: str | None = None
    try:
        eval_report_status, eval_run_id = maybe_trigger_agent_assessment(
            eval_config=eval_config,
            eval_cases=eval_cases,
            s3_key=s3_key,
            s3_bucket=settings.s3_bucket,
            version_id=version_record.id,
            org_slug=org_slug,
            skill_name=skill_name,
            settings=settings,
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning(
            "Eval trigger failed for {}/{} v{} (publish succeeded): {}",
            org_slug,
            skill_name,
            version,
            exc,
        )

    logger.info(
        "Published {}/{} v{} — version_id={} grade={} eval_run={}",
        org_slug,
        skill_name,
        version,
        version_record.id,
        report.grade,
        eval_run_id,
    )

    return PublishResult(
        skill_id=skill.id,
        version_id=version_record.id,
        version=version,
        s3_key=s3_key,
        checksum=checksum,
        eval_status=report.grade,
        eval_report_status=eval_report_status,
        eval_run_id=eval_run_id,
    )
