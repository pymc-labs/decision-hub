"""Organization validation and sync logic."""

import re
from datetime import datetime, timezone
from uuid import UUID

from loguru import logger
from sqlalchemy.engine import Connection

VALID_ROLES: tuple[str, ...] = ("owner", "admin", "member")

_SLUG_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")


def validate_org_slug(slug: str) -> str:
    """Validate and return an organization slug.

    A valid slug is 1-64 characters, lowercase alphanumeric plus hyphens,
    with no leading or trailing hyphens.

    Args:
        slug: The organization slug to validate.

    Returns:
        The validated slug.

    Raises:
        ValueError: If the slug does not match the required format.
    """
    if not _SLUG_PATTERN.match(slug):
        raise ValueError(
            f"Invalid org slug '{slug}': must be 1-64 chars, lowercase "
            "alphanumeric + hyphens, no leading/trailing hyphens."
        )
    return slug


def validate_role(role: str) -> str:
    """Validate that a role is one of the allowed values.

    Args:
        role: The role string to validate.

    Returns:
        The validated role.

    Raises:
        ValueError: If the role is not in VALID_ROLES.
    """
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}': must be one of {VALID_ROLES}.")
    return role


def sync_user_orgs(
    conn: Connection,
    user_id: UUID,
    github_org_logins: list[str],
    username: str,
) -> list[str]:
    """Sync GitHub orgs to the database for a user.

    Always ensures the personal namespace (username) exists first.
    For each GitHub org: creates it if missing (user as owner),
    adds the user as member if not already a member.
    Skips org names that don't pass slug validation.

    Does NOT remove stale memberships — revocation is a separate concern.

    Args:
        conn: Active database connection.
        user_id: UUID of the authenticated user.
        github_org_logins: GitHub org login names from the API.
        username: GitHub username (used as personal namespace).

    Returns:
        Sorted list of all org slugs the user belongs to after sync.
    """
    from decision_hub.infra.database import (
        find_org_by_slug,
        find_org_member,
        insert_org_member,
        insert_organization,
    )

    # Always sync personal namespace first
    all_slugs: list[str] = []
    _ensure_org_membership(
        conn,
        user_id,
        username.lower(),
        "owner",
        find_org_by_slug,
        insert_organization,
        find_org_member,
        insert_org_member,
        is_personal=True,
    )
    all_slugs.append(username.lower())

    for login in github_org_logins:
        slug = login.lower()

        # Skip slugs that don't match our validation rules
        if not _SLUG_PATTERN.match(slug):
            logger.debug("Skipping invalid org slug from GitHub: {!r}", login)
            continue

        # Skip if it's the same as the personal namespace
        if slug == username.lower():
            continue

        _ensure_org_membership(
            conn,
            user_id,
            slug,
            "member",
            find_org_by_slug,
            insert_organization,
            find_org_member,
            insert_org_member,
            is_personal=False,
        )
        all_slugs.append(slug)

    return sorted(set(all_slugs))


def _ensure_org_membership(
    conn: Connection,
    user_id: UUID,
    slug: str,
    default_role: str,
    find_org_fn,
    insert_org_fn,
    find_member_fn,
    insert_member_fn,
    *,
    is_personal: bool = False,
) -> None:
    """Ensure a user is a member of an org, creating both if needed."""
    org = find_org_fn(conn, slug)
    if org is None:
        # Create org with user as owner
        org = insert_org_fn(conn, slug, user_id, is_personal=is_personal)
        insert_member_fn(conn, org.id, user_id, "owner")
        return

    # Org exists — check if user is already a member
    member = find_member_fn(conn, org.id, user_id)
    if member is None:
        insert_member_fn(conn, org.id, user_id, default_role)


# Metadata refresh threshold: skip orgs synced within this window
_METADATA_REFRESH_HOURS = 24


async def sync_org_github_metadata(
    conn: Connection,
    access_token: str,
    org_slugs: list[str],
    username: str,
) -> None:
    """Fetch GitHub metadata for each org and persist it.

    For personal namespaces (slug == username.lower()), uses the GitHub
    /users/{username} endpoint. For team orgs, uses /orgs/{org}.
    Skips orgs that were synced within the last _METADATA_REFRESH_HOURS.
    Errors on individual orgs are logged and skipped (best-effort).
    """
    from decision_hub.infra.database import find_org_by_slug, update_org_github_metadata
    from decision_hub.infra.github import fetch_org_metadata, fetch_user_metadata

    now = datetime.now(timezone.utc)
    personal_slug = username.lower()

    for slug in org_slugs:
        org = find_org_by_slug(conn, slug)
        if org is None:
            continue

        # Skip if recently synced
        if org.github_synced_at is not None:
            age_hours = (now - org.github_synced_at).total_seconds() / 3600
            if age_hours < _METADATA_REFRESH_HOURS:
                continue

        try:
            if slug == personal_slug:
                meta = await fetch_user_metadata(access_token, username)
            else:
                meta = await fetch_org_metadata(access_token, slug)
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to fetch GitHub metadata for org={}", slug
            )
            continue

        update_org_github_metadata(
            conn,
            org.id,
            avatar_url=meta.get("avatar_url"),
            email=meta.get("email"),
            description=meta.get("description"),
            blog=meta.get("blog"),
        )
        logger.debug("Synced GitHub metadata for org={}", slug)
