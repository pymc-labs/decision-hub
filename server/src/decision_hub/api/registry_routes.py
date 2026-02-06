"""Skill registry routes -- publish, resolve, and delete."""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.engine import Connection

from decision_hub.api.deps import get_connection, get_current_user, get_s3_client, get_settings
from decision_hub.domain.gauntlet import run_static_checks
from decision_hub.domain.publish import (
    build_quarantine_s3_key,
    build_s3_key,
    extract_for_evaluation,
    validate_semver,
    validate_skill_name,
)
from decision_hub.domain.search import format_trust_score
from decision_hub.domain.skill_manifest import extract_body, extract_description
from decision_hub.infra.database import (
    delete_all_versions,
    delete_skill as delete_skill_record,
    delete_version,
    fetch_all_skills_for_index,
    find_audit_logs,
    find_eval_report_by_skill,
    find_eval_report_by_version,
    find_org_by_slug,
    find_org_member,
    find_skill,
    find_version,
    insert_audit_log,
    insert_eval_report,
    insert_skill,
    insert_version,
    resolve_latest_version,
    resolve_version,
    update_eval_report,
    update_skill_description,
)
from decision_hub.infra.storage import (
    compute_checksum,
    delete_skill_zip,
    generate_presigned_url,
    upload_skill_zip,
)
from decision_hub.models import User
from decision_hub.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["registry"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class PublishResponse(BaseModel):
    """Confirmation of a published skill version."""
    skill_id: str
    version: str
    s3_key: str
    checksum: str
    eval_status: str
    eval_report_status: str | None = None


class ResolveResponse(BaseModel):
    """Resolved skill version with a pre-signed download URL."""
    version: str
    download_url: str
    checksum: str


class DeleteResponse(BaseModel):
    """Confirmation of a deleted skill version."""
    org_slug: str
    skill_name: str
    version: str


class LatestVersionResponse(BaseModel):
    """Latest version of a skill."""
    version: str


class DeleteAllResponse(BaseModel):
    """Confirmation of deleting all versions of a skill."""
    org_slug: str
    skill_name: str
    versions_deleted: int


class SkillSummary(BaseModel):
    """Summary of a published skill for the list endpoint."""
    org_slug: str
    skill_name: str
    description: str
    latest_version: str
    updated_at: str
    safety_rating: str
    author: str


class AuditLogResponse(BaseModel):
    """A single audit log entry."""
    id: str
    org_slug: str
    skill_name: str
    semver: str
    grade: str
    version_id: str | None
    check_results: list[dict]
    llm_reasoning: dict | None
    publisher: str
    quarantine_s3_key: str | None
    created_at: str | None


class EvalCaseResultResponse(BaseModel):
    """A single eval case result."""
    name: str
    description: str
    verdict: str
    reasoning: str
    agent_output: str
    agent_stderr: str
    exit_code: int
    duration_ms: int
    stage: str


class EvalReportResponse(BaseModel):
    """Eval report for a skill version."""
    id: str
    version_id: str
    agent: str
    judge_model: str
    case_results: list[EvalCaseResultResponse]
    passed: int
    total: int
    total_duration_ms: int
    status: str
    error_message: str | None
    created_at: str | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/publish", response_model=PublishResponse, status_code=201)
async def publish_skill(
    background_tasks: BackgroundTasks,
    metadata: str = Form(...),
    zip_file: UploadFile = File(...),
    conn: Connection = Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> PublishResponse:
    """Publish a new skill version.

    Accepts multipart form data with a metadata JSON string and a zip file.
    Validates org membership, semver, and skill name before uploading to S3
    and recording the version in the database.
    """
    # LLM judge is required for publishing
    if not settings.google_api_key:
        raise HTTPException(
            status_code=503,
            detail="LLM judge not configured. Cannot publish without LLM review.",
        )

    meta = json.loads(metadata)
    org_slug = meta["org_slug"]
    skill_name = meta["skill_name"]
    version = meta["version"]

    validate_skill_name(skill_name)
    validate_semver(version)

    # Verify the caller belongs to the target organisation
    org = find_org_by_slug(conn, org_slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    member = find_org_member(conn, org.id, current_user.id)
    if member is None:
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this organisation",
        )

    # Read file contents and compute checksum
    file_bytes = await zip_file.read()
    checksum = compute_checksum(file_bytes)

    # Run Gauntlet static checks before uploading
    try:
        skill_md_content, source_files, lockfile_content = extract_for_evaluation(file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Parse manifest to extract runtime config and eval config.
    # If parsing fails (malformed frontmatter), the gauntlet will catch
    # the issue downstream — we just skip runtime/eval extraction.
    from decision_hub.domain.skill_manifest import parse_skill_md
    import tempfile
    from pathlib import Path

    runtime_config_dict = None
    eval_config = None
    eval_cases: tuple = ()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
        tmp.write(skill_md_content)
        tmp_path = Path(tmp.name)

    try:
        manifest = parse_skill_md(tmp_path)
        runtime_config_dict = _extract_runtime_config_dict(manifest)
        eval_config = _extract_assessment_config(manifest)
        eval_cases = _try_parse_assessment_cases(file_bytes)
    except ValueError:
        pass
    finally:
        tmp_path.unlink()

    # Extract description and body from SKILL.md
    description = extract_description(skill_md_content)
    skill_md_body = extract_body(skill_md_content)

    # Build LLM callbacks
    analyze_fn = _build_analyze_fn(settings)
    analyze_prompt_fn = _build_analyze_prompt_fn(settings)

    report = run_static_checks(
        skill_md_content,
        lockfile_content,
        source_files,
        skill_name=skill_name,
        skill_description=description,
        analyze_fn=analyze_fn,
        skill_md_body=skill_md_body,
        allowed_tools=None,
        analyze_prompt_fn=analyze_prompt_fn,
        is_verified_org=True,
    )

    # Serialize check results for audit log
    check_results_dicts = [
        {
            "check_name": r.check_name,
            "severity": r.severity,
            "message": r.message,
        }
        for r in report.results
    ]

    # Collect LLM reasoning from checks that have details
    llm_reasoning = {
        r.check_name: r.details
        for r in report.results
        if r.details is not None
    } or None

    if not report.passed:
        # Grade F: quarantine the zip in S3 for forensic inspection
        q_key = build_quarantine_s3_key(org_slug, skill_name, version)
        upload_skill_zip(s3_client, settings.s3_bucket, q_key, file_bytes)

        insert_audit_log(
            conn,
            org_slug=org_slug,
            skill_name=skill_name,
            semver=version,
            grade=report.grade,
            check_results=check_results_dicts,
            publisher=current_user.username,
            version_id=None,
            llm_reasoning=llm_reasoning,
            quarantine_s3_key=q_key,
        )
        raise HTTPException(
            status_code=422,
            detail=f"Gauntlet checks failed: {report.summary}",
        )

    eval_status = report.grade

    # Upsert skill record (find or create), then check for duplicate version
    skill = find_skill(conn, org.id, skill_name)
    if skill is None:
        skill = insert_skill(conn, org.id, skill_name, description)
    else:
        update_skill_description(conn, skill.id, description)

    if find_version(conn, skill.id, version) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Version {version} already exists for {org_slug}/{skill_name}",
        )

    # Upload to S3
    s3_key = build_s3_key(org_slug, skill_name, version)
    upload_skill_zip(s3_client, settings.s3_bucket, s3_key, file_bytes)

    version_record = insert_version(
        conn,
        skill_id=skill.id,
        semver=version,
        s3_key=s3_key,
        checksum=checksum,
        runtime_config=runtime_config_dict,
        published_by=current_user.username,
        eval_status=eval_status,
    )

    # Insert audit log with version_id
    insert_audit_log(
        conn,
        org_slug=org_slug,
        skill_name=skill_name,
        semver=version,
        grade=report.grade,
        check_results=check_results_dicts,
        publisher=current_user.username,
        version_id=version_record.id,
        llm_reasoning=llm_reasoning,
    )

    # Trigger background agent eval if config and cases are present
    eval_report_status = _maybe_trigger_agent_assessment(
        background_tasks=background_tasks,
        eval_config=eval_config,
        eval_cases=eval_cases,
        file_bytes=file_bytes,
        version_id=version_record.id,
        org_slug=org_slug,
        skill_name=skill_name,
        settings=settings,
        user_id=current_user.id,
    )

    return PublishResponse(
        skill_id=str(skill.id),
        version=version_record.semver,
        s3_key=version_record.s3_key,
        checksum=version_record.checksum,
        eval_status=eval_status,
        eval_report_status=eval_report_status,
    )


@router.get("/skills", response_model=list[SkillSummary])
def list_skills(
    conn: Connection = Depends(get_connection),
) -> list[SkillSummary]:
    """List all published skills with their latest version info.

    Public endpoint — no authentication required.
    """
    rows = fetch_all_skills_for_index(conn)
    return [
        SkillSummary(
            org_slug=row["org_slug"],
            skill_name=row["skill_name"],
            description=row.get("description", ""),
            latest_version=row["latest_version"],
            updated_at=row["created_at"].strftime("%Y-%m-%d %H:%M:%S") if row.get("created_at") else "",
            safety_rating=format_trust_score(row["eval_status"]),
            author=row.get("published_by", ""),
        )
        for row in rows
    ]


@router.get(
    "/skills/{org_slug}/{skill_name}/latest-version",
    response_model=LatestVersionResponse,
)
def get_latest_version(
    org_slug: str,
    skill_name: str,
    conn: Connection = Depends(get_connection),
) -> LatestVersionResponse:
    """Return the latest published version of a skill (regardless of eval status).

    Used by the CLI for auto-bumping during publish.
    Public endpoint -- no authentication required.
    """
    version = resolve_latest_version(conn, org_slug, skill_name)
    if version is None:
        raise HTTPException(
            status_code=404,
            detail=f"No versions found for {org_slug}/{skill_name}",
        )
    return LatestVersionResponse(version=version.semver)


@router.get("/resolve/{org_slug}/{skill_name}", response_model=ResolveResponse)
def resolve_skill(
    org_slug: str,
    skill_name: str,
    spec: str = "latest",
    allow_risky: bool = Query(False),
    conn: Connection = Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
) -> ResolveResponse:
    """Resolve a skill version and return a pre-signed download URL.

    The ``spec`` query parameter can be ``latest`` or an exact semver string.
    Set ``allow_risky=true`` to also include C-grade versions.
    """
    version = resolve_version(
        conn, org_slug, skill_name, spec, allow_risky=allow_risky,
    )
    if version is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version '{spec}' not found for {org_slug}/{skill_name}",
        )

    download_url = generate_presigned_url(
        s3_client,
        settings.s3_bucket,
        version.s3_key,
    )

    return ResolveResponse(
        version=version.semver,
        download_url=download_url,
        checksum=version.checksum,
    )


@router.get(
    "/skills/{org_slug}/{skill_name}/audit-log",
    response_model=list[AuditLogResponse],
)
def get_audit_log(
    org_slug: str,
    skill_name: str,
    semver: str | None = Query(None),
    conn: Connection = Depends(get_connection),
) -> list[AuditLogResponse]:
    """Return evaluation audit log history for a skill.

    Public endpoint — no authentication required.
    """
    entries = find_audit_logs(conn, org_slug, skill_name, semver=semver)
    return [
        AuditLogResponse(
            id=str(entry.id),
            org_slug=entry.org_slug,
            skill_name=entry.skill_name,
            semver=entry.semver,
            grade=entry.grade,
            version_id=str(entry.version_id) if entry.version_id else None,
            check_results=entry.check_results,
            llm_reasoning=entry.llm_reasoning,
            publisher=entry.publisher,
            quarantine_s3_key=entry.quarantine_s3_key,
            created_at=entry.created_at.isoformat() if entry.created_at else None,
        )
        for entry in entries
    ]


@router.get(
    "/skills/{org_slug}/{skill_name}/eval-report",
    response_model=EvalReportResponse | None,
)
def get_eval_report_by_skill(
    org_slug: str,
    skill_name: str,
    semver: str = Query(..., description="Semantic version of the skill"),
    conn: Connection = Depends(get_connection),
) -> EvalReportResponse | None:
    """Get the eval report for a specific skill version.

    Public endpoint — no authentication required.
    Returns None if no eval report exists for this version.
    """
    report = find_eval_report_by_skill(conn, org_slug, skill_name, semver)
    if report is None:
        return None
    return _report_to_response(report)


@router.get(
    "/skills/{org_slug}/{skill_name}/versions/{semver}/eval-report",
    response_model=EvalReportResponse | None,
)
def get_eval_report_by_version_path(
    org_slug: str,
    skill_name: str,
    semver: str,
    conn: Connection = Depends(get_connection),
) -> EvalReportResponse | None:
    """Get the eval report for a specific skill version (path-based).

    Public endpoint — no authentication required.
    Returns None if no eval report exists for this version.
    """
    report = find_eval_report_by_skill(conn, org_slug, skill_name, semver)
    if report is None:
        return None
    return _report_to_response(report)


@router.delete(
    "/skills/{org_slug}/{skill_name}",
    response_model=DeleteAllResponse,
)
def delete_all_skill_versions(
    org_slug: str,
    skill_name: str,
    conn: Connection = Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> DeleteAllResponse:
    """Delete all versions of a skill and the skill record itself.

    Only organisation owners and admins can delete skills.
    """
    org = find_org_by_slug(conn, org_slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    member = find_org_member(conn, org.id, current_user.id)
    if member is None or member.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Only org owners and admins can delete skills",
        )

    skill = find_skill(conn, org.id, skill_name)
    if skill is None:
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{skill_name}' not found in {org_slug}",
        )

    s3_keys = delete_all_versions(conn, skill.id)
    delete_skill_record(conn, skill.id)

    for s3_key in s3_keys:
        delete_skill_zip(s3_client, settings.s3_bucket, s3_key)

    return DeleteAllResponse(
        org_slug=org_slug,
        skill_name=skill_name,
        versions_deleted=len(s3_keys),
    )


@router.delete(
    "/skills/{org_slug}/{skill_name}/{version}",
    response_model=DeleteResponse,
)
def delete_skill_version(
    org_slug: str,
    skill_name: str,
    version: str,
    conn: Connection = Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> DeleteResponse:
    """Delete a published skill version.

    Only organisation owners and admins can delete versions.
    """
    org = find_org_by_slug(conn, org_slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    member = find_org_member(conn, org.id, current_user.id)
    if member is None or member.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Only org owners and admins can delete versions",
        )

    skill = find_skill(conn, org.id, skill_name)
    if skill is None:
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{skill_name}' not found in {org_slug}",
        )

    deleted = delete_version(conn, skill.id, version)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Version '{version}' not found for {org_slug}/{skill_name}",
        )

    # Remove the zip from S3
    s3_key = build_s3_key(org_slug, skill_name, version)
    delete_skill_zip(s3_client, settings.s3_bucket, s3_key)

    return DeleteResponse(
        org_slug=org_slug,
        skill_name=skill_name,
        version=version,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_analyze_fn(settings: Settings):
    """Build a Gemini analyze callback if google_api_key is configured.

    Returns None if no API key is set, which causes the safety scan
    to run in strict regex-only mode.
    """
    if not settings.google_api_key:
        return None

    from decision_hub.infra.gemini import analyze_code_safety, create_gemini_client

    gemini_client = create_gemini_client(settings.google_api_key)

    def analyze_fn(snippets, skill_name, skill_description):
        return analyze_code_safety(
            gemini_client,
            snippets,
            skill_name,
            skill_description,
            model=settings.gemini_model,
        )

    return analyze_fn


def _build_analyze_prompt_fn(settings: Settings):
    """Build a Gemini prompt analyze callback if google_api_key is configured.

    Returns None if no API key is set, which causes the prompt safety scan
    to run in strict regex-only mode.
    """
    if not settings.google_api_key:
        return None

    from decision_hub.infra.gemini import analyze_prompt_safety, create_gemini_client

    gemini_client = create_gemini_client(settings.google_api_key)

    def analyze_prompt_fn(prompt_hits, skill_name, skill_description):
        return analyze_prompt_safety(
            gemini_client,
            prompt_hits,
            skill_name,
            skill_description,
            model=settings.gemini_model,
        )

    return analyze_prompt_fn


def _extract_runtime_config_dict(manifest) -> dict | None:
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


def _extract_assessment_config(manifest):
    """Extract eval config from manifest (returns None if not present)."""
    return manifest.evals


def _try_parse_assessment_cases(file_bytes: bytes):
    """Try to parse eval cases from zip. Returns empty tuple if evals/ not present."""
    from decision_hub.domain.skill_manifest import parse_eval_cases_from_zip

    try:
        return parse_eval_cases_from_zip(file_bytes)
    except ValueError:
        return ()


def _maybe_trigger_agent_assessment(
    background_tasks: BackgroundTasks,
    eval_config,
    eval_cases: tuple,
    file_bytes: bytes,
    version_id,
    org_slug: str,
    skill_name: str,
    settings: Settings,
    user_id,
):
    """Conditionally trigger background agent evaluation if eval config present."""
    if eval_config and eval_cases:
        background_tasks.add_task(
            _run_assessment_background,
            version_id=version_id,
            eval_config=eval_config,
            eval_cases=eval_cases,
            skill_zip=file_bytes,
            org_slug=org_slug,
            skill_name=skill_name,
            settings=settings,
            user_id=user_id,
        )
        return "pending"
    return None


def _run_assessment_background(
    version_id,
    eval_config,
    eval_cases: tuple,
    skill_zip: bytes,
    org_slug: str,
    skill_name: str,
    settings: Settings,
    user_id,
):
    """Background task to run agent assessments and store report."""
    from cryptography.fernet import Fernet

    from decision_hub.domain.evals import run_eval_pipeline
    from decision_hub.infra.database import create_engine, get_api_keys_for_eval
    from decision_hub.infra.modal_client import get_agent_config

    try:
        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            # Decrypt API keys needed by the target agent
            agent_config = get_agent_config(eval_config.agent)
            required_keys = [agent_config.key_env_var] if agent_config.key_env_var else []
            encrypted_keys = get_api_keys_for_eval(conn, user_id, required_keys)

            fernet = Fernet(settings.encryption_key.encode())
            agent_env_vars = {
                name: fernet.decrypt(value).decode()
                for name, value in encrypted_keys.items()
            }

            # Run the pipeline
            case_results, passed, total, total_duration_ms = run_eval_pipeline(
                skill_zip=skill_zip,
                eval_config=eval_config,
                eval_cases=eval_cases,
                agent_env_vars=agent_env_vars,
                org_slug=org_slug,
                skill_name=skill_name,
            )

            # Determine overall status
            all_passed = all(r["verdict"] == "pass" for r in case_results)
            status = "completed" if all_passed else "failed"

            # Store report
            insert_eval_report(
                conn,
                version_id=version_id,
                agent=eval_config.agent,
                judge_model=eval_config.judge_model,
                case_results=case_results,
                passed=passed,
                total=total,
                total_duration_ms=total_duration_ms,
                status=status,
            )
            conn.commit()

    except Exception as e:
        logger.error(f"Agent assessment failed for version {version_id}: {e}")
        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            update_eval_report(
                conn,
                version_id=version_id,
                status="failed",
                error_message=str(e),
            )
            conn.commit()


def _reconstruct_runtime_config(runtime_dict: dict | None):
    """Reconstruct a RuntimeConfig from a stored dict (for testing/validation)."""
    if runtime_dict is None:
        return None

    from decision_hub.models import DependencySpec, RuntimeConfig

    deps_dict = runtime_dict.get("dependencies")
    dependencies = None
    if deps_dict:
        dependencies = DependencySpec(
            system=tuple(deps_dict.get("system", [])),
            package_manager=deps_dict.get("package_manager", ""),
            packages=tuple(deps_dict.get("packages", [])),
            lockfile=deps_dict.get("lockfile"),
        )

    return RuntimeConfig(
        language=runtime_dict.get("language", ""),
        entrypoint=runtime_dict.get("entrypoint", ""),
        version_hint=runtime_dict.get("version_hint"),
        env=tuple(runtime_dict.get("env", [])),
        capabilities=tuple(runtime_dict.get("capabilities", [])),
        dependencies=dependencies,
        repair_strategy=runtime_dict.get("repair_strategy", "attempt_install"),
    )


def _report_to_response(report) -> EvalReportResponse:
    """Convert an EvalReport model to a response schema."""
    case_results_responses = [
        EvalCaseResultResponse(
            name=r["name"],
            description=r["description"],
            verdict=r["verdict"],
            reasoning=r["reasoning"],
            agent_output=r["agent_output"],
            agent_stderr=r["agent_stderr"],
            exit_code=r["exit_code"],
            duration_ms=r["duration_ms"],
            stage=r["stage"],
        )
        for r in report.case_results
    ]

    return EvalReportResponse(
        id=str(report.id),
        version_id=str(report.version_id),
        agent=report.agent,
        judge_model=report.judge_model,
        case_results=case_results_responses,
        passed=report.passed,
        total=report.total,
        total_duration_ms=report.total_duration_ms,
        status=report.status,
        error_message=report.error_message,
        created_at=report.created_at.isoformat() if report.created_at else None,
    )
