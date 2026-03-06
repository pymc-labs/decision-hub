"""Plugin registry routes -- publish, list, detail, resolve, versions, and audit."""

import json
import math
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.engine import Connection

from decision_hub.api.deps import (
    get_connection,
    get_current_user,
    get_current_user_optional,
    get_s3_client,
    get_settings,
)
from decision_hub.api.rate_limit import RateLimiter
from decision_hub.api.registry_service import require_org_membership
from decision_hub.domain.plugin_publish_pipeline import execute_plugin_publish
from decision_hub.domain.publish import validate_semver
from decision_hub.domain.publish_pipeline import (
    GauntletRejectionError,
    VersionConflictError,
)
from decision_hub.domain.search import format_trust_score, resolve_author_display
from decision_hub.infra.database import (
    fetch_paginated_plugins,
    find_plugin_audit_logs,
    find_plugin_by_slug,
    increment_plugin_downloads,
    list_plugin_versions,
    list_user_org_ids,
    resolve_plugin_version,
)
from decision_hub.infra.storage import compute_checksum, generate_presigned_url
from decision_hub.models import User
from decision_hub.settings import Settings
from dhub_core.validation import validate_skill_name

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PluginSummary(BaseModel):
    """Summary of a published plugin for the list endpoint."""

    org_slug: str
    plugin_name: str
    description: str
    latest_version: str
    updated_at: str
    safety_rating: str
    author_name: str | None = None
    download_count: int = 0
    category: str = ""
    platforms: list[str] = []
    skill_count: int = 0
    hook_count: int = 0
    agent_count: int = 0
    command_count: int = 0
    source_repo_url: str | None = None
    github_stars: int | None = None
    github_license: str | None = None
    is_auto_synced: bool = False


