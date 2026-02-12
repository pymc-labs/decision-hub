"""Skill registry routes -- publish, resolve, and delete."""

import json
import math
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from decision_hub.api.deps import (
    get_connection,
    get_current_user,
    get_current_user_optional,
    get_s3_client,
    get_settings,
)
from decision_hub.api.rate_limit import RateLimiter
from decision_hub.api.registry_service import (
    classify_skill_category,
    maybe_trigger_agent_assessment,
    parse_manifest_from_content,
    quarantine_rejected_skill,
    require_org_membership,
    run_gauntlet_pipeline,
)
from decision_hub.domain.publish import (
    build_s3_key,
    extract_for_evaluation,
    validate_semver,
    validate_skill_name,
)
from decision_hub.domain.search import format_trust_score
from decision_hub.domain.skill_manifest import extract_body, extract_description
from decision_hub.infra.database import (
    count_all_skills,
    delete_all_versions,
    delete_skill_access_grant,
    delete_version,
    fetch_all_skills_for_index,
    fetch_registry_stats,
    find_active_eval_runs_for_user,
    find_audit_logs,
    find_eval_report_by_skill,
    find_eval_run,
    find_eval_runs_for_version,
    find_org_by_slug,
    find_skill,
    find_skill_by_slug,
    find_version,
    increment_skill_downloads,
    insert_audit_log,
    insert_skill,
    insert_skill_access_grant,
    insert_version,
    list_skill_access_grants,
    list_user_org_ids,
    organizations_table,
    resolve_latest_version,
    resolve_version,
    update_eval_run_status,
    update_skill_category,
    update_skill_description,
    update_skill_visibility,
    users_table,
)
from decision_hub.infra.database import (
    delete_skill as delete_skill_record,
)
from decision_hub.infra.embeddings import generate_and_store_skill_embedding
from decision_hub.infra.storage import (
    compute_checksum,
    delete_skill_zip,
    generate_presigned_url,
    list_eval_log_chunks,
    read_eval_log_chunk,
    upload_skill_zip,
)
from decision_hub.infra.storage import (
    download_skill_zip as download_zip_from_s3,
)
from decision_hub.models import User
from decision_hub.settings import Settings

router = APIRouter(prefix="/v1", tags=["registry"])
public_router = APIRouter(prefix="/v1", tags=["registry"])


def _enforce_list_skills_rate_limit(request: Request) -> None:
    """Rate-limit the skills list endpoint."""
    state = request.app.state
    if not hasattr(state, "_list_skills_rate_limiter"):
        settings: Settings = state.settings
        state._list_skills_rate_limiter = RateLimiter(
            max_requests=settings.list_skills_rate_limit,
            window_seconds=settings.list_skills_rate_window,
        )
    state._list_skills_rate_limiter(request)


def _enforce_resolve_rate_limit(request: Request) -> None:
    """Rate-limit the resolve endpoint."""
    state = request.app.state
    if not hasattr(state, "_resolve_rate_limiter"):
        settings: Settings = state.settings
        state._resolve_rate_limiter = RateLimiter(
            max_requests=settings.resolve_rate_limit,
            window_seconds=settings.resolve_rate_window,
        )
    state._resolve_rate_limiter(request)


def _enforce_download_rate_limit(request: Request) -> None:
    """Rate-limit the download endpoint."""
    state = request.app.state
    if not hasattr(state, "_download_rate_limiter"):
        settings: Settings = state.settings
        state._download_rate_limiter = RateLimiter(
            max_requests=settings.download_rate_limit,
            window_seconds=settings.download_rate_window,
        )
    state._download_rate_limiter(request)


_VALID_VISIBILITIES = {"public", "org"}


def _parse_uuid(value: str, name: str) -> UUID:
    """Parse a UUID string, raising 422 with a clear message on invalid input."""
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID for {name}: '{value}'") from None


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class PublishResponse(BaseModel):
    """Confirmation of a published skill version."""

    skill_id: str
    version_id: str
    version: str
    s3_key: str
    checksum: str
    eval_status: str
    eval_report_status: str | None = None
    eval_run_id: str | None = None


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
    checksum: str


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
    download_count: int = 0
    is_personal_org: bool = False
    category: str = ""
    visibility: str = "public"


