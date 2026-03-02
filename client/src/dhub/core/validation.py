"""Validation functions for skill names and semver versions.

Re-exports shared validation from dhub_core; keeps parse_skill_ref local
(client-only).
"""

from dhub_core.validation import (
    _SKILL_NAME_PATTERN,  # noqa: F401 — re-exported for client tests
    FIRST_VERSION,
    bump_version,
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
