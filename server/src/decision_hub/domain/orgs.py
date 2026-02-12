"""Organization validation and sync logic."""

import re
from datetime import timedelta
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


METADATA_CACHE_TTL = timedelta(hours=24)


async def sync_org_github_metadata(
    engine,
    gh_token: str,
    org_slugs: list[str],
    username: str,
) -> None:
    """Sync GitHub metadata (avatar, description, blog) for each org.

    For each org slug:
    1. Look up the org in the DB — skip if not found.
    2. Skip if ``github_synced_at`` is within the last 24 hours.
    3. For the personal namespace (slug == username), fetch from
       ``/users/{username}``; otherwise fetch from ``/orgs/{slug}``.
    4. Persist via ``update_org_github_metadata``.

    Uses short-lived DB transactions so the connection is not held open
    during GitHub HTTP calls.

    Individual org failures are logged and skipped so the loop always
    completes.

    Args:
        engine: SQLAlchemy engine (opens its own short-lived transactions).
        gh_token: GitHub OAuth access token.
        org_slugs: List of org slugs to sync.
        username: GitHub username (identifies the personal namespace).
    """
    from datetime import UTC, datetime

    from decision_hub.infra.database import find_org_by_slug, update_org_github_metadata
    from decision_hub.infra.github import fetch_org_metadata, fetch_user_metadata

    now = datetime.now(UTC)

    for slug in org_slugs:
        try:
            # Read org in a short-lived transaction
            with engine.begin() as conn:
                org = find_org_by_slug(conn, slug)
            if org is None:
                continue

            # Skip if recently synced
            if org.github_synced_at and (now - org.github_synced_at) < METADATA_CACHE_TTL:
                continue

            # Fetch metadata from GitHub (no DB transaction held)
            if slug == username.lower():
                meta = await fetch_user_metadata(gh_token, username)
            else:
                meta = await fetch_org_metadata(gh_token, slug)

            # Write metadata in a short-lived transaction
            with engine.begin() as conn:
                update_org_github_metadata(
                    conn,
                    org.id,
                    avatar_url=meta.get("avatar_url"),
                    email=meta.get("email"),
                    description=meta.get("description"),
                    blog=meta.get("blog"),
                )
        except Exception:
            logger.opt(exception=True).debug(
                "Failed to sync GitHub metadata for org {}; skipping",
                slug,
            )
