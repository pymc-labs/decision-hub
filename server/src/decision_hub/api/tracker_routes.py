"""Tracker CRUD routes — create, list, update, and delete skill trackers."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import Connection

from decision_hub.api.deps import get_connection, get_current_user
from decision_hub.api.registry_service import require_org_membership
from decision_hub.domain.tracker import parse_github_repo_url
from decision_hub.infra.database import (
    delete_skill_tracker,
    find_skill_tracker,
    insert_skill_tracker,
    list_skill_trackers_for_user,
    update_skill_tracker,
)
from decision_hub.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/trackers", tags=["trackers"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CreateTrackerRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    poll_interval_minutes: int = 60
    org_slug: str | None = None


class UpdateTrackerRequest(BaseModel):
    enabled: bool | None = None
    branch: str | None = None
    poll_interval_minutes: int | None = None


class TrackerResponse(BaseModel):
    id: str
    user_id: str
    org_slug: str
    repo_url: str
    branch: str
    last_commit_sha: str | None
    poll_interval_minutes: int
    enabled: bool
    last_checked_at: str | None
    last_published_at: str | None
    last_error: str | None
    created_at: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracker_to_response(tracker) -> TrackerResponse:
    return TrackerResponse(
        id=str(tracker.id),
        user_id=str(tracker.user_id),
        org_slug=tracker.org_slug,
        repo_url=tracker.repo_url,
        branch=tracker.branch,
        last_commit_sha=tracker.last_commit_sha,
        poll_interval_minutes=tracker.poll_interval_minutes,
        enabled=tracker.enabled,
        last_checked_at=tracker.last_checked_at.isoformat() if tracker.last_checked_at else None,
        last_published_at=tracker.last_published_at.isoformat() if tracker.last_published_at else None,
        last_error=tracker.last_error,
        created_at=tracker.created_at.isoformat() if tracker.created_at else None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=TrackerResponse, status_code=201)
def create_tracker(
    body: CreateTrackerRequest,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> TrackerResponse:
    """Create a new skill tracker for a GitHub repo."""
    # Validate the URL is a GitHub repo
    try:
        parse_github_repo_url(body.repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if body.poll_interval_minutes < 5:
        raise HTTPException(
            status_code=422,
            detail="Poll interval must be at least 5 minutes",
        )

    org_slug = body.org_slug or _resolve_org(conn, current_user)

    # Verify user has org membership
    require_org_membership(conn, org_slug, current_user.id)

    try:
        tracker = insert_skill_tracker(
            conn,
            user_id=current_user.id,
            org_slug=org_slug,
            repo_url=body.repo_url,
            branch=body.branch,
            poll_interval_minutes=body.poll_interval_minutes,
        )
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(
                status_code=409,
                detail="A tracker for this repo and branch already exists",
            )
        raise

    return _tracker_to_response(tracker)


@router.get("", response_model=list[TrackerResponse])
def list_trackers(
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> list[TrackerResponse]:
    """List all trackers for the current user."""
    trackers = list_skill_trackers_for_user(conn, current_user.id)
    return [_tracker_to_response(t) for t in trackers]


@router.get("/{tracker_id}", response_model=TrackerResponse)
def get_tracker(
    tracker_id: str,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> TrackerResponse:
    """Get tracker details by ID."""
    tracker = find_skill_tracker(conn, UUID(tracker_id))
    if tracker is None or tracker.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Tracker not found")
    return _tracker_to_response(tracker)


@router.patch("/{tracker_id}", response_model=TrackerResponse)
def update_tracker(
    tracker_id: str,
    body: UpdateTrackerRequest,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> TrackerResponse:
    """Update tracker settings (enable/disable, change interval or branch)."""
    tracker = find_skill_tracker(conn, UUID(tracker_id))
    if tracker is None or tracker.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Tracker not found")

    if body.poll_interval_minutes is not None and body.poll_interval_minutes < 5:
        raise HTTPException(
            status_code=422,
            detail="Poll interval must be at least 5 minutes",
        )

    update_skill_tracker(
        conn, tracker.id,
        enabled=body.enabled,
        branch=body.branch,
        poll_interval_minutes=body.poll_interval_minutes,
    )

    updated = find_skill_tracker(conn, UUID(tracker_id))
    return _tracker_to_response(updated)


@router.delete("/{tracker_id}", status_code=204)
def remove_tracker(
    tracker_id: str,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a tracker."""
    tracker = find_skill_tracker(conn, UUID(tracker_id))
    if tracker is None or tracker.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Tracker not found")

    delete_skill_tracker(conn, tracker.id)


def _resolve_org(conn: Connection, user: User) -> str:
    """Pick the user's org for the tracker. Uses first org if only one."""
    from decision_hub.infra.database import list_user_orgs

    orgs = list_user_orgs(conn, user.id)
    if not orgs:
        raise HTTPException(
            status_code=400,
            detail="No namespaces available. Run 'dhub login' to refresh.",
        )
    if len(orgs) == 1:
        return orgs[0].slug

    raise HTTPException(
        status_code=400,
        detail=(
            f"Multiple namespaces available ({', '.join(o.slug for o in orgs)}). "
            "Set DHUB_DEFAULT_ORG or pass org_slug in the request."
        ),
    )
