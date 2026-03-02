"""Unified publish pipeline.

Both the HTTP publish endpoint (registry_routes) and the tracker
automation (tracker_service) funnel through ``execute_publish()`` so
every skill version goes through exactly the same gauntlet → upsert →
upload → version → audit → eval sequence.  Differences (visibility,
version bumping, source URL) are expressed as parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from loguru import logger
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from decision_hub.api.registry_service import (
    classify_skill_category,
    maybe_trigger_agent_assessment,
    parse_manifest_from_content,
    quarantine_and_log_rejection,
    run_gauntlet_pipeline,
)
from decision_hub.domain.publish import build_s3_key, extract_for_evaluation
from decision_hub.domain.skill_manifest import extract_body, extract_description
from decision_hub.infra.database import (
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
from decision_hub.settings import Settings


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


def execute_publish(
    *,
    conn: Connection,
    s3_client: object,
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

    # 9. Upload to S3 and create version record
    s3_key = build_s3_key(org_slug, skill_name, version)
    upload_skill_zip(s3_client, settings.s3_bucket, s3_key, file_bytes)

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
    )

    # 11. Commit so the version row is visible to the background eval thread
    conn.commit()

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
