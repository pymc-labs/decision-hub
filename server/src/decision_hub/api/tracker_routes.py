"""CRUD API routes for skill trackers."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from decision_hub.api.deps import get_connection, get_current_user
from decision_hub.domain.tracker import check_repo_accessible, parse_github_repo_url
from decision_hub.infra.database import (
    delete_skill_tracker,
    find_org_by_slug,
    find_org_member,
    find_skill_tracker,
    insert_skill_tracker,
    list_skill_trackers_for_user,
    list_user_orgs,
    update_skill_tracker,
)
from decision_hub.models import User

router = APIRouter(prefix="/v1/trackers", tags=["trackers"])


# ---------------------------------------------------------------------------
# Request / Response models
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
    warning: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracker_to_response(tracker) -> TrackerResponse:
    """Convert a SkillTracker model to a TrackerResponse."""
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


def _parse_uuid(value: str, name: str) -> UUID:
    """Parse a string as UUID, raising HTTP 422 on invalid input."""
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid {name}: {value}") from None


def _resolve_org_slug(conn: Connection, user: User, org_slug: str | None) -> str:
    """Resolve the target org slug for a tracker.

    If org_slug is provided, verifies membership. Otherwise auto-selects
    if the user has exactly one org.
    """
    if org_slug:
        org = find_org_by_slug(conn, org_slug)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        member = find_org_member(conn, org.id, user.id)
        if member is None:
            raise HTTPException(status_code=403, detail="You are not a member of this organization")
        return org_slug

    # Auto-resolve: user must have exactly 1 org
    orgs = list_user_orgs(conn, user.id)
    if len(orgs) == 0:
        raise HTTPException(status_code=400, detail="No organizations found. Create one first.")
    if len(orgs) > 1:
        raise HTTPException(
            status_code=400,
            detail="Multiple organizations found. Specify org_slug explicitly.",
        )
    return orgs[0].slug


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=TrackerResponse, status_code=201)
def create_tracker(
    body: CreateTrackerRequest,
    conn: Connection = Depends(get_connection),
    user: User = Depends(get_current_user),
) -> TrackerResponse:
    """Create a new tracker for a GitHub repository."""
    # Validate GitHub URL
    try:
        parse_github_repo_url(body.repo_url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None

    # Validate poll interval
    if body.poll_interval_minutes < 5:
        raise HTTPException(
            status_code=422,
            detail="poll_interval_minutes must be >= 5",
        )

    org_slug = _resolve_org_slug(conn, user, body.org_slug)

    try:
        tracker = insert_skill_tracker(
            conn,
            user_id=user.id,
            org_slug=org_slug,
            repo_url=body.repo_url,
            branch=body.branch,
            poll_interval_minutes=body.poll_interval_minutes,
        )
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="A tracker for this repo and branch already exists",
        ) from None

    logger.info("Created tracker {}/{} for user={}", body.repo_url, body.branch, user.id)

    response = _tracker_to_response(tracker)

    # Check if the repo is publicly accessible (best-effort, non-blocking)
    owner, repo = parse_github_repo_url(body.repo_url)
    if not check_repo_accessible(owner, repo):
        response.warning = (
            "This repo appears to be private. To enable tracking, add a GitHub token: dhub keys add GITHUB_TOKEN"
        )

    return response


@router.get("", response_model=list[TrackerResponse])
def list_trackers(
    conn: Connection = Depends(get_connection),
    user: User = Depends(get_current_user),
) -> list[TrackerResponse]:
    """List all trackers for the current user."""
    trackers = list_skill_trackers_for_user(conn, user.id)
    return [_tracker_to_response(t) for t in trackers]


@router.get("/{tracker_id}", response_model=TrackerResponse)
def get_tracker(
    tracker_id: str,
    conn: Connection = Depends(get_connection),
    user: User = Depends(get_current_user),
) -> TrackerResponse:
    """Get details of a specific tracker."""
    tid = _parse_uuid(tracker_id, "tracker_id")
    tracker = find_skill_tracker(conn, tid)
    if tracker is None or tracker.user_id != user.id:
        raise HTTPException(status_code=404, detail="Tracker not found")
    return _tracker_to_response(tracker)


@router.patch("/{tracker_id}", response_model=TrackerResponse)
def update_tracker(
    tracker_id: str,
    body: UpdateTrackerRequest,
    conn: Connection = Depends(get_connection),
    user: User = Depends(get_current_user),
) -> TrackerResponse:
    """Update a tracker's settings."""
    tid = _parse_uuid(tracker_id, "tracker_id")
    tracker = find_skill_tracker(conn, tid)
    if tracker is None or tracker.user_id != user.id:
        raise HTTPException(status_code=404, detail="Tracker not found")

    if body.poll_interval_minutes is not None and body.poll_interval_minutes < 5:
        raise HTTPException(
            status_code=422,
            detail="poll_interval_minutes must be >= 5",
        )

    update_skill_tracker(
        conn,
        tid,
        enabled=body.enabled,
        branch=body.branch,
        poll_interval_minutes=body.poll_interval_minutes,
    )

    updated = find_skill_tracker(conn, tid)
    assert updated is not None
    return _tracker_to_response(updated)


@router.delete("/{tracker_id}", status_code=204)
def delete_tracker(
    tracker_id: str,
    conn: Connection = Depends(get_connection),
    user: User = Depends(get_current_user),
) -> None:
    """Remove a tracker."""
    tid = _parse_uuid(tracker_id, "tracker_id")
    tracker = find_skill_tracker(conn, tid)
    if tracker is None or tracker.user_id != user.id:
        raise HTTPException(status_code=404, detail="Tracker not found")
    delete_skill_tracker(conn, tid)
