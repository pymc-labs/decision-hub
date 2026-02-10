"""SQLAlchemy Core tables and query functions for Decision Hub.

All tables use PostgreSQL-specific types (UUID, JSONB) and are designed for
Supabase/PgBouncer compatibility (NullPool, statement_cache_size=0).
Query functions accept a Connection as their first argument and return
frozen dataclass instances from decision_hub.models.
"""

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from loguru import logger
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

from decision_hub.models import (
    AuditLogEntry,
    EvalReport,
    EvalRun,
    Organization,
    OrgMember,
    Skill,
    User,
    UserApiKey,
    Version,
)

metadata = MetaData()

# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------

users_table = Table(
    "users",
    metadata,
    Column(
        "id",
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.func.gen_random_uuid(),
    ),
    Column("github_id", String, nullable=False, unique=True),
    Column("username", String, nullable=False, unique=True),
)

organizations_table = Table(
    "organizations",
    metadata,
    Column(
        "id",
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.func.gen_random_uuid(),
    ),
    Column("slug", String, nullable=False, unique=True),
    Column(
        "owner_id",
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    ),
    Column("is_personal", Boolean, nullable=False, server_default="false"),
    Column("avatar_url", Text, nullable=True),
    Column("email", Text, nullable=True),
    Column("description", Text, nullable=True),
    Column("blog", Text, nullable=True),
    Column("github_synced_at", DateTime(timezone=True), nullable=True),
)

org_members_table = Table(
    "org_members",
    metadata,
    Column(
        "org_id",
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        primary_key=True,
    ),
    Column(
        "user_id",
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        primary_key=True,
    ),
    Column("role", String, nullable=False),
)

