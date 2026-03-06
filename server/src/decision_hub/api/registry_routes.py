"""Skill registry routes -- publish, resolve, and delete."""

import json
import math
import zipfile
from datetime import UTC, datetime
from uuid import UUID

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
    require_org_membership,
)
from decision_hub.domain.publish import (
    build_s3_key,
    validate_semver,
    validate_skill_name,
)
from decision_hub.domain.publish_pipeline import (
    GauntletRejectionError,
    VersionConflictError,
    execute_publish,
)
from decision_hub.domain.search import format_trust_score, resolve_author_display
from decision_hub.infra.database import (
    delete_all_versions,
    delete_skill_access_grant,
    delete_version,
    fetch_all_skills_for_index,
    fetch_plugin_display_names,
    fetch_registry_stats,
    fetch_similar_skills,
    find_active_eval_runs_for_user,
    find_audit_logs,
    find_eval_report_by_skill,
    find_eval_run,
    find_eval_runs_for_version,
    find_org_by_slug,
    find_plugin_by_slug,
    find_skill,
    find_skill_by_slug,
    has_active_tracker_for_repo,
    increment_plugin_downloads,
    increment_skill_downloads,
    insert_skill_access_grant,
    list_granted_skill_ids,
    list_skill_access_grants_with_names,
    list_user_org_ids,
    resolve_latest_version,
    resolve_plugin_version,
    resolve_version,
    update_eval_run_status,
    update_skill_visibility,
)
from decision_hub.infra.database import (
    delete_skill as delete_skill_record,
)
from decision_hub.infra.storage import (
    compute_checksum,
    delete_skill_zip,
    generate_presigned_url,
    list_eval_log_chunks,
    read_eval_log_chunk,
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


def _enforce_similar_skills_rate_limit(request: Request) -> None:
    """Rate-limit the similar skills endpoint."""
    state = request.app.state
    if not hasattr(state, "_similar_skills_rate_limiter"):
        settings: Settings = state.settings
        state._similar_skills_rate_limiter = RateLimiter(
            max_requests=settings.similar_skills_rate_limit,
            window_seconds=settings.similar_skills_rate_window,
        )
    state._similar_skills_rate_limiter(request)


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


def _enforce_audit_log_rate_limit(request: Request) -> None:
    """Rate-limit the audit log endpoint."""
    state = request.app.state
    if not hasattr(state, "_audit_log_rate_limiter"):
        settings: Settings = state.settings
        state._audit_log_rate_limiter = RateLimiter(
            max_requests=settings.audit_log_rate_limit,
            window_seconds=settings.audit_log_rate_window,
        )
    state._audit_log_rate_limiter(request)


def _enforce_publish_rate_limit(request: Request) -> None:
    """Rate-limit the publish endpoint."""
    state = request.app.state
    if not hasattr(state, "_publish_rate_limiter"):
        settings: Settings = state.settings
        state._publish_rate_limiter = RateLimiter(
            max_requests=settings.publish_rate_limit,
            window_seconds=settings.publish_rate_window,
        )
    state._publish_rate_limiter(request)


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
    source_repo_url: str | None = None
    manifest_path: str | None = None
    source_repo_removed: bool = False
    github_stars: int | None = None
    github_forks: int | None = None
    github_watchers: int | None = None
    github_is_archived: bool | None = None
    github_license: str | None = None
    is_auto_synced: bool = False
    deprecated: bool = False
    deprecated_by_plugin_name: str | None = None
    deprecation_message: str | None = None


class SimilarSkillRef(BaseModel):
    """A skill similar to the queried skill, for the sidebar panel."""

    org_slug: str
    skill_name: str
    description: str
    safety_rating: str
    category: str = ""
    download_count: int = 0


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


class PaginatedAuditLogResponse(BaseModel):
    """Paginated response for the audit log endpoint."""

    items: list[AuditLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


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
@router.post(
    "/publish", response_model=PublishResponse, status_code=201, dependencies=[Depends(_enforce_publish_rate_limit)]
)
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
    source_repo_url = meta.get("source_repo_url")
    manifest_path = meta.get("manifest_path")
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
        result = execute_publish(
            conn=conn,
            s3_client=s3_client,
            settings=settings,
            org_id=org.id,
            org_slug=org_slug,
            skill_name=skill_name,
            version=version,
            checksum=checksum,
            file_bytes=file_bytes,
            publisher=current_user.username,
            user_id=current_user.id,
            visibility=visibility,
            source_repo_url=source_repo_url,
            manifest_path=manifest_path,
            auto_bump_version=False,
        )
    except (ValueError, zipfile.BadZipFile) as exc:
        logger.warning("Skill extraction failed for {}/{} v{}: {}", org_slug, skill_name, version, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GauntletRejectionError as exc:
        raise HTTPException(status_code=422, detail=f"Gauntlet checks failed: {exc.summary}") from exc
    except VersionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return PublishResponse(
        skill_id=str(result.skill_id),
        version_id=str(result.version_id),
        version=result.version,
        s3_key=result.s3_key,
        checksum=result.checksum,
        eval_status=result.eval_status,
        eval_report_status=result.eval_report_status,
        eval_run_id=result.eval_run_id,
    )


@public_router.get(
    "/stats",
)
def get_registry_stats(
    response: Response,
    conn: Connection = Depends(get_connection),
) -> dict:
    """Return aggregate registry statistics (total skills, orgs, downloads)."""
    response.headers["Cache-Control"] = "public, max-age=60"
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
    sort: str = Query("updated", pattern="^(updated|name|downloads|github_stars|safety_rating)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    include_deprecated: bool = Query(False),
    conn: Connection = Depends(get_connection),
    current_user: User | None = Depends(get_current_user_optional),
) -> PaginatedSkillsResponse:
    """List published skills with pagination and server-side filtering."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    # Pre-compute granted skill IDs once to avoid duplicate DB round-trips.
    granted_skill_ids = list_granted_skill_ids(conn, user_org_ids) if user_org_ids else None
    offset = (page - 1) * page_size

    # Single query: fetch_all_skills_for_index uses COUNT(*) OVER() to
    # return both the page rows and the full count in one round-trip.
    rows, total = fetch_all_skills_for_index(
        conn,
        user_org_ids=user_org_ids,
        granted_skill_ids=granted_skill_ids,
        search=search,
        org_slug=org,
        category=category,
        grade=grade,
        limit=page_size,
        offset=offset,
        sort=sort,
        sort_dir=sort_dir,
        include_deprecated=include_deprecated,
    )
    total_pages = math.ceil(total / page_size) if total > 0 else 1

    # Batch-resolve plugin display names for deprecated skills
    plugin_ids = [row["deprecated_by_plugin_id"] for row in rows if row.get("deprecated_by_plugin_id")]
    plugin_names = fetch_plugin_display_names(conn, plugin_ids) if plugin_ids else {}

    items = [
        SkillSummary(
            org_slug=row["org_slug"],
            skill_name=row["skill_name"],
            description=row.get("description", ""),
            latest_version=row["latest_version"],
            updated_at=row["created_at"].strftime("%Y-%m-%d %H:%M:%S") if row.get("created_at") else "",
            safety_rating=format_trust_score(row["eval_status"]),
            author=resolve_author_display(row.get("published_by", "")),
            download_count=row.get("download_count", 0),
            is_personal_org=row.get("is_personal_org", False),
            category=row.get("category", ""),
            visibility=row.get("visibility", "public"),
            source_repo_url=row.get("source_repo_url"),
            manifest_path=row.get("manifest_path"),
            source_repo_removed=row.get("source_repo_removed", False),
            github_stars=row.get("github_stars"),
            github_forks=row.get("github_forks"),
            github_watchers=row.get("github_watchers"),
            github_is_archived=row.get("github_is_archived"),
            github_license=row.get("github_license"),
            is_auto_synced=row.get("has_tracker", False),
            deprecated=row.get("deprecated", False),
            deprecated_by_plugin_name=plugin_names.get(row["deprecated_by_plugin_id"])
            if row.get("deprecated_by_plugin_id")
            else None,
            deprecation_message=row.get("deprecation_message"),
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

    # Resolve deprecating plugin name if applicable
    deprecated_by_plugin_name = None
    if skill.deprecated_by_plugin_id:
        names = fetch_plugin_display_names(conn, [skill.deprecated_by_plugin_id])
        deprecated_by_plugin_name = names.get(skill.deprecated_by_plugin_id)

    return SkillSummary(
        org_slug=org_slug,
        skill_name=skill_name,
        description=skill.description,
        latest_version=version.semver,
        updated_at=version.created_at.strftime("%Y-%m-%d %H:%M:%S") if version.created_at else "",
        safety_rating=format_trust_score(version.eval_status),
        author=resolve_author_display(version.published_by),
        download_count=skill.download_count,
        is_personal_org=org.is_personal if org else False,
        category=skill.category,
        visibility=skill.visibility,
        source_repo_url=skill.source_repo_url,
        manifest_path=skill.manifest_path,
        source_repo_removed=skill.source_repo_removed,
        github_stars=skill.github_stars,
        github_forks=skill.github_forks,
        github_watchers=skill.github_watchers,
        github_is_archived=skill.github_is_archived,
        github_license=skill.github_license,
        is_auto_synced=bool(skill.source_repo_url and has_active_tracker_for_repo(conn, skill.source_repo_url)),
        deprecated=skill.deprecated,
        deprecated_by_plugin_name=deprecated_by_plugin_name,
        deprecation_message=skill.deprecation_message,
    )


@public_router.get(
    "/skills/{org_slug}/{skill_name}/similar",
    response_model=list[SimilarSkillRef],
    dependencies=[Depends(_enforce_similar_skills_rate_limit)],
)
def get_similar_skills(
    org_slug: str,
    skill_name: str,
    conn: Connection = Depends(get_connection),
) -> list[SimilarSkillRef]:
    """Return up to 5 similar public skills by vector distance.

    Returns 404 if the skill does not exist or is not public.
    Returns an empty list if the skill has no stored embedding.
    """
    skill = find_skill_by_slug(conn, org_slug, skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found in {org_slug}")
    rows = fetch_similar_skills(conn, org_slug, skill_name, limit=5)
    return [
        SimilarSkillRef(
            org_slug=row["org_slug"],
            skill_name=row["skill_name"],
            description=row.get("description") or "",
            safety_rating=format_trust_score(row["eval_status"]),
            category=row.get("category") or "",
            download_count=row.get("download_count", 0),
        )
        for row in rows
    ]


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
    """Resolve a skill (or plugin) version and return a pre-signed download URL.

    Tries to match a plugin first, then falls back to skill resolution.
    This makes the endpoint a unified resolver for both entity types.
    """
    logger.debug("Resolving {}/{} spec={}", org_slug, skill_name, spec)

    # Try plugin first — plugins take precedence when name matches both
    plugin_ver = resolve_plugin_version(conn, org_slug, skill_name, spec)
    if plugin_ver is not None:
        plugin = find_plugin_by_slug(conn, org_slug, skill_name)
        if plugin:
            increment_plugin_downloads(conn, plugin.id)
        download_url = generate_presigned_url(s3_client, settings.s3_bucket, plugin_ver.s3_key)
        return ResolveResponse(
            version=plugin_ver.semver,
            checksum=plugin_ver.checksum,
            download_url=download_url,
        )

    # Fall back to skill resolution
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
    allow_risky: bool = Query(False),
    conn: Connection = Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
    current_user: User | None = Depends(get_current_user_optional),
) -> Response:
    """Download a skill zip file, proxied through the server to avoid CORS issues."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    version = resolve_version(conn, org_slug, skill_name, spec, allow_risky=allow_risky, user_org_ids=user_org_ids)
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
    response_model=PaginatedAuditLogResponse,
    dependencies=[Depends(_enforce_audit_log_rate_limit)],
)
def get_audit_log(
    org_slug: str,
    skill_name: str,
    semver: str | None = Query(None, max_length=50),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    conn: Connection = Depends(get_connection),
    current_user: User | None = Depends(get_current_user_optional),
) -> PaginatedAuditLogResponse:
    """Return evaluation audit log history for a skill."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    skill = find_skill_by_slug(conn, org_slug, skill_name, user_org_ids=user_org_ids)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found in {org_slug}")
    offset = (page - 1) * page_size
    entries, total = find_audit_logs(conn, org_slug, skill_name, semver=semver, limit=page_size, offset=offset)
    total_pages = math.ceil(total / page_size) if total > 0 else 1
    items = [
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
    return PaginatedAuditLogResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


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
    grants = list_skill_access_grants_with_names(conn, skill.id)
    return [
        AccessGrantListEntry(
            grantee_org_slug=grantee_slug,
            granted_by=username,
            created_at=created_at.isoformat() if created_at else None,
        )
        for grantee_slug, username, created_at in grants
    ]


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
