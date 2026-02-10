"""Organisation management routes -- create, list, and detail."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from decision_hub.api.deps import get_connection, get_current_user
from decision_hub.domain.orgs import validate_org_slug
from decision_hub.infra.database import (
    find_org_by_slug,
    insert_org_member,
    insert_organization,
    list_user_orgs,
)
from decision_hub.models import Organization, User

org_router = APIRouter(prefix="/v1/orgs", tags=["orgs"])


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


class OrgDetail(BaseModel):
    """Full organisation profile for a dedicated org page."""
    id: str
    slug: str
    is_personal: bool
    avatar_url: str | None = None
    email: str | None = None
    description: str | None = None
    blog: str | None = None
    github_synced_at: datetime | None = None


def _org_to_summary(org: Organization) -> OrgSummary:
    return OrgSummary(
        id=str(org.id),
        slug=org.slug,
        avatar_url=org.avatar_url,
        is_personal=org.is_personal,
    )


def _org_to_detail(org: Organization) -> OrgDetail:
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
    return [_org_to_summary(o) for o in orgs]


@org_router.get("/{slug}", response_model=OrgDetail)
def get_org(
    slug: str,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> OrgDetail:
    """Get full profile for a single organisation."""
    org = find_org_by_slug(conn, slug)
    if org is None:
        raise HTTPException(status_code=404, detail=f"Organisation '{slug}' not found")
    return _org_to_detail(org)