class PaginatedPluginsResponse(BaseModel):
    """Paginated response for the plugins list endpoint."""

    items: list[PluginSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


class PluginVersionResponse(BaseModel):
    """A single plugin version entry."""

    semver: str
    published_by: str
    eval_status: str | None
    gauntlet_summary: str | None = None
    created_at: str


class PluginResolveResponse(BaseModel):
    """Resolved plugin version with a pre-signed download URL."""

    version: str
    checksum: str
    download_url: str


class PluginPublishResponse(BaseModel):
    """Confirmation of a published plugin version."""

    plugin_id: str
    version_id: str
    version: str
    s3_key: str
    checksum: str
    eval_status: str
    deprecated_skills_count: int


class PluginAuditEntry(BaseModel):
    """A single audit log entry for a plugin."""

    semver: str
    grade: str
    publisher: str
    created_at: str
    quarantined: bool = False


# ---------------------------------------------------------------------------
# Rate limiters (lazy init from app settings, matching existing pattern)
# ---------------------------------------------------------------------------


def _enforce_list_plugins_rate_limit(request: Request) -> None:
    """Rate-limit the plugins list endpoint."""
    state = request.app.state
    if not hasattr(state, "_list_plugins_rate_limiter"):
        settings: Settings = state.settings
        state._list_plugins_rate_limiter = RateLimiter(
            max_requests=settings.list_plugins_rate_limit,
            window_seconds=settings.list_plugins_rate_window,
        )
    state._list_plugins_rate_limiter(request)


def _enforce_resolve_plugin_rate_limit(request: Request) -> None:
    """Rate-limit the plugin resolve endpoint."""
    state = request.app.state
    if not hasattr(state, "_resolve_plugin_rate_limiter"):
        settings: Settings = state.settings
        state._resolve_plugin_rate_limiter = RateLimiter(
            max_requests=settings.resolve_plugin_rate_limit,
            window_seconds=settings.resolve_plugin_rate_window,
        )
    state._resolve_plugin_rate_limiter(request)


def _enforce_publish_plugin_rate_limit(request: Request) -> None:
    """Rate-limit the plugin publish endpoint."""
    state = request.app.state
    if not hasattr(state, "_publish_plugin_rate_limiter"):
        settings: Settings = state.settings
        state._publish_plugin_rate_limiter = RateLimiter(
            max_requests=settings.publish_plugin_rate_limit,
            window_seconds=settings.publish_plugin_rate_window,
        )
    state._publish_plugin_rate_limiter(request)


def _enforce_plugin_detail_rate_limit(request: Request) -> None:
    """Rate-limit the plugin detail endpoint."""
    state = request.app.state
    if not hasattr(state, "_plugin_detail_rate_limiter"):
        settings: Settings = state.settings
        state._plugin_detail_rate_limiter = RateLimiter(
            max_requests=settings.plugin_detail_rate_limit,
            window_seconds=settings.plugin_detail_rate_window,
        )
    state._plugin_detail_rate_limiter(request)


def _enforce_plugin_versions_rate_limit(request: Request) -> None:
    """Rate-limit the plugin versions endpoint."""
    state = request.app.state
    if not hasattr(state, "_plugin_versions_rate_limiter"):
        settings: Settings = state.settings
        state._plugin_versions_rate_limiter = RateLimiter(
            max_requests=settings.plugin_versions_rate_limit,
            window_seconds=settings.plugin_versions_rate_window,
        )
    state._plugin_versions_rate_limiter(request)


def _enforce_plugin_audit_rate_limit(request: Request) -> None:
    """Rate-limit the plugin audit endpoint."""
    state = request.app.state
    if not hasattr(state, "_plugin_audit_rate_limiter"):
        settings: Settings = state.settings
        state._plugin_audit_rate_limiter = RateLimiter(
            max_requests=settings.plugin_audit_rate_limit,
            window_seconds=settings.plugin_audit_rate_window,
        )
    state._plugin_audit_rate_limiter(request)


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/v1/plugins", tags=["plugins"])
public_router = APIRouter(prefix="/v1/plugins", tags=["plugins"])


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@public_router.get(
    "",
    response_model=PaginatedPluginsResponse,
    dependencies=[Depends(_enforce_list_plugins_rate_limit)],
)
def list_plugins(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=200),
    org: str | None = Query(None, max_length=100),
    category: str | None = Query(None, max_length=100),
    platform: str | None = Query(None, max_length=50),
    grade: str | None = Query(None, max_length=1),
    sort: str = Query("updated", pattern="^(updated|name|downloads|github_stars)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    conn: Connection = Depends(get_connection),
    current_user: User | None = Depends(get_current_user_optional),
) -> PaginatedPluginsResponse:
    """List published plugins with pagination and filtering."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    offset = (page - 1) * page_size
    rows, total = fetch_paginated_plugins(
        conn,
        search=search,
        org_slug=org,
        category=category,
        platform=platform,
        grade=grade,
        limit=page_size,
        offset=offset,
        sort=sort,
        sort_dir=sort_dir,
        user_org_ids=user_org_ids,
    )
    total_pages = math.ceil(total / page_size) if total > 0 else 1
    items = [
        PluginSummary(
            org_slug=row["org_slug"],
            plugin_name=row["plugin_name"],
            description=row.get("description", ""),
            latest_version=row["latest_version"],
            updated_at=(row["published_at"].strftime("%Y-%m-%d %H:%M:%S") if row.get("published_at") else ""),
            safety_rating=format_trust_score(row.get("eval_status") or ""),
            author_name=row.get("author_name"),
            download_count=row.get("download_count", 0),
            category=row.get("category", ""),
            platforms=list(row.get("platforms") or []),
            skill_count=row.get("skill_count", 0),
            hook_count=row.get("hook_count", 0),
            agent_count=row.get("agent_count", 0),
            command_count=row.get("command_count", 0),
            source_repo_url=row.get("source_repo_url"),
            github_stars=row.get("github_stars"),
            github_license=row.get("github_license"),
            is_auto_synced=bool(row.get("has_tracker", False)),
        )
        for row in rows
    ]
    return PaginatedPluginsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@public_router.get(
    "/{org_slug}/{plugin_name}",
    dependencies=[Depends(_enforce_plugin_detail_rate_limit)],
)
def get_plugin_detail(
    org_slug: str,
    plugin_name: str,
    conn: Connection = Depends(get_connection),
    current_user: User | None = Depends(get_current_user_optional),
) -> dict:
    """Return detailed plugin info including component lists."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    plugin = find_plugin_by_slug(conn, org_slug, plugin_name)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found in {org_slug}")

    # Enforce visibility: if the plugin is org-private, only members can see it
    if plugin.visibility == "org" and (user_org_ids is None or plugin.org_id not in user_org_ids):
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found in {org_slug}")

    version = resolve_plugin_version(conn, org_slug, plugin_name, "latest", user_org_ids=user_org_ids)
    manifest = version.plugin_manifest if version else None

    return {
        "org_slug": org_slug,
        "plugin_name": plugin.name,
        "description": plugin.description,
        "author_name": plugin.author_name,
        "homepage": plugin.homepage,
        "license": plugin.license,
        "keywords": list(plugin.keywords),
        "platforms": list(plugin.platforms),
        "category": plugin.category,
        "download_count": plugin.download_count,
        "source_repo_url": plugin.source_repo_url,
        "github_stars": plugin.github_stars,
        "github_license": plugin.github_license,
        "latest_version": version.semver if version else None,
        "safety_rating": format_trust_score(version.eval_status or "") if version else "unknown",
        "skill_count": plugin.skill_count,
        "hook_count": plugin.hook_count,
        "agent_count": plugin.agent_count,
        "command_count": plugin.command_count,
        "skills": manifest.get("skills", []) if manifest else [],
        "hooks": manifest.get("hooks", []) if manifest else [],
        "agents": manifest.get("agents", []) if manifest else [],
        "commands": manifest.get("commands", []) if manifest else [],
    }