class PaginatedSkillsResponse(BaseModel):
    """Paginated response for the skills list endpoint."""

    items: list[SkillSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


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


class EvalRunResponse(BaseModel):
    """Eval run metadata."""

    id: str
    version_id: str
    agent: str
    judge_model: str
    status: str
    stage: str | None
    current_case: str | None
    current_case_index: int | None
    total_cases: int
    heartbeat_at: str | None
    log_seq: int
    error_message: str | None
    created_at: str | None
    completed_at: str | None


class EvalRunLogsResponse(BaseModel):
    """Paginated eval run log events."""

    events: list[dict]
    next_cursor: int
    run_status: str
    run_stage: str | None
    current_case: str | None


class VisibilityRequest(BaseModel):
    visibility: str


class VisibilityResponse(BaseModel):
    org_slug: str
    skill_name: str
    visibility: str


class AccessGrantRequest(BaseModel):
    grantee_org_slug: str


class AccessGrantResponse(BaseModel):
    org_slug: str
    skill_name: str
    grantee_org_slug: str


class AccessGrantListEntry(BaseModel):
    grantee_org_slug: str
    granted_by: str
    created_at: str | None


# Stale heartbeat threshold for zombie detection (5 minutes)
_STALE_HEARTBEAT_SECONDS = 300


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# Sync ``def`` so FastAPI runs it in a threadpool.  Using ``async def``
# would block the event loop during synchronous DB/S3/gauntlet calls and
# also requires ``await zip_file.read()`` which deadlocks under
# BaseHTTPMiddleware (see CLIVersionMiddleware docstring in app.py).
@router.post("/publish", response_model=PublishResponse, status_code=201)
def publish_skill(
    metadata: str = Form(...),
    zip_file: UploadFile = File(...),
    conn: Connection = Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> PublishResponse:
    """Publish a new skill version."""
    logger.info("Publish request from user={}", current_user.username)
    if not settings.google_api_key:
        raise HTTPException(
            status_code=503,
            detail="LLM judge not configured. Cannot publish without LLM review.",
        )

    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid JSON in metadata: {exc}") from exc

    missing = [k for k in ("org_slug", "skill_name", "version") if k not in meta]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required metadata keys: {', '.join(missing)}")
    org_slug, skill_name, version = meta["org_slug"], meta["skill_name"], meta["version"]
    visibility = meta.get("visibility")
    if visibility is not None and visibility not in _VALID_VISIBILITIES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid visibility '{visibility}'. Must be 'public' or 'org'.",
        )

    try:
        validate_skill_name(skill_name)
        validate_semver(version)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info(
        "Publishing {}/{} v{} visibility={} by {}", org_slug, skill_name, version, visibility, current_user.username
    )

    org = require_org_membership(conn, org_slug, current_user.id)

    # Read file contents with size limit (50 MB) and compute checksum
    max_upload_bytes = 50 * 1024 * 1024
    file_bytes = zip_file.file.read(max_upload_bytes + 1)
    if len(file_bytes) > max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds maximum size of {max_upload_bytes // (1024 * 1024)} MB",
        )
    checksum = compute_checksum(file_bytes)

    try:
        skill_md_content, source_files, lockfile_content = extract_for_evaluation(file_bytes)
    except ValueError as exc:
        logger.warning("Skill extraction failed for {}/{} v{}: {}", org_slug, skill_name, version, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    runtime_config_dict, eval_config, eval_cases = parse_manifest_from_content(
        skill_md_content,
        file_bytes,
    )

    description = extract_description(skill_md_content)
    skill_md_body = extract_body(skill_md_content)

    report, check_results_dicts, llm_reasoning = run_gauntlet_pipeline(
        skill_md_content,
        lockfile_content,
        source_files,
        skill_name,
        description,
        skill_md_body,
        settings,
    )
    logger.info(
        "Gauntlet result for {}/{} v{}: grade={} passed={}", org_slug, skill_name, version, report.grade, report.passed
    )

    if not report.passed:
        quarantine_rejected_skill(
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
            publisher=current_user.username,
        )

    # Classify the skill after gauntlet passes (non-critical, graceful fallback)
    category = classify_skill_category(skill_name, description, skill_md_body, settings)

    # Upsert skill record (find or create), then check for duplicate version
    eval_status = report.grade
    skill = find_skill(conn, org.id, skill_name)
    if skill is None:
        skill = insert_skill(
            conn, org.id, skill_name, description, category=category, visibility=visibility or "public"
        )
    else:
        update_skill_description(conn, skill.id, description)
        update_skill_category(conn, skill.id, category)
        if visibility is not None:
            update_skill_visibility(conn, skill.id, visibility)

    if find_version(conn, skill.id, version) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Version {version} already exists for {org_slug}/{skill_name}",
        )

    # Generate embedding (fail-open: never blocks publish)
    generate_and_store_skill_embedding(conn, skill.id, skill_name, org_slug, category, description, settings)

    # Upload to S3 and record the version
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
            published_by=current_user.username,
            eval_status=eval_status,
        )
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"Version {version} already exists for {org_slug}/{skill_name}",
        ) from None

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

    # Commit now so the version row is visible to the background eval thread.
    conn.commit()

    eval_report_status, eval_run_id = maybe_trigger_agent_assessment(
        eval_config=eval_config,
        eval_cases=eval_cases,
        s3_key=s3_key,
        s3_bucket=settings.s3_bucket,
        version_id=version_record.id,
        org_slug=org_slug,
        skill_name=skill_name,
        settings=settings,
        user_id=current_user.id,
    )

    logger.info(
        "Published {}/{} v{} — version_id={} grade={} eval_run={}",
        org_slug,
        skill_name,
        version,
        version_record.id,
        eval_status,
        eval_run_id,
    )
    return PublishResponse(
        skill_id=str(skill.id),
        version_id=str(version_record.id),
        version=version_record.semver,
        s3_key=version_record.s3_key,
        checksum=version_record.checksum,
        eval_status=eval_status,
        eval_report_status=eval_report_status,
        eval_run_id=eval_run_id,
    )


