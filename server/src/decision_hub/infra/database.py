"""SQLAlchemy Core tables and query functions for Decision Hub.

All tables use PostgreSQL-specific types (UUID, JSONB) and are designed for
Supabase/PgBouncer compatibility (NullPool, statement_cache_size=0).
Query functions accept a Connection as their first argument and return
frozen dataclass instances from decision_hub.models.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from loguru import logger
from pgvector.sqlalchemy import Vector
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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

from decision_hub.models import (
    AuditLogEntry,
    EvalReport,
    EvalRun,
    Organization,
    OrgMember,
    Skill,
    SkillAccessGrant,
    SkillTracker,
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
    Column("github_id", Text, nullable=False, unique=True),
    Column("username", Text, nullable=False, unique=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
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
    Column("slug", Text, nullable=False, unique=True),
    Column(
        "owner_id",
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    ),
    Column("is_personal", Boolean, nullable=False, server_default="false"),
    Column("email", Text, nullable=True),
    Column("avatar_url", Text, nullable=True),
    Column("description", Text, nullable=True),
    Column("blog", Text, nullable=True),
    Column("github_synced_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
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
    Column("role", Text, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
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
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    Column("download_count", sa.Integer, nullable=False, server_default="0"),
    Column("category", String, nullable=False, server_default=""),
    Column("visibility", String(10), nullable=False, server_default="public"),
    Column("source_repo_url", Text, nullable=True),
    Column("search_vector", TSVECTOR, nullable=True),
    Column("embedding", Vector(768), nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.UniqueConstraint("org_id", "name"),
    sa.Index("idx_skills_created_at", "created_at"),
    sa.Index("idx_skills_search_vector", "search_vector", postgresql_using="gin"),
)

sa.Index(
    "idx_skills_embedding_hnsw",
    skills_table.c.embedding,
    postgresql_using="hnsw",
    postgresql_with={"m": 16, "ef_construction": 64},
    postgresql_ops={"embedding": "vector_cosine_ops"},
)

skill_access_grants_table = Table(
    "skill_access_grants",
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
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "grantee_org_id",
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=False,
    ),
    Column(
        "granted_by",
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.UniqueConstraint("skill_id", "grantee_org_id"),
    sa.Index("idx_skill_access_grants_grantee_org", "grantee_org_id"),
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
    Column("semver", Text, nullable=False),
    Column("semver_major", sa.Integer, nullable=False, server_default="0"),
    Column("semver_minor", sa.Integer, nullable=False, server_default="0"),
    Column("semver_patch", sa.Integer, nullable=False, server_default="0"),
    Column("s3_key", Text, nullable=False),
    Column("checksum", Text, nullable=False),
    Column("runtime_config", JSONB, nullable=True),
    Column("eval_status", Text, nullable=False, server_default="pending"),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    Column("published_by", Text, nullable=False, server_default=""),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.UniqueConstraint("skill_id", "semver"),
    sa.Index(
        "idx_versions_skill_semver_parts",
        "skill_id",
        sa.text("semver_major DESC"),
        sa.text("semver_minor DESC"),
        sa.text("semver_patch DESC"),
    ),
    sa.Index(
        "idx_versions_eval_status_partial",
        "eval_status",
        postgresql_where=sa.text("eval_status IN ('A', 'B', 'passed')"),
    ),
    sa.Index("idx_versions_updated_at", "updated_at"),
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
    Column("key_name", Text, nullable=False),
    Column("encrypted_value", LargeBinary, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    Column(
        "updated_at",
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
    Column("semver", Text, nullable=False),
    Column("grade", String(1), nullable=False),
    Column(
        "version_id",
        PG_UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("check_results", JSONB, nullable=False),
    Column("llm_reasoning", JSONB, nullable=True),
    Column("publisher", Text, nullable=False, server_default=""),
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
    Column("agent", Text, nullable=False),
    Column("judge_model", Text, nullable=False),
    Column("case_results", JSONB, nullable=False),
    Column("passed", sa.Integer, nullable=False),
    Column("total", sa.Integer, nullable=False),
    Column("total_duration_ms", sa.Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("error_message", Text, nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Index("idx_eval_reports_updated_at", "updated_at"),
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
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Index("idx_eval_runs_version_created", "version_id", "created_at"),
    sa.Index("idx_eval_runs_user_created", "user_id", "created_at"),
    sa.Index("idx_eval_runs_updated_at", "updated_at"),
)

search_logs_table = Table(
    "search_logs",
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
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("query_preview", String(500), nullable=False),
    Column("s3_key", Text, nullable=False),
    Column("results_count", sa.Integer, nullable=False, server_default=sa.text("0")),
    Column("model", String(100), nullable=True),
    Column("latency_ms", sa.Integer, nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)

skill_trackers_table = Table(
    "skill_trackers",
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
    Column("org_slug", Text, nullable=False),
    Column("repo_url", Text, nullable=False),
    Column("branch", String, nullable=False, server_default="main"),
    Column("last_commit_sha", String, nullable=True),
    Column("poll_interval_minutes", sa.Integer, nullable=False, server_default="60"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("last_checked_at", DateTime(timezone=True), nullable=True),
    Column("last_published_at", DateTime(timezone=True), nullable=True),
    Column("last_error", Text, nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.UniqueConstraint("user_id", "repo_url", "branch"),
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
        connect_args={"options": "-c statement_cache_size=0 -c statement_timeout=30000"},
    )


# ---------------------------------------------------------------------------
# Row-to-model helpers
# ---------------------------------------------------------------------------


def _row_to_user(row: sa.Row) -> User:
    """Map a database row to a User model."""
    return User(
        id=row.id,
        github_id=row.github_id,
        username=row.username,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_organization(row: sa.Row) -> Organization:
    """Map a database row to an Organization model."""
    return Organization(
        id=row.id,
        slug=row.slug,
        owner_id=row.owner_id,
        is_personal=row.is_personal,
        email=row.email,
        avatar_url=row.avatar_url,
        description=row.description,
        blog=row.blog,
        github_synced_at=row.github_synced_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_org_member(row: sa.Row) -> OrgMember:
    """Map a database row to an OrgMember model."""
    return OrgMember(
        org_id=row.org_id,
        user_id=row.user_id,
        role=row.role,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_skill(row: sa.Row) -> Skill:
    """Map a database row to a Skill model."""
    return Skill(
        id=row.id,
        org_id=row.org_id,
        name=row.name,
        description=row.description,
        download_count=row.download_count,
        category=row.category,
        visibility=row.visibility,
        source_repo_url=row.source_repo_url,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


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
        updated_at=row.updated_at,
    )


def _row_to_user_api_key(row: sa.Row) -> UserApiKey:
    """Map a database row to a UserApiKey model."""
    return UserApiKey(
        id=row.id,
        user_id=row.user_id,
        key_name=row.key_name,
        encrypted_value=row.encrypted_value,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# User queries
# ---------------------------------------------------------------------------


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


def insert_organization(conn: Connection, slug: str, owner_id: UUID, *, is_personal: bool = False) -> Organization:
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
    stmt = sa.select(organizations_table).where(organizations_table.c.slug == slug)
    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_organization(row)


def list_all_org_profiles(conn: Connection) -> list[Organization]:
    """Return all organizations (public listing)."""
    stmt = sa.select(organizations_table).order_by(organizations_table.c.slug)
    rows = conn.execute(stmt).all()
    return [_row_to_organization(row) for row in rows]


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


def update_org_github_metadata(
    conn: Connection,
    org_id: UUID,
    *,
    avatar_url: str | None = None,
    email: str | None = None,
    description: str | None = None,
    blog: str | None = None,
) -> None:
    """Update GitHub-sourced metadata and set github_synced_at = now()."""
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


# ---------------------------------------------------------------------------
# Org member queries
# ---------------------------------------------------------------------------


def insert_org_member(conn: Connection, org_id: UUID, user_id: UUID, role: str) -> OrgMember:
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
        sa.insert(org_members_table).values(org_id=org_id, user_id=user_id, role=role).returning(*org_members_table.c)
    )
    row = conn.execute(stmt).one()
    logger.debug("Added org member org={} user={} role={}", org_id, user_id, role)
    return _row_to_org_member(row)


def find_org_member(conn: Connection, org_id: UUID, user_id: UUID) -> OrgMember | None:
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
    conn: Connection,
    org_id: UUID,
    name: str,
    description: str = "",
    category: str = "",
    *,
    visibility: str = "public",
    source_repo_url: str | None = None,
) -> Skill:
    """Register a new skill under an organization.

    Args:
        conn: Active database connection.
        org_id: UUID of the owning organization.
        name: Skill name (unique within the org).
        description: Short description from SKILL.md frontmatter.
        category: Skill category from LLM classification.
        visibility: Skill visibility ('public' or 'org').
        source_repo_url: URL of the source GitHub repository.

    Returns:
        The newly created Skill.
    """
    values: dict = dict(org_id=org_id, name=name, description=description, category=category, visibility=visibility)
    if source_repo_url is not None:
        values["source_repo_url"] = source_repo_url
    stmt = sa.insert(skills_table).values(**values).returning(*skills_table.c)
    row = conn.execute(stmt).one()
    skill = _row_to_skill(row)
    logger.debug("Inserted skill name={} org={} visibility={} id={}", name, org_id, visibility, skill.id)
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


def find_skill_by_slug(
    conn: Connection,
    org_slug: str,
    skill_name: str,
    *,
    user_org_ids: list[UUID] | None = None,
) -> Skill | None:
    """Find a skill by org slug and name, with visibility filtering.

    Returns the Skill if it exists and is visible to the caller, else None.
    """
    join = skills_table.join(
        organizations_table,
        skills_table.c.org_id == organizations_table.c.id,
    )
    stmt = (
        sa.select(skills_table)
        .select_from(join)
        .where(
            sa.and_(
                organizations_table.c.slug == org_slug,
                skills_table.c.name == skill_name,
            )
        )
    )
    granted = list_granted_skill_ids(conn, user_org_ids) if user_org_ids else None
    stmt = _apply_visibility_filter(stmt, user_org_ids, granted)
    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_skill(row)


def update_skill_description(conn: Connection, skill_id: UUID, description: str) -> None:
    """Update the description of an existing skill.

    Used during re-publish to keep the description in sync with SKILL.md.
    """
    stmt = sa.update(skills_table).where(skills_table.c.id == skill_id).values(description=description)
    conn.execute(stmt)


def update_skill_category(conn: Connection, skill_id: UUID, category: str) -> None:
    """Update the category of an existing skill."""
    stmt = sa.update(skills_table).where(skills_table.c.id == skill_id).values(category=category)
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
# Skill access grant queries
# ---------------------------------------------------------------------------


def _row_to_skill_access_grant(row: sa.Row) -> SkillAccessGrant:
    """Map a database row to a SkillAccessGrant model."""
    return SkillAccessGrant(
        id=row.id,
        skill_id=row.skill_id,
        grantee_org_id=row.grantee_org_id,
        granted_by=row.granted_by,
        created_at=row.created_at,
    )


def update_skill_visibility(conn: Connection, skill_id: UUID, visibility: str) -> None:
    """Update the visibility of an existing skill."""
    stmt = sa.update(skills_table).where(skills_table.c.id == skill_id).values(visibility=visibility)
    conn.execute(stmt)


def update_skill_source_repo_url(conn: Connection, skill_id: UUID, source_repo_url: str) -> None:
    """Set or update the source GitHub repository URL for a skill."""
    stmt = sa.update(skills_table).where(skills_table.c.id == skill_id).values(source_repo_url=source_repo_url)
    conn.execute(stmt)


def insert_skill_access_grant(
    conn: Connection, skill_id: UUID, grantee_org_id: UUID, granted_by: UUID
) -> SkillAccessGrant:
    """Grant an org access to a skill. Raises IntegrityError on duplicate."""
    stmt = (
        sa.insert(skill_access_grants_table)
        .values(skill_id=skill_id, grantee_org_id=grantee_org_id, granted_by=granted_by)
        .returning(*skill_access_grants_table.c)
    )
    row = conn.execute(stmt).one()
    logger.debug("Granted access skill={} grantee_org={}", skill_id, grantee_org_id)
    return _row_to_skill_access_grant(row)


def delete_skill_access_grant(conn: Connection, skill_id: UUID, grantee_org_id: UUID) -> bool:
    """Revoke an org's access to a skill. Returns True if a row was deleted."""
    stmt = sa.delete(skill_access_grants_table).where(
        sa.and_(
            skill_access_grants_table.c.skill_id == skill_id,
            skill_access_grants_table.c.grantee_org_id == grantee_org_id,
        )
    )
    result = conn.execute(stmt)
    deleted = result.rowcount > 0
    if deleted:
        logger.debug("Revoked access skill={} grantee_org={}", skill_id, grantee_org_id)
    return deleted


