"""Organisation management routes -- create, list, and detail."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from decision_hub.api.deps import get_connection, get_current_user
from decision_hub.domain.orgs import validate_org_slug
from decision_hub.infra.database import (
    fetch_org_stats,
    find_org_by_slug,
    find_org_member,
    insert_org_member,
    insert_organization,
    list_all_org_profiles,
    list_user_orgs,
    org_has_public_skills,
)
from decision_hub.models import User

org_router = APIRouter(prefix="/v1/orgs", tags=["orgs"])
org_public_router = APIRouter(prefix="/v1/orgs", tags=["orgs"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CreateOrgRequest(BaseModel):
    """Payload to create a new organisation."""

    slug: str


class CreateOrgResponse(BaseModel):
    """Confirmation of a newly-created organisation."""

    id: str
    slug: str


class OrgSummary(BaseModel):
    """Summary of an organisation for listing."""

    id: str
    slug: str
    avatar_url: str | None = None
    is_personal: bool = False


class OrgProfile(BaseModel):
    """Public org profile — no auth required."""

    slug: str
    is_personal: bool
    avatar_url: str | None = None
    description: str | None = None
    blog: str | None = None


class OrgDetail(BaseModel):
    """Full organisation profile."""

    id: str
    slug: str
    is_personal: bool
    avatar_url: str | None = None
    email: str | None = None
    description: str | None = None
    blog: str | None = None
    github_synced_at: datetime | None = None


# ---------------------------------------------------------------------------
# Organisation endpoints
# ---------------------------------------------------------------------------


@org_router.post("", response_model=CreateOrgResponse, status_code=201)
def create_organisation(
    body: CreateOrgRequest,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> CreateOrgResponse:
    """Create an organisation and register the caller as owner."""
    try:
        validate_org_slug(body.slug)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Only allow creating orgs matching the user's GitHub username or org memberships
    allowed_slugs = {current_user.username.lower()} | {org_name.lower() for org_name in current_user.github_orgs}
    if body.slug.lower() not in allowed_slugs:
        raise HTTPException(
            status_code=403,
            detail="You can only create orgs matching your GitHub username or org memberships",
        )

    try:
        org = insert_organization(conn, body.slug, current_user.id)
        insert_org_member(conn, org.id, current_user.id, role="owner")
    except IntegrityError:
        logger.warning("Duplicate org slug '{}' by user={}", body.slug, current_user.username)
        raise HTTPException(
            status_code=409,
            detail=f"Organisation '{body.slug}' already exists",
        ) from None

    return CreateOrgResponse(id=str(org.id), slug=org.slug)


@org_router.get("", response_model=list[OrgSummary])
def list_orgs(
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> list[OrgSummary]:
    """List organisations the authenticated user belongs to."""
    orgs = list_user_orgs(conn, current_user.id)
    return [
        OrgSummary(
            id=str(o.id),
            slug=o.slug,
            avatar_url=o.avatar_url,
            is_personal=o.is_personal,
        )
        for o in orgs
    ]


class OrgStatsEntry(BaseModel):
    """Aggregated statistics for a single org."""

    slug: str
    is_personal: bool
    avatar_url: str | None = None
    skill_count: int
    total_downloads: int
    latest_update: str | None = None


class OrgStatsResponse(BaseModel):
    """Response for the /orgs/stats endpoint."""

    items: list[OrgStatsEntry]


@org_public_router.get("/stats", response_model=OrgStatsResponse)
def get_org_stats(
    search: str | None = Query(None, max_length=200),
    type_filter: str = Query("all", pattern="^(orgs|users|all)$"),
    conn: Connection = Depends(get_connection),
) -> OrgStatsResponse:
    """Return aggregated org statistics for the orgs listing page."""
    rows = fetch_org_stats(conn, search=search, type_filter=type_filter)
    items = [
        OrgStatsEntry(
            slug=row["slug"],
            is_personal=row["is_personal"],
            avatar_url=row["avatar_url"],
            skill_count=row["skill_count"],
            total_downloads=row["total_downloads"],
            latest_update=row["latest_update"],
        )
        for row in rows
    ]
    return OrgStatsResponse(items=items)


@org_public_router.get("/profiles", response_model=list[OrgProfile])
def list_org_profiles(
    conn: Connection = Depends(get_connection),
) -> list[OrgProfile]:
    """Public profiles for all organisations (single request, no auth)."""
    orgs = list_all_org_profiles(conn)
    return [
        OrgProfile(
            slug=o.slug,
            is_personal=o.is_personal,
            avatar_url=o.avatar_url,
            description=o.description,
            blog=o.blog,
        )
        for o in orgs
    ]


@org_public_router.get("/{slug}/profile", response_model=OrgProfile)
def get_org_profile(
    slug: str,
    conn: Connection = Depends(get_connection),
) -> OrgProfile:
    """Public profile for an organisation."""
    org = find_org_by_slug(conn, slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")
    if not org_has_public_skills(conn, org.id):
        raise HTTPException(status_code=404, detail="Organisation not found")
    return OrgProfile(
        slug=org.slug,
        is_personal=org.is_personal,
        avatar_url=org.avatar_url,
        description=org.description,
        blog=org.blog,
    )


@org_router.get("/{slug}", response_model=OrgDetail)
def get_org(
    slug: str,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> OrgDetail:
    """Get full profile for an organisation."""
    org = find_org_by_slug(conn, slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    # Only members can view the org detail (avoids leaking org existence)
    member = find_org_member(conn, org.id, current_user.id)
    if member is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    return OrgDetail(
        id=str(org.id),
        slug=org.slug,
        is_personal=org.is_personal,
        avatar_url=org.avatar_url,
        email=org.email,
        description=org.description,
        blog=org.blog,
        github_synced_at=org.github_synced_at,
    )