@public_router.get(
    "/stats",
)
def get_registry_stats(
    conn: Connection = Depends(get_connection),
) -> dict:
    """Return aggregate registry statistics (total skills, orgs, downloads)."""
    return fetch_registry_stats(conn)


@public_router.get(
    "/skills",
    response_model=PaginatedSkillsResponse,
    dependencies=[Depends(_enforce_list_skills_rate_limit)],
)
def list_skills(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=200),
    org: str | None = Query(None, max_length=100),
    category: str | None = Query(None, max_length=100),
    grade: str | None = Query(None, max_length=1),
    sort: str = Query("updated", pattern="^(updated|name|downloads)$"),
    conn: Connection = Depends(get_connection),
    current_user: User | None = Depends(get_current_user_optional),
) -> PaginatedSkillsResponse:
    """List published skills with pagination and server-side filtering."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None

    total = count_all_skills(
        conn,
        user_org_ids=user_org_ids,
        search=search,
        org_slug=org,
        category=category,
        grade=grade,
    )
    total_pages = math.ceil(total / page_size) if total > 0 else 1
    offset = (page - 1) * page_size

    rows = fetch_all_skills_for_index(
        conn,
        user_org_ids=user_org_ids,
        search=search,
        org_slug=org,
        category=category,
        grade=grade,
        limit=page_size,
        offset=offset,
        sort=sort,
    )
    items = [
        SkillSummary(
            org_slug=row["org_slug"],
            skill_name=row["skill_name"],
            description=row.get("description", ""),
            latest_version=row["latest_version"],
            updated_at=row["created_at"].strftime("%Y-%m-%d %H:%M:%S") if row.get("created_at") else "",
            safety_rating=format_trust_score(row["eval_status"]),
            author=row.get("published_by", ""),
            download_count=row.get("download_count", 0),
            is_personal_org=row.get("is_personal_org", False),
            category=row.get("category", ""),
            visibility=row.get("visibility", "public"),
        )
        for row in rows
    ]
    return PaginatedSkillsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@public_router.get(
    "/skills/{org_slug}/{skill_name}/summary",
    response_model=SkillSummary,
)
def get_skill_summary(
    org_slug: str,
    skill_name: str,
    conn: Connection = Depends(get_connection),
    current_user: User | None = Depends(get_current_user_optional),
) -> SkillSummary:
    """Return a single skill summary by org slug and skill name."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    skill = find_skill_by_slug(conn, org_slug, skill_name, user_org_ids=user_org_ids)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found in {org_slug}")
    version = resolve_latest_version(conn, org_slug, skill_name, user_org_ids=user_org_ids)
    if version is None:
        raise HTTPException(status_code=404, detail=f"No versions found for {org_slug}/{skill_name}")

    org = find_org_by_slug(conn, org_slug)
    return SkillSummary(
        org_slug=org_slug,
        skill_name=skill_name,
        description=skill.description,
        latest_version=version.semver,
        updated_at=version.created_at.strftime("%Y-%m-%d %H:%M:%S") if version.created_at else "",
        safety_rating=format_trust_score(version.eval_status),
        author=version.published_by,
        download_count=skill.download_count,
        is_personal_org=org.is_personal if org else False,
        category=skill.category,
        visibility=skill.visibility,
    )