def list_skill_access_grants(conn: Connection, skill_id: UUID) -> list[SkillAccessGrant]:
    """List all access grants for a skill, ordered by created_at."""
    stmt = (
        sa.select(skill_access_grants_table)
        .where(skill_access_grants_table.c.skill_id == skill_id)
        .order_by(skill_access_grants_table.c.created_at)
    )
    rows = conn.execute(stmt).all()
    return [_row_to_skill_access_grant(row) for row in rows]


def list_granted_skill_ids(conn: Connection, org_ids: list[UUID]) -> list[UUID]:
    """List all skill IDs that the given orgs have been granted access to."""
    if not org_ids:
        return []
    stmt = (
        sa.select(skill_access_grants_table.c.skill_id)
        .where(skill_access_grants_table.c.grantee_org_id.in_(org_ids))
        .distinct()
    )
    rows = conn.execute(stmt).all()
    return [row.skill_id for row in rows]


def list_user_org_ids(conn: Connection, user_id: UUID) -> list[UUID]:
    """Return just the org IDs for a user (lightweight, for visibility filtering)."""
    stmt = sa.select(org_members_table.c.org_id).where(org_members_table.c.user_id == user_id)
    rows = conn.execute(stmt).all()
    return [row.org_id for row in rows]


def _apply_visibility_filter(
    stmt: sa.Select,
    user_org_ids: list[UUID] | None,
    granted_skill_ids: list[UUID] | None = None,
) -> sa.Select:
    """Apply visibility filtering to a query that includes skills_table.

    A skill is visible if any of:
    1. visibility == 'public'
    2. visibility == 'org' AND the skill's org_id is in user_org_ids
    3. visibility == 'org' AND the skill's id has been granted to one of user_org_ids

    granted_skill_ids should be pre-computed via list_granted_skill_ids() and
    passed in to avoid redundant DB round-trips when this filter is applied
    to multiple queries in the same request.
    """
    if user_org_ids is not None:
        vis_conditions: list[sa.ColumnElement] = [
            skills_table.c.visibility == "public",
            sa.and_(
                skills_table.c.visibility == "org",
                skills_table.c.org_id.in_(user_org_ids),
            ),
        ]
        if granted_skill_ids:
            vis_conditions.append(
                sa.and_(
                    skills_table.c.visibility == "org",
                    skills_table.c.id.in_(granted_skill_ids),
                )
            )
        stmt = stmt.where(sa.or_(*vis_conditions))
    else:
        # Unauthenticated: only public skills
        stmt = stmt.where(skills_table.c.visibility == "public")
    return stmt


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
    *,
    user_org_ids: list[UUID] | None = None,
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
        user_org_ids: Org IDs the caller belongs to (None = unauthenticated).

    Returns:
        The resolved Version, or None if no matching version exists.
    """
    # Join versions -> skills -> organizations to resolve by slug + name
    join = versions_table.join(skills_table, versions_table.c.skill_id == skills_table.c.id).join(
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

    # Visibility filter
    granted = list_granted_skill_ids(conn, user_org_ids) if user_org_ids else None
    base = _apply_visibility_filter(base, user_org_ids, granted)

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
    *,
    user_org_ids: list[UUID] | None = None,
) -> Version | None:
    """Find the latest version of a skill regardless of eval_status.

    Used for auto-bumping: the publisher needs to know the highest
    published semver even if it hasn't passed evaluation yet.

    Args:
        conn: Active database connection.
        org_slug: Organization slug that owns the skill.
        skill_name: Name of the skill.
        user_org_ids: Org IDs the caller belongs to (None = unauthenticated).
    """
    join = versions_table.join(skills_table, versions_table.c.skill_id == skills_table.c.id).join(
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
    )

    granted = list_granted_skill_ids(conn, user_org_ids) if user_org_ids else None
    stmt = _apply_visibility_filter(stmt, user_org_ids, granted)

    stmt = stmt.order_by(
        versions_table.c.semver_major.desc(),
        versions_table.c.semver_minor.desc(),
        versions_table.c.semver_patch.desc(),
    ).limit(1)

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
    select_stmt = sa.select(versions_table.c.s3_key).where(versions_table.c.skill_id == skill_id)
    rows = conn.execute(select_stmt).all()
    s3_keys = [row.s3_key for row in rows]

    delete_stmt = sa.delete(versions_table).where(versions_table.c.skill_id == skill_id)
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
    stmt = sa.select(user_api_keys_table).where(user_api_keys_table.c.user_id == user_id)
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


def _build_skills_filters(
    base: sa.Select,
    latest_version_ref: sa.FromClause,
    *,
    search: str | None = None,
    org_slug: str | None = None,
    category: str | None = None,
    grade: str | None = None,
) -> sa.Select:
    """Apply optional filter predicates to a skills query.

    Shared between fetch_all_skills_for_index and count_all_skills to
    keep filter logic consistent. latest_version_ref is needed for grade
    filtering (eval_status lives on the lateral/exists subquery).
    """
    if search:
        pattern = f"%{search}%"
        base = base.where(
            sa.or_(
                skills_table.c.name.ilike(pattern),
                skills_table.c.description.ilike(pattern),
                organizations_table.c.slug.ilike(pattern),
            )
        )
    if org_slug:
        base = base.where(organizations_table.c.slug == org_slug)
    if category:
        base = base.where(skills_table.c.category == category)
    if grade:
        grade_statuses = {
            "A": ["A", "passed"],
            "B": ["B"],
            "C": ["C"],
        }
        statuses = grade_statuses.get(grade, [grade])
        base = base.where(latest_version_ref.c.eval_status.in_(statuses))
    return base


def fetch_all_skills_for_index(
    conn: Connection,
    *,
    user_org_ids: list[UUID] | None = None,
    granted_skill_ids: list[UUID] | None = None,
    limit: int | None = None,
    offset: int = 0,
    search: str | None = None,
    org_slug: str | None = None,
    category: str | None = None,
    grade: str | None = None,
    sort: str = "updated",
) -> tuple[list[dict], int]:
    """Fetch skills with their latest version info, with optional filters.

    Returns a tuple of (items, total) where items is a list of dicts with
    keys: org_slug, skill_name, latest_version, eval_status, visibility, etc.
    total is the full count of matching rows (before LIMIT/OFFSET), computed
    via a COUNT(*) OVER() window function to avoid a separate count query.

    Uses a LATERAL subquery to find the latest version per skill via one
    index lookup each (ordered by semver parts numerically), leveraging
    idx_versions_skill_semver_parts.

    Supports server-side filtering by search term, org, category, grade,
    and sorting by updated/name/downloads.
    """
    # LATERAL subquery: for each skill, one index scan to find the highest semver
    latest_version = (
        sa.select(
            versions_table.c.semver,
            versions_table.c.eval_status,
            versions_table.c.created_at,
            versions_table.c.published_by,
        )
        .where(versions_table.c.skill_id == skills_table.c.id)
        .order_by(
            versions_table.c.semver_major.desc(),
            versions_table.c.semver_minor.desc(),
            versions_table.c.semver_patch.desc(),
        )
        .limit(1)
        .lateral("latest_version")
    )

    base = sa.select(
        organizations_table.c.slug.label("org_slug"),
        organizations_table.c.is_personal.label("is_personal_org"),
        skills_table.c.name.label("skill_name"),
        skills_table.c.description,
        skills_table.c.download_count,
        skills_table.c.category,
        skills_table.c.visibility,
        skills_table.c.source_repo_url,
        latest_version.c.semver.label("latest_version"),
        latest_version.c.eval_status,
        latest_version.c.created_at,
        latest_version.c.published_by,
        sa.func.count().over().label("_total"),
    ).select_from(
        skills_table.join(
            organizations_table,
            skills_table.c.org_id == organizations_table.c.id,
        ).join(
            latest_version,
            sa.literal(True),
        )
    )

    # Visibility filter
    base = _apply_visibility_filter(base, user_org_ids, granted_skill_ids)

    # Apply optional filters
    base = _build_skills_filters(
        base,
        latest_version,
        search=search,
        org_slug=org_slug,
        category=category,
        grade=grade,
    )

    # Sorting — always include (org.slug, skill.name) as tiebreaker for
    # deterministic pagination when the primary sort column has duplicates.
    tiebreaker = (organizations_table.c.slug, skills_table.c.name)
    if sort == "name":
        base = base.order_by(skills_table.c.name.asc(), *tiebreaker)
    elif sort == "downloads":
        base = base.order_by(skills_table.c.download_count.desc(), *tiebreaker)
    else:
        # "updated" — most recently published version first
        base = base.order_by(latest_version.c.created_at.desc(), *tiebreaker)

    if limit is not None:
        base = base.limit(limit).offset(offset)

    rows = conn.execute(base).all()
    total = rows[0]._total if rows else 0
    items = [
        {
            "org_slug": row.org_slug,
            "is_personal_org": row.is_personal_org,
            "skill_name": row.skill_name,
            "description": row.description,
            "download_count": row.download_count,
            "category": row.category,
            "visibility": row.visibility,
            "latest_version": row.latest_version,
            "eval_status": row.eval_status,
            "created_at": row.created_at,
            "published_by": row.published_by,
        }
        for row in rows
    ]
    return items, total


def search_skills_hybrid(
    conn: Connection,
    query: str,
    query_embedding: list[float] | None,
    *,
    user_org_ids: list[UUID] | None = None,
    category: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Hybrid retrieval: FTS + vector search, union + dedup.

    Runs two complementary queries and merges results:
    1. Full-text search via tsvector (keyword match)
    2. Vector similarity via pgvector (semantic match)

    Results are deduped by (org_slug, skill_name), with vector results
    taking precedence (better ranking signal for reranking).
    """

    # --- Shared building blocks ---
    granted = list_granted_skill_ids(conn, user_org_ids) if user_org_ids else None

    def _base_select(extra_columns: list):
        """Build the base SELECT with LATERAL version join."""
        latest_version = (
            sa.select(
                versions_table.c.semver,
                versions_table.c.eval_status,
                versions_table.c.created_at,
                versions_table.c.published_by,
            )
            .where(versions_table.c.skill_id == skills_table.c.id)
            .order_by(
                versions_table.c.semver_major.desc(),
                versions_table.c.semver_minor.desc(),
                versions_table.c.semver_patch.desc(),
            )
            .limit(1)
            .lateral("latest_version")
        )

        columns = [
            organizations_table.c.slug.label("org_slug"),
            organizations_table.c.is_personal.label("is_personal_org"),
            skills_table.c.name.label("skill_name"),
            skills_table.c.description,
            skills_table.c.download_count,
            skills_table.c.category,
            skills_table.c.visibility,
            latest_version.c.semver.label("latest_version"),
            latest_version.c.eval_status,
            latest_version.c.created_at,
            latest_version.c.published_by,
            *extra_columns,
        ]

        stmt = sa.select(*columns).select_from(
            skills_table.join(
                organizations_table,
                skills_table.c.org_id == organizations_table.c.id,
            ).join(
                latest_version,
                sa.literal(True),
            )
        )

        stmt = _apply_visibility_filter(stmt, user_org_ids, granted)
        if category:
            stmt = stmt.where(skills_table.c.category == category)

        return stmt

    # --- 1. FTS query ---
    fts_stmt = _base_select(
        [
            sa.func.ts_rank_cd(
                skills_table.c.search_vector,
                sa.func.websearch_to_tsquery("english", query),
            ).label("fts_rank"),
        ]
    )
    fts_stmt = fts_stmt.where(skills_table.c.search_vector.op("@@")(sa.func.websearch_to_tsquery("english", query)))
    fts_stmt = fts_stmt.order_by(sa.text("fts_rank DESC")).limit(limit)
    fts_rows = conn.execute(fts_stmt).all()

    # --- 2. Vector query (if embedding available) ---
    vec_rows: list = []
    if query_embedding is not None:
        vec_stmt = _base_select(
            [
                skills_table.c.embedding.cosine_distance(query_embedding).label("vec_dist"),
            ]
        )
        vec_stmt = vec_stmt.where(skills_table.c.embedding.isnot(None))
        vec_stmt = vec_stmt.order_by(sa.text("vec_dist ASC")).limit(limit)
        vec_rows = conn.execute(vec_stmt).all()

    # --- 3. Union + dedup (vector first, then FTS-only) ---
    seen: set[tuple[str, str]] = set()
    results: list[dict] = []

    def _row_to_dict(row) -> dict:
        return {
            "org_slug": row.org_slug,
            "is_personal_org": row.is_personal_org,
            "skill_name": row.skill_name,
            "description": row.description,
            "download_count": row.download_count,
            "category": row.category,
            "visibility": row.visibility,
            "latest_version": row.latest_version,
            "eval_status": row.eval_status,
            "created_at": row.created_at,
            "published_by": row.published_by,
        }

    for row in vec_rows:
        key = (row.org_slug, row.skill_name)
        if key not in seen:
            seen.add(key)
            results.append(_row_to_dict(row))

    for row in fts_rows:
        key = (row.org_slug, row.skill_name)
        if key not in seen:
            seen.add(key)
            results.append(_row_to_dict(row))

    return results


