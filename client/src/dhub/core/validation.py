"""Validation functions for skill names and semver versions.

Re-exports shared validation from dhub_core; keeps bump_version local
(client-only).
"""

from dhub_core.validation import (
    _SKILL_NAME_PATTERN,  # noqa: F401 — re-exported for client tests
    FIRST_VERSION,
    validate_semver,
    validate_skill_name,
)

__all__ = ["FIRST_VERSION", "bump_version", "parse_skill_ref", "validate_semver", "validate_skill_name"]


def parse_skill_ref(skill_ref: str) -> tuple[str, str]:
    """Parse 'org/skill' reference into (org_slug, skill_name).

    Raises:
        ValueError: If the reference is not in org/skill format.
    """
    parts = skill_ref.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Skill reference must be in org/skill format, got: '{skill_ref}'")
    return parts[0], parts[1]


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