@public_router.get(
    "/skills/{org_slug}/{skill_name}/latest-version",
    response_model=LatestVersionResponse,
)
def get_latest_version(
    org_slug: str,
    skill_name: str,
    conn: Connection = Depends(get_connection),
    current_user: User | None = Depends(get_current_user_optional),
) -> LatestVersionResponse:
    """Return the latest published version of a skill."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    version = resolve_latest_version(conn, org_slug, skill_name, user_org_ids=user_org_ids)
    if version is None:
        raise HTTPException(
            status_code=404,
            detail=f"No versions found for {org_slug}/{skill_name}",
        )
    return LatestVersionResponse(version=version.semver, checksum=version.checksum)


@public_router.get(
    "/resolve/{org_slug}/{skill_name}",
    response_model=ResolveResponse,
    dependencies=[Depends(_enforce_resolve_rate_limit)],
)
def resolve_skill(
    org_slug: str,
    skill_name: str,
    spec: str = Query("latest", max_length=50),
    allow_risky: bool = Query(False),
    conn: Connection = Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
    current_user: User | None = Depends(get_current_user_optional),
) -> ResolveResponse:
    """Resolve a skill version and return a pre-signed download URL."""
    logger.debug("Resolving {}/{} spec={}", org_slug, skill_name, spec)
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    version = resolve_version(
        conn,
        org_slug,
        skill_name,
        spec,
        allow_risky=allow_risky,
        user_org_ids=user_org_ids,
    )
    if version is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version '{spec}' not found for {org_slug}/{skill_name}",
        )

    increment_skill_downloads(conn, version.skill_id)

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


@public_router.get(
    "/skills/{org_slug}/{skill_name}/download",
    dependencies=[Depends(_enforce_download_rate_limit)],
)
def download_skill(
    org_slug: str,
    skill_name: str,
    spec: str = Query("latest", max_length=50),
    conn: Connection = Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
    current_user: User | None = Depends(get_current_user_optional),
) -> Response:
    """Download a skill zip file, proxied through the server to avoid CORS issues."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    version = resolve_version(conn, org_slug, skill_name, spec, allow_risky=True, user_org_ids=user_org_ids)
    if version is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version '{spec}' not found for {org_slug}/{skill_name}",
        )

    increment_skill_downloads(conn, version.skill_id)

    data = download_zip_from_s3(s3_client, settings.s3_bucket, version.s3_key)
    filename = f"{org_slug}_{skill_name}_{version.semver}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@public_router.get(
    "/skills/{org_slug}/{skill_name}/audit-log",
    response_model=list[AuditLogResponse],
)
def get_audit_log(
    org_slug: str,
    skill_name: str,
    semver: str | None = Query(None, max_length=50),
    conn: Connection = Depends(get_connection),
    current_user: User | None = Depends(get_current_user_optional),
) -> list[AuditLogResponse]:
    """Return evaluation audit log history for a skill."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    skill = find_skill_by_slug(conn, org_slug, skill_name, user_org_ids=user_org_ids)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found in {org_slug}")
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


@public_router.get(
    "/skills/{org_slug}/{skill_name}/eval-report",
    response_model=EvalReportResponse | None,
)
def get_eval_report_by_skill(
    org_slug: str,
    skill_name: str,
    semver: str = Query(..., max_length=50, description="Semantic version of the skill"),
    conn: Connection = Depends(get_connection),
    current_user: User | None = Depends(get_current_user_optional),
) -> EvalReportResponse | None:
    """Get the eval report for a specific skill version."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    skill = find_skill_by_slug(conn, org_slug, skill_name, user_org_ids=user_org_ids)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found in {org_slug}")
    report = find_eval_report_by_skill(conn, org_slug, skill_name, semver)
    if report is None:
        return None
    return _report_to_response(report)