def update_skill_embedding(conn: Connection, skill_id: UUID, embedding: list[float]) -> None:
    """Store an embedding vector for a skill."""
    stmt = sa.update(skills_table).where(skills_table.c.id == skill_id).values(embedding=embedding)
    conn.execute(stmt)


def count_all_skills(
    conn: Connection,
    *,
    user_org_ids: list[UUID] | None = None,
    granted_skill_ids: list[UUID] | None = None,
    search: str | None = None,
    org_slug: str | None = None,
    category: str | None = None,
    grade: str | None = None,
) -> int:
    """Count total skills visible to the user (for pagination metadata).

    Uses an EXISTS subquery on versions_table to match the inner-join
    behavior of fetch_all_skills_for_index (only skills with at least
    one published version are counted). Accepts the same filter params
    for consistency.
    """
    if grade:
        # When filtering by grade, we need the lateral join to access eval_status
        latest_version = (
            sa.select(
                versions_table.c.eval_status,
            )
            .where(versions_table.c.skill_id == skills_table.c.id)
            .order_by(
                versions_table.c.semver_major.desc(),
                versions_table.c.semver_minor.desc(),
                versions_table.c.semver_patch.desc(),
            )
            .limit(1)
            .lateral("latest_version")
        )
        base = sa.select(sa.func.count()).select_from(
            skills_table.join(
                organizations_table,
                skills_table.c.org_id == organizations_table.c.id,
            ).join(
                latest_version,
                sa.literal(True),
            )
        )
        base = _apply_visibility_filter(base, user_org_ids, granted_skill_ids)
        base = _build_skills_filters(
            base,
            latest_version,
            search=search,
            org_slug=org_slug,
            category=category,
            grade=grade,
        )
    else:
        has_version = sa.exists().where(versions_table.c.skill_id == skills_table.c.id)
        # Create a dummy ref for _build_skills_filters (grade is None, so it won't be used)
        dummy_lateral = sa.table("latest_version", sa.column("eval_status"))
        base = (
            sa.select(sa.func.count())
            .select_from(
                skills_table.join(
                    organizations_table,
                    skills_table.c.org_id == organizations_table.c.id,
                )
            )
            .where(has_version)
        )
        base = _apply_visibility_filter(base, user_org_ids, granted_skill_ids)
        base = _build_skills_filters(
            base,
            dummy_lateral,
            search=search,
            org_slug=org_slug,
            category=category,
        )

    return conn.execute(base).scalar_one()


