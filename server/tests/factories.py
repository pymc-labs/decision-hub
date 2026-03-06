"""Test data factories for server tests.

Centralized builders that produce model instances with sensible defaults.
Override specific fields via keyword arguments. All functions return
frozen dataclass instances matching the production models.
"""

from uuid import UUID, uuid4

from decision_hub.models import Organization, OrgMember, Skill, Version

# Stable default user ID used across test factories.
DEFAULT_USER_ID = UUID("12345678-1234-5678-1234-567812345678")


def make_org(**overrides: object) -> Organization:
    """Build an Organization with sensible defaults."""
    defaults: dict[str, object] = {
        "id": uuid4(),
        "slug": "test-org",
        "owner_id": DEFAULT_USER_ID,
    }
    defaults.update(overrides)
    return Organization(**defaults)  # type: ignore[arg-type]


def make_skill(org: Organization | None = None, **overrides: object) -> Skill:
    """Build a Skill linked to *org* (or a fresh org if None)."""
    if org is None:
        org = make_org()
    defaults: dict[str, object] = {
        "id": uuid4(),
        "org_id": org.id,
        "name": "my-skill",
        "description": "A test skill",
    }
    defaults.update(overrides)
    return Skill(**defaults)  # type: ignore[arg-type]


def make_version(skill: Skill | None = None, **overrides: object) -> Version:
    """Build a Version linked to *skill* (or a fresh skill if None)."""
    if skill is None:
        skill = make_skill()
    semver = overrides.get("semver", "1.0.0")
    defaults: dict[str, object] = {
        "id": uuid4(),
        "skill_id": skill.id,
        "semver": semver,
        "s3_key": f"skills/test-org/{skill.name}/{semver}.zip",
        "checksum": "abc123def456",
        "runtime_config": None,
        "eval_status": "A",
        "created_at": None,
        "published_by": "testuser",
    }
    defaults.update(overrides)
    return Version(**defaults)  # type: ignore[arg-type]


def make_member(org: Organization | None = None, **overrides: object) -> OrgMember:
    """Build an OrgMember linked to *org*."""
    if org is None:
        org = make_org()
    defaults: dict[str, object] = {
        "org_id": org.id,
        "user_id": DEFAULT_USER_ID,
        "role": "owner",
    }
    defaults.update(overrides)
    return OrgMember(**defaults)  # type: ignore[arg-type]
