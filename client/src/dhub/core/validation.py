"""Validation functions for skill names and semver versions.

Re-exports shared validation from dhub_core; keeps parse_skill_ref local
(client-only).
"""

from dhub_core.validation import (
    _SKILL_NAME_PATTERN,  # noqa: F401 — re-exported for client tests
    FIRST_VERSION,
    bump_version,
    parse_semver,
    validate_semver,
    validate_skill_name,
)

__all__ = ["FIRST_VERSION", "bump_version", "parse_semver", "parse_skill_ref", "validate_semver", "validate_skill_name"]


def parse_skill_ref(skill_ref: str) -> tuple[str, str]:
    """Parse 'org/skill' reference into (org_slug, skill_name).

    Raises:
        ValueError: If the reference is not in org/skill format, or if either
            the org or skill component is empty (e.g. 'org/' or '/skill').
    """
    parts = skill_ref.split("/", 1)
    # ``"org/".split("/", 1)`` yields ``["org", ""]`` — length 2 but with an
    # empty half — so guard the components explicitly. An empty skill name
    # would otherwise resolve to the org directory itself (e.g. ~/.dhub/skills/org/).
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Skill reference must be in org/skill format, got: '{skill_ref}'")
    return parts[0], parts[1]
