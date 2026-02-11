"""Validation functions for skill names and semver versions.

Re-exports shared validation from dhub_core; keeps bump_version local
(client-only).
"""

from dhub_core.validation import (
    FIRST_VERSION,
    _SKILL_NAME_PATTERN,
    validate_semver,
    validate_skill_name,
)

__all__ = ["FIRST_VERSION", "bump_version", "validate_semver", "validate_skill_name"]


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