def fetch_registry_stats(conn: Connection) -> dict:
    """Fetch aggregate registry statistics for the homepage.

    Returns total_skills, total_orgs, and total_downloads across
    all published skills (skills with at least one version).
    """
    has_version = sa.exists().where(versions_table.c.skill_id == skills_table.c.id)

    stmt = (
        sa.select(
            sa.func.count(sa.distinct(skills_table.c.id)).label("total_skills"),
            sa.func.count(sa.distinct(organizations_table.c.slug)).label("total_orgs"),
            sa.func.coalesce(sa.func.sum(skills_table.c.download_count), 0).label("total_downloads"),
        )
        .select_from(
            skills_table.join(
                organizations_table,
                skills_table.c.org_id == organizations_table.c.id,
            )
        )
        .where(
            sa.and_(
                has_version,
                skills_table.c.visibility == "public",
            )
        )
    )

    row = conn.execute(stmt).one()

    # Active categories: distinct non-null categories across published skills
    cat_stmt = (
        sa.select(sa.distinct(skills_table.c.category))
        .where(
            sa.and_(
                skills_table.c.category.isnot(None),
                skills_table.c.category != "",
                skills_table.c.visibility == "public",
                sa.exists().where(versions_table.c.skill_id == skills_table.c.id),
            )
        )
        .order_by(skills_table.c.category)
    )
    active_categories = [r[0] for r in conn.execute(cat_stmt)]

    return {
        "total_skills": row.total_skills,
        "total_orgs": row.total_orgs,
        "total_downloads": row.total_downloads,
        "active_categories": active_categories,
    }


