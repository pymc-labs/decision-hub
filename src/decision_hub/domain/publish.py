"""Publishing validation for skills."""

import re

_SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")


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
        raise ValueError(
            f"Invalid semver '{version}': must be in major.minor.patch format "
            "(e.g. '1.0.0')."
        )
    return version


def build_s3_key(org_slug: str, skill_name: str, version: str) -> str:
    """Build the S3 object key for a published skill version.

    Args:
        org_slug: The organization slug.
        skill_name: The skill name.
        version: The semver version string.

    Returns:
        S3 key in the format 'skills/{org}/{name}/{version}.zip'.
    """
    return f"skills/{org_slug}/{skill_name}/{version}.zip"


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
