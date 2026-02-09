"""Organisation management routes -- create and list."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from decision_hub.api.deps import get_connection, get_current_user
from decision_hub.domain.orgs import validate_org_slug
from decision_hub.infra.database import (
    insert_org_member,
    insert_organization,
    list_user_orgs,
)
from decision_hub.models import User

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
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        org = insert_organization(conn, body.slug, current_user.id)
        insert_org_member(conn, org.id, current_user.id, role="owner")
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"Organisation '{body.slug}' already exists",
        )

    return CreateOrgResponse(id=str(org.id), slug=org.slug)


@org_router.get("", response_model=list[OrgSummary])
def list_orgs(
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> list[OrgSummary]:
    """List organisations the authenticated user belongs to."""
    orgs = list_user_orgs(conn, current_user.id)
    return [OrgSummary(id=str(o.id), slug=o.slug) for o in orgs]