@public_router.get(
    "/{org_slug}/{plugin_name}/resolve",
    response_model=PluginResolveResponse,
    dependencies=[Depends(_enforce_resolve_plugin_rate_limit)],
)
def resolve_plugin(
    org_slug: str,
    plugin_name: str,
    spec: str = Query("latest", max_length=50),
    conn: Connection = Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
    current_user: User | None = Depends(get_current_user_optional),
) -> PluginResolveResponse:
    """Resolve a plugin version and return a download URL."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    version = resolve_plugin_version(conn, org_slug, plugin_name, spec, user_org_ids=user_org_ids)
    if version is None:
        raise HTTPException(
            status_code=404,
            detail=f"No version found for {org_slug}/{plugin_name}",
        )

    plugin = find_plugin_by_slug(conn, org_slug, plugin_name)
    if plugin:
        increment_plugin_downloads(conn, plugin.id)

    download_url = generate_presigned_url(s3_client, settings.s3_bucket, version.s3_key)
    return PluginResolveResponse(
        version=version.semver,
        checksum=version.checksum,
        download_url=download_url,
    )


@public_router.get(
    "/{org_slug}/{plugin_name}/versions",
    response_model=list[PluginVersionResponse],
    dependencies=[Depends(_enforce_plugin_versions_rate_limit)],
)
def get_plugin_versions(
    org_slug: str,
    plugin_name: str,
    conn: Connection = Depends(get_connection),
    current_user: User | None = Depends(get_current_user_optional),
) -> list[PluginVersionResponse]:
    """List all versions for a plugin, newest first."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    plugin = find_plugin_by_slug(conn, org_slug, plugin_name)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found in {org_slug}")
    if plugin.visibility == "org" and (user_org_ids is None or plugin.org_id not in user_org_ids):
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found in {org_slug}")

    versions = list_plugin_versions(conn, plugin.id)
    return [
        PluginVersionResponse(
            semver=v.semver,
            published_by=resolve_author_display(v.published_by),
            eval_status=v.eval_status,
            gauntlet_summary=v.gauntlet_summary,
            created_at=v.created_at.strftime("%Y-%m-%d %H:%M:%S") if v.created_at else "",
        )
        for v in versions
    ]


