"""Validation functions for skill names, org slugs, and semver versions.

This module is the single source of truth for validation logic shared
between the client (dhub-cli) and server (decision-hub-server).
"""

import re

_SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

# Shared slug pattern: 1-64 chars, lowercase alphanumeric + hyphens,
# no leading/trailing hyphens. Used for both skill names and org slugs.
_SLUG_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")

# Backward-compat alias — some call sites reference the old name.
_SKILL_NAME_PATTERN = _SLUG_PATTERN

FIRST_VERSION = "0.1.0"


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse a semver string into a comparable (major, minor, patch) tuple.

    Raises:
        ValueError: If the version string does not have exactly 3 dot-separated
            integer components.
    """
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid semver '{version}': expected 3 dot-separated components, got {len(parts)}")
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        raise ValueError(f"Invalid semver '{version}': components must be integers") from None


def validate_semver(version: str) -> str:
    """Validate that a version string follows semver format (major.minor.patch).

    Args:
        version: The version string to validate.

    Returns:
        The validated version string.

    Raises:
        ValueError: If the version does not match semver format.
    """
    if not _SEMVER_PATTERN.match(version):
        raise ValueError(f"Invalid semver '{version}': must be in major.minor.patch format (e.g. '1.0.0').")
    return version


def bump_version(current: str, bump: str = "patch") -> str:
    """Increment a semver version string.

    Args:
        current: Current version in major.minor.patch format.
        bump: Which component to bump ('major', 'minor', or 'patch').

    Returns:
        The bumped version string.

    Raises:
        ValueError: If current is not valid semver or bump level is unknown.
    """
    validate_semver(current)
    major, minor, patch = (int(p) for p in current.split("."))

    if bump == "patch":
        patch += 1
    elif bump == "minor":
        minor += 1
        patch = 0
    elif bump == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        raise ValueError(f"Unknown bump level '{bump}': must be major, minor, or patch")

    return f"{major}.{minor}.{patch}"


def validate_slug(slug: str, label: str = "slug") -> str:
    """Validate a slug (skill name or org slug).

    A valid slug is 1-64 characters, lowercase alphanumeric plus hyphens,
    with no leading or trailing hyphens.

    Args:
        slug: The slug to validate.
        label: Human-readable label for error messages (e.g. 'skill name', 'org slug').

    Returns:
        The validated slug.

    Raises:
        ValueError: If the slug does not match the required format.
    """
    if not _SLUG_PATTERN.match(slug):
        raise ValueError(
            f"Invalid {label} '{slug}': must be 1-64 chars, lowercase "
            "alphanumeric + hyphens, no leading/trailing hyphens."
        )
    return slug


def validate_skill_name(name: str) -> str:
    """Validate a skill name. Delegates to :func:`validate_slug`."""
    return validate_slug(name, label="skill name")


def validate_org_slug(slug: str) -> str:
    """Validate an organization slug. Delegates to :func:`validate_slug`."""
    return validate_slug(slug, label="org slug")
