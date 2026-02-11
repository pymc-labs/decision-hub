"""Validation functions for skill names and semver versions.

This module is the single source of truth for validation logic shared
between the client (dhub-cli) and server (decision-hub-server).
"""

import re

_SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")

FIRST_VERSION = "0.1.0"


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


def validate_skill_name(name: str) -> str:
    """Validate a skill name.

    A valid skill name is 1-64 characters, lowercase alphanumeric plus hyphens,
    with no leading or trailing hyphens.

    Args:
        name: The skill name to validate.

    Returns:
        The validated skill name.

    Raises:
        ValueError: If the name does not match the required format.
    """
    if not _SKILL_NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid skill name '{name}': must be 1-64 chars, lowercase "
            "alphanumeric + hyphens, no leading/trailing hyphens."
        )
    return name