def fetch_org_stats(
    conn: Connection,
    *,
    search: str | None = None,
    type_filter: str = "all",
) -> list[dict]:
    """Fetch aggregated org statistics for the orgs listing page.

    Returns slug, is_personal, avatar_url, skill_count, total_downloads,
    and latest_update for each org that has at least one published skill.
    """
    # LATERAL subquery to get the latest version's created_at per skill
    latest_version = (
        sa.select(
            versions_table.c.created_at,
        )
        .where(versions_table.c.skill_id == skills_table.c.id)
        .order_by(
            versions_table.c.semver_major.desc(),
            versions_table.c.semver_minor.desc(),
            versions_table.c.semver_patch.desc(),
        )
        .limit(1)
        .lateral("latest_version")
    )

    stmt = (
        sa.select(
            organizations_table.c.slug,
            organizations_table.c.is_personal,
            organizations_table.c.avatar_url,
            sa.func.count(skills_table.c.id).label("skill_count"),
            sa.func.coalesce(sa.func.sum(skills_table.c.download_count), 0).label("total_downloads"),
            sa.func.max(latest_version.c.created_at).label("latest_update"),
        )
        .select_from(
            skills_table.join(
                organizations_table,
                skills_table.c.org_id == organizations_table.c.id,
            ).join(
                latest_version,
                sa.literal(True),
            )
        )
        .where(skills_table.c.visibility == "public")
    )

    # Filter on non-aggregate columns before grouping (WHERE, not HAVING)
    if search:
        stmt = stmt.where(organizations_table.c.slug.ilike(f"%{search}%"))

    if type_filter == "orgs":
        stmt = stmt.where(organizations_table.c.is_personal == sa.false())
    elif type_filter == "users":
        stmt = stmt.where(organizations_table.c.is_personal == sa.true())

    stmt = stmt.group_by(
        organizations_table.c.slug,
        organizations_table.c.is_personal,
        organizations_table.c.avatar_url,
    ).order_by(organizations_table.c.slug)

    rows = conn.execute(stmt).all()
    return [
        {
            "slug": row.slug,
            "is_personal": row.is_personal,
            "avatar_url": row.avatar_url,
            "skill_count": row.skill_count,
            "total_downloads": row.total_downloads,
            "latest_update": row.latest_update.isoformat() if row.latest_update else None,
        }
        for row in rows
    ]