skills_table = Table(
    "skills",
    metadata,
    Column(
        "id",
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.func.gen_random_uuid(),
    ),
    Column(
        "org_id",
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=False,
    ),
    Column("name", String, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    Column("download_count", sa.Integer, nullable=False, server_default="0"),
    sa.UniqueConstraint("org_id", "name"),
)

versions_table = Table(
    "versions",
    metadata,
    Column(
        "id",
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.func.gen_random_uuid(),
    ),
    Column(
        "skill_id",
        PG_UUID(as_uuid=True),
        ForeignKey("skills.id"),
        nullable=False,
    ),
    Column("semver", String, nullable=False),
    Column("semver_major", sa.Integer, nullable=False, server_default="0"),
    Column("semver_minor", sa.Integer, nullable=False, server_default="0"),
    Column("semver_patch", sa.Integer, nullable=False, server_default="0"),
    Column("s3_key", Text, nullable=False),
    Column("checksum", String, nullable=False),
    Column("runtime_config", JSONB, nullable=True),
    Column("eval_status", String, nullable=False, server_default="pending"),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    Column("published_by", String, nullable=False, server_default=""),
    sa.UniqueConstraint("skill_id", "semver"),
    sa.Index(
        "idx_versions_skill_semver_parts",
        "skill_id",
        sa.text("semver_major DESC"),
        sa.text("semver_minor DESC"),
        sa.text("semver_patch DESC"),
    ),
)

user_api_keys_table = Table(
    "user_api_keys",
    metadata,
    Column(
        "id",
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.func.gen_random_uuid(),
    ),
    Column(
        "user_id",
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    ),
    Column("key_name", String, nullable=False),
    Column("encrypted_value", LargeBinary, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.UniqueConstraint("user_id", "key_name"),
)

eval_audit_logs_table = Table(
    "eval_audit_logs",
    metadata,
    Column(
        "id",
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.func.gen_random_uuid(),
    ),
    Column("org_slug", Text, nullable=False),
    Column("skill_name", Text, nullable=False),
    Column("semver", String, nullable=False),
    Column("grade", String(1), nullable=False),
    Column(
        "version_id",
        PG_UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("check_results", JSONB, nullable=False),
    Column("llm_reasoning", JSONB, nullable=True),
    Column("publisher", String, nullable=False, server_default=""),
    Column("quarantine_s3_key", Text, nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)

eval_reports_table = Table(
    "eval_reports",
    metadata,
    Column(
        "id",
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.func.gen_random_uuid(),
    ),
    Column(
        "version_id",
        PG_UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("agent", String, nullable=False),
    Column("judge_model", String, nullable=False),
    Column("case_results", JSONB, nullable=False),
    Column("passed", sa.Integer, nullable=False),
    Column("total", sa.Integer, nullable=False),
    Column("total_duration_ms", sa.Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("error_message", Text, nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)

eval_runs_table = Table(
    "eval_runs",
    metadata,
    Column(
        "id",
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.func.gen_random_uuid(),
    ),
    Column(
        "version_id",
        PG_UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "user_id",
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    ),
    Column("agent", String, nullable=False),
    Column("judge_model", String, nullable=False),
    Column("status", String, nullable=False, server_default="pending"),
    Column("stage", String, nullable=True),
    Column("current_case", String, nullable=True),
    Column("current_case_index", sa.Integer, nullable=True),
    Column("total_cases", sa.Integer, nullable=False),
    Column("heartbeat_at", DateTime(timezone=True), nullable=True),
    Column("log_s3_prefix", Text, nullable=False),
    Column("log_seq", sa.Integer, nullable=False, server_default="0"),
    Column("error_message", Text, nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------


def create_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine configured for Supabase PgBouncer compatibility.

    Uses NullPool (no connection pooling on the client side, since PgBouncer
    handles pooling) and disables the PostgreSQL statement cache to avoid
    conflicts with PgBouncer's transaction-mode pooling.

    Args:
        database_url: PostgreSQL connection string.

    Returns:
        A configured SQLAlchemy Engine instance.
    """
    return sa.create_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"options": "-c statement_cache_size=0"},
    )


# ---------------------------------------------------------------------------
# Row-to-model helpers
# ---------------------------------------------------------------------------


def _row_to_user(row: sa.Row) -> User:
    """Map a database row to a User model."""
    return User(id=row.id, github_id=row.github_id, username=row.username)


def _row_to_organization(row: sa.Row) -> Organization:
    """Map a database row to an Organization model."""
    return Organization(
        id=row.id,
        slug=row.slug,
        owner_id=row.owner_id,
        is_personal=row.is_personal,
        avatar_url=row.avatar_url,
        email=row.email,
        description=row.description,
        blog=row.blog,
        github_synced_at=row.github_synced_at,
    )


def _row_to_org_member(row: sa.Row) -> OrgMember:
    """Map a database row to an OrgMember model."""
    return OrgMember(org_id=row.org_id, user_id=row.user_id, role=row.role)


def _row_to_skill(row: sa.Row) -> Skill:
    """Map a database row to a Skill model."""
    return Skill(id=row.id, org_id=row.org_id, name=row.name, description=row.description, download_count=row.download_count)


def _row_to_version(row: sa.Row) -> Version:
    """Map a database row to a Version model."""
    return Version(
        id=row.id,
        skill_id=row.skill_id,
        semver=row.semver,
        s3_key=row.s3_key,
        checksum=row.checksum,
        runtime_config=row.runtime_config,
        eval_status=row.eval_status,
        created_at=row.created_at,
        published_by=row.published_by,
    )


def _row_to_user_api_key(row: sa.Row) -> UserApiKey:
    """Map a database row to a UserApiKey model."""
    return UserApiKey(
        id=row.id,
        user_id=row.user_id,
        key_name=row.key_name,
        encrypted_value=row.encrypted_value,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# User queries
# ---------------------------------------------------------------------------


def find_user_by_github_id(conn: Connection, github_id: str) -> User | None:
    """Find a user by their GitHub ID.

    Args:
        conn: Active database connection.
        github_id: The GitHub user ID string.

    Returns:
        The matching User, or None if not found.
    """
    stmt = sa.select(users_table).where(users_table.c.github_id == github_id)
    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_user(row)


def upsert_user(conn: Connection, github_id: str, username: str) -> User:
    """Insert a user or update the username if the github_id already exists.

    Uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE to atomically handle
    both new and returning users.

    Args:
        conn: Active database connection.
        github_id: The GitHub user ID string.
        username: The GitHub username.

    Returns:
        The upserted User.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = (
        pg_insert(users_table)
        .values(github_id=github_id, username=username)
        .on_conflict_do_update(
            index_elements=[users_table.c.github_id],
            set_={"username": username},
        )
        .returning(*users_table.c)
    )
    row = conn.execute(stmt).one()
    user = _row_to_user(row)
    logger.debug("Upserted user github_id={} username={} id={}", github_id, username, user.id)
    return user


# ---------------------------------------------------------------------------
# Organization queries
# ---------------------------------------------------------------------------


def insert_organization(
    conn: Connection, slug: str, owner_id: UUID, *, is_personal: bool = False
) -> Organization:
    """Create a new organization.

    Args:
        conn: Active database connection.
        slug: Unique organization slug.
        owner_id: UUID of the owning user.
        is_personal: Whether this is a personal user namespace.

    Returns:
        The newly created Organization.
    """
    stmt = (
        sa.insert(organizations_table)
        .values(slug=slug, owner_id=owner_id, is_personal=is_personal)
        .returning(*organizations_table.c)
    )
    row = conn.execute(stmt).one()
    org = _row_to_organization(row)
    logger.debug("Created org slug={} owner={} id={}", slug, owner_id, org.id)
    return org


def find_org_by_slug(conn: Connection, slug: str) -> Organization | None:
    """Find an organization by its slug.

    Args:
        conn: Active database connection.
        slug: The organization slug to search for.

    Returns:
        The matching Organization, or None if not found.
    """
    stmt = sa.select(organizations_table).where(
        organizations_table.c.slug == slug
    )
    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_organization(row)


def update_org_github_metadata(
    conn: Connection,
    org_id: UUID,
    *,
    avatar_url: str | None = None,
    email: str | None = None,
    description: str | None = None,
    blog: str | None = None,
) -> None:
    """Update GitHub-sourced metadata on an organization.

    Sets github_synced_at to the current time.
    """
    stmt = (
        sa.update(organizations_table)
        .where(organizations_table.c.id == org_id)
        .values(
            avatar_url=avatar_url,
            email=email,
            description=description,
            blog=blog,
            github_synced_at=sa.func.now(),
        )
    )
    conn.execute(stmt)
    logger.debug("Updated GitHub metadata for org={}", org_id)


def list_user_orgs(conn: Connection, user_id: UUID) -> list[Organization]:
    """List all organizations a user belongs to.

    Joins org_members with organizations to find every organization
    where the user has a membership record.

    Args:
        conn: Active database connection.
        user_id: UUID of the user.

    Returns:
        List of Organizations the user is a member of.
    """
    stmt = (
        sa.select(organizations_table)
        .join(
            org_members_table,
            organizations_table.c.id == org_members_table.c.org_id,
        )
        .where(org_members_table.c.user_id == user_id)
    )
    rows = conn.execute(stmt).all()
    return [_row_to_organization(row) for row in rows]


# ---------------------------------------------------------------------------
# Org member queries
# ---------------------------------------------------------------------------


def insert_org_member(
    conn: Connection, org_id: UUID, user_id: UUID, role: str
) -> OrgMember:
    """Add a member to an organization.

    Args:
        conn: Active database connection.
        org_id: UUID of the organization.
        user_id: UUID of the user to add.
        role: Membership role (e.g. 'owner', 'admin', 'member').

    Returns:
        The newly created OrgMember.
    """
    stmt = (
        sa.insert(org_members_table)
        .values(org_id=org_id, user_id=user_id, role=role)
        .returning(*org_members_table.c)
    )
    row = conn.execute(stmt).one()
    logger.debug("Added org member org={} user={} role={}", org_id, user_id, role)
    return _row_to_org_member(row)


def list_org_members(conn: Connection, org_id: UUID) -> list[OrgMember]:
    """List all members of an organization.

    Args:
        conn: Active database connection.
        org_id: UUID of the organization.

    Returns:
        List of OrgMember records for the organization.
    """
    stmt = sa.select(org_members_table).where(
        org_members_table.c.org_id == org_id
    )
    rows = conn.execute(stmt).all()
    return [_row_to_org_member(row) for row in rows]


def find_org_member(
    conn: Connection, org_id: UUID, user_id: UUID
) -> OrgMember | None:
    """Find a specific membership record.

    Args:
        conn: Active database connection.
        org_id: UUID of the organization.
        user_id: UUID of the user.

    Returns:
        The OrgMember if found, or None.
    """
    stmt = sa.select(org_members_table).where(
        sa.and_(
            org_members_table.c.org_id == org_id,
            org_members_table.c.user_id == user_id,
        )
    )
    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_org_member(row)


# ---------------------------------------------------------------------------
# Skill queries
# ---------------------------------------------------------------------------


def insert_skill(
    conn: Connection, org_id: UUID, name: str, description: str = ""
) -> Skill:
    """Register a new skill under an organization.

    Args:
        conn: Active database connection.
        org_id: UUID of the owning organization.
        name: Skill name (unique within the org).
        description: Short description from SKILL.md frontmatter.

    Returns:
        The newly created Skill.
    """
    stmt = (
        sa.insert(skills_table)
        .values(org_id=org_id, name=name, description=description)
        .returning(*skills_table.c)
    )
    row = conn.execute(stmt).one()
    skill = _row_to_skill(row)
    logger.debug("Inserted skill name={} org={} id={}", name, org_id, skill.id)
    return skill


def find_skill(conn: Connection, org_id: UUID, name: str) -> Skill | None:
    """Find a skill by organization and name.

    Args:
        conn: Active database connection.
        org_id: UUID of the organization.
        name: Skill name.

    Returns:
        The Skill if found, or None.
    """
    stmt = sa.select(skills_table).where(
        sa.and_(
            skills_table.c.org_id == org_id,
            skills_table.c.name == name,
        )
    )
    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_skill(row)


def update_skill_description(
    conn: Connection, skill_id: UUID, description: str
) -> None:
    """Update the description of an existing skill.

    Used during re-publish to keep the description in sync with SKILL.md.
    """
    stmt = (
        sa.update(skills_table)
        .where(skills_table.c.id == skill_id)
        .values(description=description)
    )
    conn.execute(stmt)


def increment_skill_downloads(conn: Connection, skill_id: UUID) -> None:
    """Atomically increment the download counter for a skill."""
    stmt = (
        sa.update(skills_table)
        .where(skills_table.c.id == skill_id)
        .values(download_count=skills_table.c.download_count + 1)
    )
    conn.execute(stmt)


# ---------------------------------------------------------------------------
# Version queries
# ---------------------------------------------------------------------------


def parse_semver_parts(semver: str) -> tuple[int, int, int]:
    """Parse a semver string into (major, minor, patch) integers."""
    major, minor, patch = semver.split(".")
    return int(major), int(minor), int(patch)


def find_version(conn: Connection, skill_id: UUID, semver: str) -> Version | None:
    """Look up a specific version of a skill by skill ID and semver string.

    Returns the Version if found, or None if the version does not exist.
    """
    stmt = sa.select(versions_table).where(
        sa.and_(
            versions_table.c.skill_id == skill_id,
            versions_table.c.semver == semver,
        )
    )
    row = conn.execute(stmt).first()
    return _row_to_version(row) if row else None


def insert_version(
    conn: Connection,
    skill_id: UUID,
    semver: str,
    s3_key: str,
    checksum: str,
    runtime_config: dict | None,
    published_by: str = "",
    eval_status: str = "pending",
) -> Version:
    """Record a new published version of a skill.

    Args:
        conn: Active database connection.
        skill_id: UUID of the parent skill.
        semver: Semantic version string (e.g. '1.2.3').
        s3_key: S3 object key where the skill zip is stored.
        checksum: SHA256 hex digest of the skill zip.
        runtime_config: Optional runtime configuration as a JSON-compatible dict.
        published_by: GitHub username of the publisher.
        eval_status: Evaluation result (pending/passed/failed).

    Returns:
        The newly created Version.
    """
    major, minor, patch = parse_semver_parts(semver)
    stmt = (
        sa.insert(versions_table)
        .values(
            skill_id=skill_id,
            semver=semver,
            semver_major=major,
            semver_minor=minor,
            semver_patch=patch,
            s3_key=s3_key,
            checksum=checksum,
            runtime_config=runtime_config,
            published_by=published_by,
            eval_status=eval_status,
        )
        .returning(*versions_table.c)
    )
    row = conn.execute(stmt).one()
    ver = _row_to_version(row)
    logger.debug("Inserted version skill={} semver={} eval_status={} id={}", skill_id, semver, eval_status, ver.id)
    return ver


def resolve_version(
    conn: Connection,
    org_slug: str,
    skill_name: str,
    spec: str,
    allow_risky: bool = False,
) -> Version | None:
    """Resolve a version specification to a concrete Version record.

    If spec is "latest", returns the highest semver for the given skill.
    Otherwise, returns the exact match for the specified semver string.

    Semver ordering splits on '.' and casts each part to integer, so
    '2.10.0' correctly sorts higher than '2.9.0'.

    Args:
        conn: Active database connection.
        org_slug: Organization slug that owns the skill.
        skill_name: Name of the skill.
        spec: Either "latest" or an exact semver string.
        allow_risky: If True, also include C-grade (risky) versions.

    Returns:
        The resolved Version, or None if no matching version exists.
    """
    # Join versions -> skills -> organizations to resolve by slug + name
    join = versions_table.join(
        skills_table, versions_table.c.skill_id == skills_table.c.id
    ).join(
        organizations_table,
        skills_table.c.org_id == organizations_table.c.id,
    )

    base = (
        sa.select(versions_table)
        .select_from(join)
        .where(
            sa.and_(
                organizations_table.c.slug == org_slug,
                skills_table.c.name == skill_name,
            )
        )
    )

    # Filter by grade: A/B (and legacy "passed") by default, add C if allow_risky
    allowed_statuses = ["A", "B", "passed"]
    if allow_risky:
        allowed_statuses.append("C")
    base = base.where(versions_table.c.eval_status.in_(allowed_statuses))

    if spec == "latest":
        stmt = base.order_by(
            versions_table.c.semver_major.desc(),
            versions_table.c.semver_minor.desc(),
            versions_table.c.semver_patch.desc(),
        ).limit(1)
    else:
        stmt = base.where(versions_table.c.semver == spec)

    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_version(row)


def resolve_latest_version(
    conn: Connection,
    org_slug: str,
    skill_name: str,
) -> Version | None:
    """Find the latest version of a skill regardless of eval_status.

    Used for auto-bumping: the publisher needs to know the highest
    published semver even if it hasn't passed evaluation yet.
    """
    join = versions_table.join(
        skills_table, versions_table.c.skill_id == skills_table.c.id
    ).join(
        organizations_table,
        skills_table.c.org_id == organizations_table.c.id,
    )

    stmt = (
        sa.select(versions_table)
        .select_from(join)
        .where(
            sa.and_(
                organizations_table.c.slug == org_slug,
                skills_table.c.name == skill_name,
            )
        )
        .order_by(
            versions_table.c.semver_major.desc(),
            versions_table.c.semver_minor.desc(),
            versions_table.c.semver_patch.desc(),
        )
        .limit(1)
    )

    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_version(row)


def delete_all_versions(conn: Connection, skill_id: UUID) -> list[str]:
    """Delete all versions of a skill.

    Args:
        conn: Active database connection.
        skill_id: UUID of the parent skill.

    Returns:
        List of S3 keys for the deleted versions (for S3 cleanup).
    """
    # Fetch s3_keys before deleting
    select_stmt = sa.select(versions_table.c.s3_key).where(
        versions_table.c.skill_id == skill_id
    )
    rows = conn.execute(select_stmt).all()
    s3_keys = [row.s3_key for row in rows]

    delete_stmt = sa.delete(versions_table).where(
        versions_table.c.skill_id == skill_id
    )
    conn.execute(delete_stmt)
    logger.debug("Deleted {} versions for skill={}", len(s3_keys), skill_id)
    return s3_keys


def delete_skill(conn: Connection, skill_id: UUID) -> None:
    """Delete a skill record (after all versions have been removed)."""
    stmt = sa.delete(skills_table).where(skills_table.c.id == skill_id)
    conn.execute(stmt)
    logger.debug("Deleted skill id={}", skill_id)


def delete_version(conn: Connection, skill_id: UUID, semver: str) -> bool:
    """Delete a specific version of a skill.

    Args:
        conn: Active database connection.
        skill_id: UUID of the parent skill.
        semver: Semantic version string to delete.

    Returns:
        True if a version was deleted, False if no matching version was found.
    """
    stmt = sa.delete(versions_table).where(
        sa.and_(
            versions_table.c.skill_id == skill_id,
            versions_table.c.semver == semver,
        )
    )
    result = conn.execute(stmt)
    deleted = result.rowcount > 0
    if deleted:
        logger.debug("Deleted version skill={} semver={}", skill_id, semver)
    return deleted


# ---------------------------------------------------------------------------
# User API key queries
# ---------------------------------------------------------------------------


def insert_api_key(
    conn: Connection,
    user_id: UUID,
    key_name: str,
    encrypted_value: bytes,
) -> UserApiKey:
    """Store an encrypted API key for a user.

    Args:
        conn: Active database connection.
        user_id: UUID of the key owner.
        key_name: Human-readable name for the key (unique per user).
        encrypted_value: Fernet-encrypted key value.

    Returns:
        The newly created UserApiKey.
    """
    stmt = (
        sa.insert(user_api_keys_table)
        .values(
            user_id=user_id,
            key_name=key_name,
            encrypted_value=encrypted_value,
        )
        .returning(*user_api_keys_table.c)
    )
    row = conn.execute(stmt).one()
    logger.debug("Stored API key '{}' for user={}", key_name, user_id)
    return _row_to_user_api_key(row)


def list_api_keys(conn: Connection, user_id: UUID) -> list[UserApiKey]:
    """List all API keys belonging to a user.

    Args:
        conn: Active database connection.
        user_id: UUID of the key owner.

    Returns:
        List of UserApiKey records for the user.
    """
    stmt = sa.select(user_api_keys_table).where(
        user_api_keys_table.c.user_id == user_id
    )
    rows = conn.execute(stmt).all()
    return [_row_to_user_api_key(row) for row in rows]


def delete_api_key(conn: Connection, user_id: UUID, key_name: str) -> bool:
    """Delete an API key by user and name.

    Args:
        conn: Active database connection.
        user_id: UUID of the key owner.
        key_name: Name of the key to delete.

    Returns:
        True if a key was deleted, False if no matching key was found.
    """
    stmt = sa.delete(user_api_keys_table).where(
        sa.and_(
            user_api_keys_table.c.user_id == user_id,
            user_api_keys_table.c.key_name == key_name,
        )
    )
    result = conn.execute(stmt)
    deleted = result.rowcount > 0
    if deleted:
        logger.debug("Deleted API key '{}' for user={}", key_name, user_id)
    return deleted


# ---------------------------------------------------------------------------
# Search index queries (Sprint 4)
# ---------------------------------------------------------------------------


def fetch_all_skills_for_index(conn: Connection) -> list[dict]:
    """Fetch all skills with their latest version info for the search index.

    Returns a list of dicts, each with keys: org_slug, skill_name,
    latest_version, eval_status. Uses a subquery to find the latest
    version per skill (ordered by semver parts numerically).
    """
    # Subquery: for each skill, find the highest semver using integer columns
    latest_version = (
        sa.select(
            versions_table.c.skill_id,
            versions_table.c.semver,
            versions_table.c.eval_status,
            versions_table.c.created_at,
            versions_table.c.published_by,
            sa.func.row_number()
            .over(
                partition_by=versions_table.c.skill_id,
                order_by=[
                    versions_table.c.semver_major.desc(),
                    versions_table.c.semver_minor.desc(),
                    versions_table.c.semver_patch.desc(),
                ],
            )
            .label("rn"),
        )
    ).subquery("ranked")

    stmt = (
        sa.select(
            organizations_table.c.slug.label("org_slug"),
            organizations_table.c.is_personal.label("is_personal_org"),
            skills_table.c.name.label("skill_name"),
            skills_table.c.description,
            skills_table.c.download_count,
            latest_version.c.semver.label("latest_version"),
            latest_version.c.eval_status,
            latest_version.c.created_at,
            latest_version.c.published_by,
        )
        .select_from(
            skills_table.join(
                organizations_table,
                skills_table.c.org_id == organizations_table.c.id,
            ).join(
                latest_version,
                sa.and_(
                    skills_table.c.id == latest_version.c.skill_id,
                    latest_version.c.rn == 1,
                ),
            )
        )
    )

    rows = conn.execute(stmt).all()
    return [
        {
            "org_slug": row.org_slug,
            "is_personal_org": row.is_personal_org,
            "skill_name": row.skill_name,
            "description": row.description,
            "download_count": row.download_count,
            "latest_version": row.latest_version,
            "eval_status": row.eval_status,
            "created_at": row.created_at,
            "published_by": row.published_by,
        }
        for row in rows
    ]


def get_api_keys_for_eval(
    conn: Connection, user_id: UUID, key_names: list[str]
) -> dict[str, bytes]:
    """Retrieve encrypted values for specific API keys by name.

    Used during gauntlet runs to fetch only the keys needed by test agents.

    Args:
        conn: Active database connection.
        user_id: UUID of the key owner.
        key_names: List of key names to retrieve.

    Returns:
        Dictionary mapping key_name to its encrypted_value bytes.
        Only includes keys that exist; missing names are silently omitted.
    """
    stmt = sa.select(
        user_api_keys_table.c.key_name,
        user_api_keys_table.c.encrypted_value,
    ).where(
        sa.and_(
            user_api_keys_table.c.user_id == user_id,
            user_api_keys_table.c.key_name.in_(key_names),
        )
    )
    rows = conn.execute(stmt).all()
    return {row.key_name: row.encrypted_value for row in rows}


# ---------------------------------------------------------------------------
# Audit log queries
# ---------------------------------------------------------------------------


def _row_to_audit_log_entry(row: sa.Row) -> AuditLogEntry:
    """Map a database row to an AuditLogEntry model."""
    return AuditLogEntry(
        id=row.id,
        org_slug=row.org_slug,
        skill_name=row.skill_name,
        semver=row.semver,
        grade=row.grade,
        version_id=row.version_id,
        check_results=row.check_results,
        llm_reasoning=row.llm_reasoning,
        publisher=row.publisher,
        quarantine_s3_key=row.quarantine_s3_key,
        created_at=row.created_at,
    )


def insert_audit_log(
    conn: Connection,
    org_slug: str,
    skill_name: str,
    semver: str,
    grade: str,
    check_results: list[dict],
    publisher: str,
    version_id: UUID | None = None,
    llm_reasoning: dict | None = None,
    quarantine_s3_key: str | None = None,
) -> AuditLogEntry:
    """Insert a gauntlet evaluation audit log entry.

    Called for every publish attempt (including F-grade rejections).

    Args:
        conn: Active database connection.
        org_slug: Organization slug (denormalized).
        skill_name: Skill name (denormalized).
        semver: Version string.
        grade: A/B/C/F.
        check_results: Serialized list of EvalResult dicts.
        publisher: GitHub username of the publisher.
        version_id: UUID of the version record (None for F-rejected).
        llm_reasoning: Raw LLM judge responses.
        quarantine_s3_key: S3 key for quarantined rejected packages.

    Returns:
        The newly created AuditLogEntry.
    """
    values = {
        "org_slug": org_slug,
        "skill_name": skill_name,
        "semver": semver,
        "grade": grade,
        "check_results": check_results,
        "publisher": publisher,
    }
    if version_id is not None:
        values["version_id"] = version_id
    if llm_reasoning is not None:
        values["llm_reasoning"] = llm_reasoning
    if quarantine_s3_key is not None:
        values["quarantine_s3_key"] = quarantine_s3_key

    stmt = (
        sa.insert(eval_audit_logs_table)
        .values(**values)
        .returning(*eval_audit_logs_table.c)
    )
    row = conn.execute(stmt).one()
    logger.debug("Audit log: {}/{} v{} grade={} by={}", org_slug, skill_name, semver, grade, publisher)
    return _row_to_audit_log_entry(row)


def find_audit_logs(
    conn: Connection,
    org_slug: str,
    skill_name: str,
    semver: str | None = None,
) -> list[AuditLogEntry]:
    """Find audit log entries for a skill, optionally filtered by version.

    Args:
        conn: Active database connection.
        org_slug: Organization slug.
        skill_name: Skill name.
        semver: Optional version to filter by.

    Returns:
        List of AuditLogEntry records, newest first.
    """
    conditions = [
        eval_audit_logs_table.c.org_slug == org_slug,
        eval_audit_logs_table.c.skill_name == skill_name,
    ]
    if semver is not None:
        conditions.append(eval_audit_logs_table.c.semver == semver)

    stmt = (
        sa.select(eval_audit_logs_table)
        .where(sa.and_(*conditions))
        .order_by(eval_audit_logs_table.c.created_at.desc())
    )
    rows = conn.execute(stmt).all()
    return [_row_to_audit_log_entry(row) for row in rows]


# ---------------------------------------------------------------------------
# Eval report queries
# ---------------------------------------------------------------------------


def _row_to_eval_report(row: sa.Row) -> EvalReport:
    """Map a database row to an EvalReport model."""
    return EvalReport(
        id=row.id,
        version_id=row.version_id,
        agent=row.agent,
        judge_model=row.judge_model,
        case_results=row.case_results,
        passed=row.passed,
        total=row.total,
        total_duration_ms=row.total_duration_ms,
        status=row.status,
        error_message=row.error_message,
        created_at=row.created_at,
    )


def insert_eval_report(
    conn: Connection,
    version_id: UUID,
    agent: str,
    judge_model: str,
    case_results: list[dict],
    passed: int,
    total: int,
    total_duration_ms: int,
    status: str,
    error_message: str | None = None,
) -> EvalReport:
    """Insert an eval report for a skill version.

    Args:
        conn: Active database connection.
        version_id: UUID of the skill version.
        agent: Name of the agent used for evaluation.
        judge_model: Name of the LLM judge model.
        case_results: List of serialized EvalCaseResult dicts.
        passed: Number of cases that passed.
        total: Total number of cases.
        total_duration_ms: Total execution duration in milliseconds.
        status: Overall status (passed/failed/error).
        error_message: Optional error message.

    Returns:
        The newly created EvalReport.
    """
    stmt = (
        sa.insert(eval_reports_table)
        .values(
            version_id=version_id,
            agent=agent,
            judge_model=judge_model,
            case_results=case_results,
            passed=passed,
            total=total,
            total_duration_ms=total_duration_ms,
            status=status,
            error_message=error_message,
        )
        .returning(*eval_reports_table.c)
    )
    row = conn.execute(stmt).one()
    logger.debug("Inserted eval report version={} status={} passed={}/{}", version_id, status, passed, total)
    return _row_to_eval_report(row)


def update_eval_report(
    conn: Connection,
    version_id: UUID,
    status: str,
    error_message: str | None = None,
) -> None:
    """Update an existing eval report's status and error message.

    Args:
        conn: Active database connection.
        version_id: UUID of the skill version.
        status: New status value.
        error_message: Optional error message.
    """
    stmt = (
        sa.update(eval_reports_table)
        .where(eval_reports_table.c.version_id == version_id)
        .values(status=status, error_message=error_message)
    )
    conn.execute(stmt)


def find_eval_report_by_version(
    conn: Connection, version_id: UUID
) -> EvalReport | None:
    """Find an eval report by version ID.

    Args:
        conn: Active database connection.
        version_id: UUID of the skill version.

    Returns:
        The EvalReport if found, or None.
    """
    stmt = sa.select(eval_reports_table).where(
        eval_reports_table.c.version_id == version_id
    )
    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_eval_report(row)


def find_eval_report_by_skill(
    conn: Connection, org_slug: str, skill_name: str, semver: str
) -> EvalReport | None:
    """Find an eval report by org, skill name, and version.

    Args:
        conn: Active database connection.
        org_slug: Organization slug.
        skill_name: Skill name.
        semver: Semantic version string.

    Returns:
        The EvalReport if found, or None.
    """
    # Join eval_reports -> versions -> skills -> organizations
    join = (
        eval_reports_table.join(
            versions_table,
            eval_reports_table.c.version_id == versions_table.c.id,
        )
        .join(skills_table, versions_table.c.skill_id == skills_table.c.id)
        .join(
            organizations_table,
            skills_table.c.org_id == organizations_table.c.id,
        )
    )

    stmt = (
        sa.select(eval_reports_table)
        .select_from(join)
        .where(
            sa.and_(
                organizations_table.c.slug == org_slug,
                skills_table.c.name == skill_name,
                versions_table.c.semver == semver,
            )
        )
    )

    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_eval_report(row)


# ---------------------------------------------------------------------------
# Eval run queries
# ---------------------------------------------------------------------------


def _row_to_eval_run(row: sa.Row) -> EvalRun:
    """Map a database row to an EvalRun model."""
    return EvalRun(
        id=row.id,
        version_id=row.version_id,
        user_id=row.user_id,
        agent=row.agent,
        judge_model=row.judge_model,
        status=row.status,
        stage=row.stage,
        current_case=row.current_case,
        current_case_index=row.current_case_index,
        total_cases=row.total_cases,
        heartbeat_at=row.heartbeat_at,
        log_s3_prefix=row.log_s3_prefix,
        log_seq=row.log_seq,
        error_message=row.error_message,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def insert_eval_run(
    conn: Connection,
    version_id: UUID,
    user_id: UUID,
    agent: str,
    judge_model: str,
    total_cases: int,
    log_s3_prefix: str,
    run_id: UUID | None = None,
) -> EvalRun:
    """Insert a new eval run row (status=pending) before spawning the worker.

    When run_id is provided, uses it as the primary key instead of letting
    the DB generate one. This allows the S3 prefix to be set correctly
    before insert (prefix depends on the run ID).
    """
    values = dict(
        version_id=version_id,
        user_id=user_id,
        agent=agent,
        judge_model=judge_model,
        total_cases=total_cases,
        log_s3_prefix=log_s3_prefix,
    )
    if run_id is not None:
        values["id"] = run_id

    stmt = (
        sa.insert(eval_runs_table)
        .values(**values)
        .returning(*eval_runs_table.c)
    )
    row = conn.execute(stmt).one()
    run = _row_to_eval_run(row)
    logger.debug("Inserted eval run version={} agent={} cases={} id={}", version_id, agent, total_cases, run.id)
    return run


def update_eval_run_status(
    conn: Connection,
    run_id: UUID,
    *,
    status: str | None = None,
    stage: str | None = None,
    current_case: str | None = None,
    current_case_index: int | None = None,
    log_seq: int | None = None,
    error_message: str | None = None,
    completed_at: datetime | None = None,
) -> None:
    """Update eval run operational state and bump heartbeat."""
    values: dict = {"heartbeat_at": sa.func.now()}
    if status is not None:
        values["status"] = status
    if stage is not None:
        values["stage"] = stage
    if current_case is not None:
        values["current_case"] = current_case
    if current_case_index is not None:
        values["current_case_index"] = current_case_index
    if log_seq is not None:
        values["log_seq"] = log_seq
    if error_message is not None:
        values["error_message"] = error_message
    if completed_at is not None:
        values["completed_at"] = completed_at

    stmt = (
        sa.update(eval_runs_table)
        .where(eval_runs_table.c.id == run_id)
        .values(**values)
    )
    conn.execute(stmt)
    if status is not None:
        logger.debug("Eval run {} → status={} stage={}", run_id, status, stage)


def update_eval_run_heartbeat(conn: Connection, run_id: UUID) -> None:
    """Lightweight heartbeat-only update."""
    stmt = (
        sa.update(eval_runs_table)
        .where(eval_runs_table.c.id == run_id)
        .values(heartbeat_at=sa.func.now())
    )
    conn.execute(stmt)


def find_eval_run(conn: Connection, run_id: UUID) -> EvalRun | None:
    """Find an eval run by its ID."""
    stmt = sa.select(eval_runs_table).where(eval_runs_table.c.id == run_id)
    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_eval_run(row)


def find_latest_eval_run_for_version(
    conn: Connection, version_id: UUID
) -> EvalRun | None:
    """Find the most recent eval run for a given version."""
    stmt = (
        sa.select(eval_runs_table)
        .where(eval_runs_table.c.version_id == version_id)
        .order_by(eval_runs_table.c.created_at.desc())
        .limit(1)
    )
    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_eval_run(row)


def find_eval_runs_for_version(
    conn: Connection, version_id: UUID
) -> list[EvalRun]:
    """List all eval runs for a version, newest first."""
    stmt = (
        sa.select(eval_runs_table)
        .where(eval_runs_table.c.version_id == version_id)
        .order_by(eval_runs_table.c.created_at.desc())
    )
    rows = conn.execute(stmt).all()
    return [_row_to_eval_run(row) for row in rows]


def find_active_eval_runs_for_user(
    conn: Connection, user_id: UUID, limit: int = 10
) -> list[EvalRun]:
    """Find recent eval runs for a user, newest first."""
    stmt = (
        sa.select(eval_runs_table)
        .where(eval_runs_table.c.user_id == user_id)
        .order_by(eval_runs_table.c.created_at.desc())
        .limit(limit)
    )
    rows = conn.execute(stmt).all()
    return [_row_to_eval_run(row) for row in rows]