@public_router.get(
    "/{org_slug}/{plugin_name}/audit",
    response_model=list[PluginAuditEntry],
    dependencies=[Depends(_enforce_plugin_audit_rate_limit)],
)
def get_plugin_audit_log(
    org_slug: str,
    plugin_name: str,
    conn: Connection = Depends(get_connection),
    current_user: User | None = Depends(get_current_user_optional),
) -> list[PluginAuditEntry]:
    """Return audit log entries for a plugin."""
    user_org_ids = list_user_org_ids(conn, current_user.id) if current_user else None
    plugin = find_plugin_by_slug(conn, org_slug, plugin_name)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found in {org_slug}")
    if plugin.visibility == "org" and (user_org_ids is None or plugin.org_id not in user_org_ids):
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found in {org_slug}")
    entries = find_plugin_audit_logs(conn, plugin_name, org_slug)
    return [
        PluginAuditEntry(
            semver=e.semver,
            grade=e.grade,
            publisher=e.publisher,
            created_at=e.created_at.strftime("%Y-%m-%d %H:%M:%S") if e.created_at else "",
            quarantined=e.quarantine_s3_key is not None,
        )
        for e in entries
    ]


# ---------------------------------------------------------------------------
# Auth-required endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/publish",
    response_model=PluginPublishResponse,
    status_code=201,
    dependencies=[Depends(_enforce_publish_plugin_rate_limit)],
)
def publish_plugin(
    metadata: str = Form(...),
    zip_file: UploadFile = File(...),
    conn: Connection = Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> PluginPublishResponse:
    """Publish a new plugin version."""
    logger.info("Plugin publish request from user={}", current_user.username)
    if not settings.google_api_key:
        raise HTTPException(
            status_code=503,
            detail="LLM judge not configured. Cannot publish without LLM review.",
        )

    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid JSON in metadata: {exc}") from exc

    missing = [k for k in ("org_slug", "plugin_name", "version") if k not in meta]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required metadata keys: {', '.join(missing)}")

    org_slug = meta["org_slug"]
    plugin_name = meta["plugin_name"]
    version = meta["version"]
    source_repo_url = meta.get("source_repo_url")
    visibility = meta.get("visibility")
    if visibility is not None and visibility not in ("public", "org"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid visibility '{visibility}'. Must be 'public' or 'org'.",
        )

    try:
        validate_skill_name(plugin_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        validate_semver(version)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "Publishing plugin {}/{} v{} visibility={} by {}",
        org_slug,
        plugin_name,
        version,
        visibility,
        current_user.username,
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
        result = execute_plugin_publish(
            conn=conn,
            s3_client=s3_client,
            settings=settings,
            org_id=org.id,
            org_slug=org_slug,
            plugin_name=plugin_name,
            version=version,
            checksum=checksum,
            file_bytes=file_bytes,
            publisher=current_user.username,
            source_repo_url=source_repo_url,
            visibility=visibility,
        )
    except (ValueError, zipfile.BadZipFile) as exc:
        logger.warning(
            "Plugin extraction failed for {}/{} v{}: {}",
            org_slug,
            plugin_name,
            version,
            exc,
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GauntletRejectionError as exc:
        raise HTTPException(status_code=422, detail=f"Gauntlet checks failed: {exc.summary}") from exc
    except VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info(
        "Published plugin {}/{} v{} by {} — grade={} deprecated_skills={}",
        org_slug,
        plugin_name,
        result.version,
        current_user.username,
        result.eval_status,
        result.deprecated_skills_count,
    )

    return PluginPublishResponse(
        plugin_id=str(result.plugin_id),
        version_id=str(result.version_id),
        version=result.version,
        s3_key=result.s3_key,
        checksum=result.checksum,
        eval_status=result.eval_status,
        deprecated_skills_count=result.deprecated_skills_count,
    )
