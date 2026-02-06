"""Organization validation logic."""

import re

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
        raise ValueError(
            f"Invalid role '{role}': must be one of {VALID_ROLES}."
        )
    return role