@public_router.get(
    "/skills/{org_slug}/{skill_name}/versions/{semver}/eval-report",
    response_model=EvalReportResponse | None,
)
def get_eval_report_by_version_path(
    org_slug: str,
    skill_name: str,
    semver: str,
    conn: Connection = Depends(get_connection),
    current_user: User | None = Depends(get_current_user_optional),
) -> EvalReportResponse | None:
    """Get the eval report for a specific skill version (path-based)."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    skill = find_skill_by_slug(conn, org_slug, skill_name, user_org_ids=user_org_ids)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found in {org_slug}")
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
    """Delete all versions of a skill and the skill record itself."""
    logger.info("Delete all versions of {}/{} by {}", org_slug, skill_name, current_user.username)
    org = require_org_membership(conn, org_slug, current_user.id, admin_only=True)
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
    """Delete a published skill version."""
    logger.info("Delete {}/{} v{} by {}", org_slug, skill_name, version, current_user.username)
    org = require_org_membership(conn, org_slug, current_user.id, admin_only=True)
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
# Eval run endpoints
# ---------------------------------------------------------------------------


def _run_to_response(run) -> EvalRunResponse:
    """Convert an EvalRun model to a response schema."""
    return EvalRunResponse(
        id=str(run.id),
        version_id=str(run.version_id),
        agent=run.agent,
        judge_model=run.judge_model,
        status=run.status,
        stage=run.stage,
        current_case=run.current_case,
        current_case_index=run.current_case_index,
        total_cases=run.total_cases,
        heartbeat_at=run.heartbeat_at.isoformat() if run.heartbeat_at else None,
        log_seq=run.log_seq,
        error_message=run.error_message,
        created_at=run.created_at.isoformat() if run.created_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


def _check_zombie(conn: Connection, run) -> str:
    """Check if a running eval run has a stale heartbeat (zombie).

    If heartbeat_at is older than _STALE_HEARTBEAT_SECONDS, marks the
    run as failed and returns "failed". Otherwise returns run.status.
    """
    if run.status not in ("running", "judging", "provisioning"):
        return run.status
    if run.heartbeat_at is None:
        return run.status
    elapsed = (datetime.now(UTC) - run.heartbeat_at).total_seconds()
    if elapsed > _STALE_HEARTBEAT_SECONDS:
        update_eval_run_status(
            conn,
            run.id,
            status="failed",
            error_message=f"Stale heartbeat ({int(elapsed)}s). Worker may have crashed.",
            completed_at=datetime.now(UTC),
        )
        return "failed"
    return run.status


@router.get("/eval-runs/{run_id}", response_model=EvalRunResponse)
def get_eval_run(
    run_id: str,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> EvalRunResponse:
    """Get eval run metadata by run ID."""
    parsed_id = _parse_uuid(run_id, "run_id")
    run = find_eval_run(conn, parsed_id)
    if run is None or run.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Eval run not found")
    _check_zombie(conn, run)
    # Re-read after potential zombie update
    run = find_eval_run(conn, parsed_id)
    return _run_to_response(run)


@router.get("/eval-runs/{run_id}/logs", response_model=EvalRunLogsResponse)
def get_eval_run_logs(
    run_id: str,
    cursor: int = Query(0, ge=0, description="Return events with seq > cursor"),
    conn: Connection = Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> EvalRunLogsResponse:
    """Get eval run log events with cursor-based pagination."""
    parsed_id = _parse_uuid(run_id, "run_id")
    run = find_eval_run(conn, parsed_id)
    if run is None or run.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Eval run not found")

    # Zombie detection on read
    effective_status = _check_zombie(conn, run)

    # Fetch all S3 chunks for the run. The cursor is an event sequence number
    # (e.g. 50), not a chunk file sequence number (e.g. 3), so we can't use
    # it to filter S3 files. Instead, fetch all chunks and filter events in memory.
    chunks = list_eval_log_chunks(
        s3_client,
        settings.s3_bucket,
        run.log_s3_prefix,
        after_seq=0,
    )

    # Read and parse events from each chunk, filtering by cursor
    all_events: list[dict] = []
    max_seq = cursor
    for _chunk_seq, s3_key in chunks:
        content = read_eval_log_chunk(s3_client, settings.s3_bucket, s3_key)
        for line in content.strip().split("\n"):
            if line.strip():
                event = json.loads(line)
                event_seq = event.get("seq", 0)
                if event_seq > cursor:
                    all_events.append(event)
                if event_seq > max_seq:
                    max_seq = event_seq

    return EvalRunLogsResponse(
        events=all_events,
        next_cursor=max_seq,
        run_status=effective_status,
        run_stage=run.stage,
        current_case=run.current_case,
    )


@router.get("/eval-runs", response_model=list[EvalRunResponse])
def list_eval_runs(
    version_id: str | None = Query(None, description="Filter by version ID"),
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> list[EvalRunResponse]:
    """List eval runs, optionally filtered by version ID."""
    if version_id is not None:
        parsed_vid = _parse_uuid(version_id, "version_id")
        runs = find_eval_runs_for_version(conn, parsed_vid)
        runs = [r for r in runs if r.user_id == current_user.id]
    else:
        runs = find_active_eval_runs_for_user(conn, current_user.id)
    return [_run_to_response(r) for r in runs]


# ---------------------------------------------------------------------------
# Visibility and access grant endpoints
# ---------------------------------------------------------------------------


@router.put(
    "/skills/{org_slug}/{skill_name}/visibility",
    response_model=VisibilityResponse,
)
def change_visibility(
    org_slug: str,
    skill_name: str,
    body: VisibilityRequest,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> VisibilityResponse:
    """Change the visibility of a published skill."""
    if body.visibility not in _VALID_VISIBILITIES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid visibility '{body.visibility}'. Must be 'public' or 'org'.",
        )
    org = require_org_membership(conn, org_slug, current_user.id, admin_only=True)
    skill = find_skill(conn, org.id, skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found in {org_slug}")
    update_skill_visibility(conn, skill.id, body.visibility)
    logger.info("Visibility changed {}/{} -> {} by {}", org_slug, skill_name, body.visibility, current_user.username)
    return VisibilityResponse(org_slug=org_slug, skill_name=skill_name, visibility=body.visibility)


@router.post(
    "/skills/{org_slug}/{skill_name}/access",
    response_model=AccessGrantResponse,
    status_code=201,
)
def grant_access(
    org_slug: str,
    skill_name: str,
    body: AccessGrantRequest,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> AccessGrantResponse:
    """Grant an organisation access to a private skill."""
    org = require_org_membership(conn, org_slug, current_user.id, admin_only=True)
    skill = find_skill(conn, org.id, skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found in {org_slug}")
    grantee_org = find_org_by_slug(conn, body.grantee_org_slug)
    if grantee_org is None:
        raise HTTPException(status_code=404, detail=f"Organisation '{body.grantee_org_slug}' not found")
    try:
        insert_skill_access_grant(conn, skill.id, grantee_org.id, current_user.id)
    except IntegrityError:
        raise HTTPException(status_code=409, detail=f"Access already granted to '{body.grantee_org_slug}'") from None
    logger.info("Access granted {}/{} -> {} by {}", org_slug, skill_name, body.grantee_org_slug, current_user.username)
    return AccessGrantResponse(org_slug=org_slug, skill_name=skill_name, grantee_org_slug=body.grantee_org_slug)


@router.delete(
    "/skills/{org_slug}/{skill_name}/access/{grantee_org_slug}",
    response_model=AccessGrantResponse,
)
def revoke_access(
    org_slug: str,
    skill_name: str,
    grantee_org_slug: str,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> AccessGrantResponse:
    """Revoke an organisation's access to a private skill."""
    org = require_org_membership(conn, org_slug, current_user.id, admin_only=True)
    skill = find_skill(conn, org.id, skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found in {org_slug}")
    grantee_org = find_org_by_slug(conn, grantee_org_slug)
    if grantee_org is None:
        raise HTTPException(status_code=404, detail=f"Organisation '{grantee_org_slug}' not found")
    deleted = delete_skill_access_grant(conn, skill.id, grantee_org.id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No access grant found for '{grantee_org_slug}'")
    logger.info("Access revoked {}/{} -> {} by {}", org_slug, skill_name, grantee_org_slug, current_user.username)
    return AccessGrantResponse(org_slug=org_slug, skill_name=skill_name, grantee_org_slug=grantee_org_slug)


@router.get(
    "/skills/{org_slug}/{skill_name}/access",
    response_model=list[AccessGrantListEntry],
)
def list_access(
    org_slug: str,
    skill_name: str,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> list[AccessGrantListEntry]:
    """List all access grants for a skill."""
    org = require_org_membership(conn, org_slug, current_user.id, admin_only=True)
    skill = find_skill(conn, org.id, skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found in {org_slug}")
    grants = list_skill_access_grants(conn, skill.id)
    results = []
    for grant in grants:
        grantee_org_slug_val = conn.execute(
            sa.select(organizations_table.c.slug).where(organizations_table.c.id == grant.grantee_org_id)
        ).scalar()
        granted_by_username = conn.execute(
            sa.select(users_table.c.username).where(users_table.c.id == grant.granted_by)
        ).scalar()
        results.append(
            AccessGrantListEntry(
                grantee_org_slug=grantee_org_slug_val or str(grant.grantee_org_id),
                granted_by=granted_by_username or str(grant.granted_by),
                created_at=grant.created_at.isoformat() if grant.created_at else None,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------


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