def get_api_keys_for_eval(conn: Connection, user_id: UUID, key_names: list[str]) -> dict[str, bytes]:
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
    values: dict[str, Any] = {
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

    stmt = sa.insert(eval_audit_logs_table).values(**values).returning(*eval_audit_logs_table.c)
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
        sa.select(eval_audit_logs_table).where(sa.and_(*conditions)).order_by(eval_audit_logs_table.c.created_at.desc())
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
        updated_at=row.updated_at,
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


def find_eval_report_by_version(conn: Connection, version_id: UUID) -> EvalReport | None:
    """Find an eval report by version ID.

    Args:
        conn: Active database connection.
        version_id: UUID of the skill version.

    Returns:
        The EvalReport if found, or None.
    """
    stmt = sa.select(eval_reports_table).where(eval_reports_table.c.version_id == version_id)
    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_eval_report(row)


def find_eval_report_by_skill(conn: Connection, org_slug: str, skill_name: str, semver: str) -> EvalReport | None:
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
        updated_at=row.updated_at,
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

    stmt = sa.insert(eval_runs_table).values(**values).returning(*eval_runs_table.c)
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

    stmt = sa.update(eval_runs_table).where(eval_runs_table.c.id == run_id).values(**values)
    conn.execute(stmt)
    if status is not None:
        logger.debug("Eval run {} → status={} stage={}", run_id, status, stage)


def update_eval_run_heartbeat(conn: Connection, run_id: UUID) -> None:
    """Lightweight heartbeat-only update."""
    stmt = sa.update(eval_runs_table).where(eval_runs_table.c.id == run_id).values(heartbeat_at=sa.func.now())
    conn.execute(stmt)


def find_eval_run(conn: Connection, run_id: UUID) -> EvalRun | None:
    """Find an eval run by its ID."""
    stmt = sa.select(eval_runs_table).where(eval_runs_table.c.id == run_id)
    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_eval_run(row)


def find_latest_eval_run_for_version(conn: Connection, version_id: UUID) -> EvalRun | None:
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


def find_eval_runs_for_version(conn: Connection, version_id: UUID) -> list[EvalRun]:
    """List all eval runs for a version, newest first."""
    stmt = (
        sa.select(eval_runs_table)
        .where(eval_runs_table.c.version_id == version_id)
        .order_by(eval_runs_table.c.created_at.desc())
    )
    rows = conn.execute(stmt).all()
    return [_row_to_eval_run(row) for row in rows]


def find_active_eval_runs_for_user(conn: Connection, user_id: UUID, limit: int = 10) -> list[EvalRun]:
    """Find recent eval runs for a user, newest first."""
    stmt = (
        sa.select(eval_runs_table)
        .where(eval_runs_table.c.user_id == user_id)
        .order_by(eval_runs_table.c.created_at.desc())
        .limit(limit)
    )
    rows = conn.execute(stmt).all()
    return [_row_to_eval_run(row) for row in rows]


# ---------------------------------------------------------------------------
# Search log queries
# ---------------------------------------------------------------------------


def insert_search_log(
    conn: Connection,
    log_id: UUID,
    query: str,
    s3_key: str,
    results_count: int,
    model: str,
    latency_ms: int,
    user_id: UUID | None = None,
) -> None:
    """Insert search log metadata into the database.

    The full query and response are stored in S3; this stores lightweight
    metadata for querying and analytics.

    Args:
        conn: Active database connection.
        log_id: UUID of the search log (matches S3 filename).
        query: First 500 chars of the query for previews.
        s3_key: S3 key where the full log is stored.
        results_count: Number of skills in the search index.
        model: Model used for search (e.g. 'gemini-2.0-flash').
        latency_ms: Total search latency in milliseconds.
        user_id: ID of the user (None for anonymous searches).
    """
    values: dict[str, Any] = {
        "id": log_id,
        "query_preview": query[:500],
        "s3_key": s3_key,
        "results_count": results_count,
        "model": model,
        "latency_ms": latency_ms,
    }
    if user_id is not None:
        values["user_id"] = user_id

    stmt = sa.insert(search_logs_table).values(**values)
    conn.execute(stmt)
    logger.debug(
        "Search log metadata inserted id={} user={} results={}",
        log_id,
        user_id,
        results_count,
    )


# ---------------------------------------------------------------------------
# Skill tracker queries
# ---------------------------------------------------------------------------


def _row_to_skill_tracker(row: sa.Row) -> SkillTracker:
    """Map a database row to a SkillTracker model."""
    return SkillTracker(
        id=row.id,
        user_id=row.user_id,
        org_slug=row.org_slug,
        repo_url=row.repo_url,
        branch=row.branch,
        last_commit_sha=row.last_commit_sha,
        poll_interval_minutes=row.poll_interval_minutes,
        enabled=row.enabled,
        last_checked_at=row.last_checked_at,
        last_published_at=row.last_published_at,
        last_error=row.last_error,
        created_at=row.created_at,
    )


def insert_skill_tracker(
    conn: Connection,
    user_id: UUID,
    org_slug: str,
    repo_url: str,
    branch: str = "main",
    poll_interval_minutes: int = 60,
) -> SkillTracker:
    """Create a new skill tracker for a GitHub repo."""
    stmt = (
        sa.insert(skill_trackers_table)
        .values(
            user_id=user_id,
            org_slug=org_slug,
            repo_url=repo_url,
            branch=branch,
            poll_interval_minutes=poll_interval_minutes,
        )
        .returning(*skill_trackers_table.c)
    )
    row = conn.execute(stmt).one()
    tracker = _row_to_skill_tracker(row)
    logger.debug("Created tracker repo={} branch={} id={}", repo_url, branch, tracker.id)
    return tracker


def find_skill_tracker(conn: Connection, tracker_id: UUID) -> SkillTracker | None:
    """Find a tracker by its ID."""
    stmt = sa.select(skill_trackers_table).where(skill_trackers_table.c.id == tracker_id)
    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_skill_tracker(row)


def list_skill_trackers_for_user(conn: Connection, user_id: UUID) -> list[SkillTracker]:
    """List all trackers owned by a user."""
    stmt = (
        sa.select(skill_trackers_table)
        .where(skill_trackers_table.c.user_id == user_id)
        .order_by(skill_trackers_table.c.created_at.desc())
    )
    rows = conn.execute(stmt).all()
    return [_row_to_skill_tracker(row) for row in rows]


def claim_due_trackers(conn: Connection, *, batch_size: int = 100) -> list[SkillTracker]:
    """Atomically claim a batch of due trackers for processing.

    Uses SELECT ... FOR UPDATE SKIP LOCKED to prevent concurrent runs
    from double-processing the same tracker. Claims each selected row
    by setting last_checked_at = now(), so the next run will skip it.

    Args:
        batch_size: Maximum number of trackers to claim per invocation.
            Prevents unbounded row locks and keeps processing within
            the DB statement timeout.

    Returns the claimed SkillTracker objects (with their pre-claim state).
    """
    now = sa.func.now()
    due_filter = sa.and_(
        skill_trackers_table.c.enabled.is_(True),
        sa.or_(
            skill_trackers_table.c.last_checked_at.is_(None),
            now
            > (
                skill_trackers_table.c.last_checked_at
                + skill_trackers_table.c.poll_interval_minutes * sa.text("INTERVAL '1 minute'")
            ),
        ),
    )

    # Select due tracker IDs with row-level locking, skipping already-locked rows.
    # ORDER BY prioritises never-checked (NULLS FIRST) then most-overdue,
    # which matches the ix_skill_trackers_due index.
    # LIMIT prevents unbounded lock acquisition at scale.
    locked_ids_cte = (
        sa.select(skill_trackers_table.c.id)
        .where(due_filter)
        .order_by(skill_trackers_table.c.last_checked_at.asc().nulls_first())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
        .cte("locked_ids")
    )

    # Claim by bumping last_checked_at, returning full rows
    update_stmt = (
        sa.update(skill_trackers_table)
        .where(skill_trackers_table.c.id.in_(sa.select(locked_ids_cte.c.id)))
        .values(last_checked_at=now)
        .returning(*skill_trackers_table.c)
    )
    rows = conn.execute(update_stmt).all()
    return [_row_to_skill_tracker(row) for row in rows]


def update_skill_tracker(
    conn: Connection,
    tracker_id: UUID,
    *,
    last_commit_sha: str | None = None,
    last_checked_at: datetime | None = None,
    last_published_at: datetime | None = None,
    last_error: str | None = ...,  # type: ignore[assignment]
    enabled: bool | None = None,
    branch: str | None = None,
    poll_interval_minutes: int | None = None,
) -> None:
    """Update tracker fields. Only non-None values are updated.

    last_error uses a sentinel default (...) so that passing
    last_error=None explicitly clears the error.
    """
    values: dict = {}
    if last_commit_sha is not None:
        values["last_commit_sha"] = last_commit_sha
    if last_checked_at is not None:
        values["last_checked_at"] = last_checked_at
    if last_published_at is not None:
        values["last_published_at"] = last_published_at
    if last_error is not ...:
        values["last_error"] = last_error
    if enabled is not None:
        values["enabled"] = enabled
    if branch is not None:
        values["branch"] = branch
    if poll_interval_minutes is not None:
        values["poll_interval_minutes"] = poll_interval_minutes

    if not values:
        return

    stmt = sa.update(skill_trackers_table).where(skill_trackers_table.c.id == tracker_id).values(**values)
    conn.execute(stmt)


def delete_skill_tracker(conn: Connection, tracker_id: UUID) -> bool:
    """Delete a tracker. Returns True if a row was deleted."""
    stmt = sa.delete(skill_trackers_table).where(skill_trackers_table.c.id == tracker_id)
    result = conn.execute(stmt)
    return result.rowcount > 0
