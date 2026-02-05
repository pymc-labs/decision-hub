"""Organisation management routes -- create, invite, accept."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import Connection

from decision_hub.api.deps import get_connection, get_current_user
from decision_hub.domain.orgs import can_invite, validate_org_slug, validate_role
from decision_hub.infra.database import (
    accept_invite,
    find_invite,
    find_org_by_slug,
    find_org_member,
    insert_org_invite,
    insert_org_member,
    insert_organization,
    list_user_orgs,
)
from decision_hub.models import User

org_router = APIRouter(prefix="/v1/orgs", tags=["orgs"])
invite_router = APIRouter(prefix="/v1/invites", tags=["invites"])


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


class InviteRequest(BaseModel):
    """Invite another GitHub user to an organisation."""
    github_username: str
    role: str = "member"


class InviteResponse(BaseModel):
    """Confirmation of a sent invite."""
    id: str
    status: str


class AcceptInviteResponse(BaseModel):
    """Confirmation that the invite was accepted."""
    org_id: str
    role: str


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
    validate_org_slug(body.slug)

    org = insert_organization(conn, body.slug, current_user.id)
    insert_org_member(conn, org.id, current_user.id, role="owner")
    conn.commit()

    return CreateOrgResponse(id=str(org.id), slug=org.slug)


@org_router.get("", response_model=list[OrgSummary])
def list_orgs(
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> list[OrgSummary]:
    """List organisations the authenticated user belongs to."""
    orgs = list_user_orgs(conn, current_user.id)
    return [OrgSummary(id=str(o.id), slug=o.slug) for o in orgs]


@org_router.post("/{slug}/invites", response_model=InviteResponse, status_code=201)
def invite_user(
    slug: str,
    body: InviteRequest,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> InviteResponse:
    """Invite a GitHub user to an organisation.

    The caller must be an owner or admin of the target organisation.
    """
    validate_role(body.role)

    org = find_org_by_slug(conn, slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    member = find_org_member(conn, org.id, current_user.id)
    if member is None:
        raise HTTPException(status_code=403, detail="You are not a member of this organisation")

    if not can_invite(member.role):
        raise HTTPException(
            status_code=403,
            detail="Insufficient permissions to invite users",
        )

    invite = insert_org_invite(conn, org.id, body.github_username)
    conn.commit()

    return InviteResponse(id=str(invite.id), status=invite.status)


# ---------------------------------------------------------------------------
# Invite acceptance (separate prefix)
# ---------------------------------------------------------------------------

@invite_router.post("/{invite_id}/accept", response_model=AcceptInviteResponse)
def accept_user_invite(
    invite_id: UUID,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> AcceptInviteResponse:
    """Accept a pending organisation invite.

    The invite's target GitHub username must match the authenticated user.
    """
    invite = find_invite(conn, invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")

    if invite.invitee_github_username != current_user.username:
        raise HTTPException(
            status_code=403,
            detail="This invite is not addressed to you",
        )

    if invite.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Invite already {invite.status}",
        )

    accept_invite(conn, invite.id)
    insert_org_member(conn, invite.org_id, current_user.id, role="member")
    conn.commit()

    return AcceptInviteResponse(org_id=str(invite.org_id), role="member")
