"""SQLAlchemy Core tables and query functions for Decision Hub.

All tables use PostgreSQL-specific types (UUID, JSONB) and are designed for
Supabase/PgBouncer compatibility (NullPool, statement_cache_size=0).
Query functions accept a Connection as their first argument and return
frozen dataclass instances from decision_hub.models.
"""

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import (
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
    Organization,
    OrgInvite,
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
    Column("username", String, nullable=False),
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

org_invites_table = Table(
    "org_invites",
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
    Column("invitee_github_username", String, nullable=False),
    Column("status", String, nullable=False, server_default="pending"),
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
    Column("s3_key", Text, nullable=False),
    Column("checksum", String, nullable=False),
    Column("runtime_config", JSONB, nullable=True),
    Column("eval_status", String, nullable=False, server_default="pending"),
    sa.UniqueConstraint("skill_id", "semver"),
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
    return Organization(id=row.id, slug=row.slug, owner_id=row.owner_id)


def _row_to_org_member(row: sa.Row) -> OrgMember:
    """Map a database row to an OrgMember model."""
    return OrgMember(org_id=row.org_id, user_id=row.user_id, role=row.role)


def _row_to_org_invite(row: sa.Row) -> OrgInvite:
    """Map a database row to an OrgInvite model."""
    return OrgInvite(
        id=row.id,
        org_id=row.org_id,
        invitee_github_username=row.invitee_github_username,
        status=row.status,
    )


def _row_to_skill(row: sa.Row) -> Skill:
    """Map a database row to a Skill model."""
    return Skill(id=row.id, org_id=row.org_id, name=row.name)


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
    return _row_to_user(row)


# ---------------------------------------------------------------------------
# Organization queries
# ---------------------------------------------------------------------------


def insert_organization(
    conn: Connection, slug: str, owner_id: UUID
) -> Organization:
    """Create a new organization.

    Args:
        conn: Active database connection.
        slug: Unique organization slug.
        owner_id: UUID of the owning user.

    Returns:
        The newly created Organization.
    """
    stmt = (
        sa.insert(organizations_table)
        .values(slug=slug, owner_id=owner_id)
        .returning(*organizations_table.c)
    )
    row = conn.execute(stmt).one()
    return _row_to_organization(row)


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
# Org invite queries
# ---------------------------------------------------------------------------


def insert_org_invite(
    conn: Connection, org_id: UUID, invitee_github_username: str
) -> OrgInvite:
    """Create a pending invitation to an organization.

    Args:
        conn: Active database connection.
        org_id: UUID of the organization.
        invitee_github_username: GitHub username of the person being invited.

    Returns:
        The newly created OrgInvite with status 'pending'.
    """
    stmt = (
        sa.insert(org_invites_table)
        .values(org_id=org_id, invitee_github_username=invitee_github_username)
        .returning(*org_invites_table.c)
    )
    row = conn.execute(stmt).one()
    return _row_to_org_invite(row)


def find_invite(conn: Connection, invite_id: UUID) -> OrgInvite | None:
    """Find an invitation by its ID.

    Args:
        conn: Active database connection.
        invite_id: UUID of the invitation.

    Returns:
        The OrgInvite if found, or None.
    """
    stmt = sa.select(org_invites_table).where(
        org_invites_table.c.id == invite_id
    )
    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_org_invite(row)


def accept_invite(conn: Connection, invite_id: UUID) -> OrgInvite:
    """Mark an invitation as accepted.

    Args:
        conn: Active database connection.
        invite_id: UUID of the invitation to accept.

    Returns:
        The updated OrgInvite with status 'accepted'.

    Raises:
        sqlalchemy.exc.NoResultFound: If no invite with the given ID exists.
    """
    stmt = (
        sa.update(org_invites_table)
        .where(org_invites_table.c.id == invite_id)
        .values(status="accepted")
        .returning(*org_invites_table.c)
    )
    row = conn.execute(stmt).one()
    return _row_to_org_invite(row)


# ---------------------------------------------------------------------------
# Skill queries
# ---------------------------------------------------------------------------


def insert_skill(conn: Connection, org_id: UUID, name: str) -> Skill:
    """Register a new skill under an organization.

    Args:
        conn: Active database connection.
        org_id: UUID of the owning organization.
        name: Skill name (unique within the org).

    Returns:
        The newly created Skill.
    """
    stmt = (
        sa.insert(skills_table)
        .values(org_id=org_id, name=name)
        .returning(*skills_table.c)
    )
    row = conn.execute(stmt).one()
    return _row_to_skill(row)


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


# ---------------------------------------------------------------------------
# Version queries
# ---------------------------------------------------------------------------


def insert_version(
    conn: Connection,
    skill_id: UUID,
    semver: str,
    s3_key: str,
    checksum: str,
    runtime_config: dict | None,
) -> Version:
    """Record a new published version of a skill.

    Args:
        conn: Active database connection.
        skill_id: UUID of the parent skill.
        semver: Semantic version string (e.g. '1.2.3').
        s3_key: S3 object key where the skill zip is stored.
        checksum: SHA256 hex digest of the skill zip.
        runtime_config: Optional runtime configuration as a JSON-compatible dict.

    Returns:
        The newly created Version with status 'pending'.
    """
    stmt = (
        sa.insert(versions_table)
        .values(
            skill_id=skill_id,
            semver=semver,
            s3_key=s3_key,
            checksum=checksum,
            runtime_config=runtime_config,
        )
        .returning(*versions_table.c)
    )
    row = conn.execute(stmt).one()
    return _row_to_version(row)


def resolve_version(
    conn: Connection,
    org_slug: str,
    skill_name: str,
    spec: str,
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

    if spec == "latest":
        # Split semver into major.minor.patch and sort numerically descending
        major = sa.cast(
            sa.func.split_part(versions_table.c.semver, ".", 1), sa.Integer
        )
        minor = sa.cast(
            sa.func.split_part(versions_table.c.semver, ".", 2), sa.Integer
        )
        patch = sa.cast(
            sa.func.split_part(versions_table.c.semver, ".", 3), sa.Integer
        )
        stmt = base.order_by(
            major.desc(), minor.desc(), patch.desc()
        ).limit(1)
    else:
        stmt = base.where(versions_table.c.semver == spec)

    row = conn.execute(stmt).first()
    if row is None:
        return None
    return _row_to_version(row)


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
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Search index queries (Sprint 4)
# ---------------------------------------------------------------------------


def fetch_all_skills_for_index(conn: Connection) -> list[dict]:
    """Fetch all skills with their latest version info for the search index.

    Returns a list of dicts, each with keys: org_slug, skill_name,
    latest_version, eval_status. Uses a subquery to find the latest
    version per skill (ordered by semver parts numerically).
    """
    # Subquery: for each skill, find the highest semver
    major = sa.cast(
        sa.func.split_part(versions_table.c.semver, ".", 1), sa.Integer
    )
    minor = sa.cast(
        sa.func.split_part(versions_table.c.semver, ".", 2), sa.Integer
    )
    patch = sa.cast(
        sa.func.split_part(versions_table.c.semver, ".", 3), sa.Integer
    )

    latest_version = (
        sa.select(
            versions_table.c.skill_id,
            versions_table.c.semver,
            versions_table.c.eval_status,
            sa.func.row_number()
            .over(
                partition_by=versions_table.c.skill_id,
                order_by=[major.desc(), minor.desc(), patch.desc()],
            )
            .label("rn"),
        )
    ).subquery("ranked")

    stmt = (
        sa.select(
            organizations_table.c.slug.label("org_slug"),
            skills_table.c.name.label("skill_name"),
            latest_version.c.semver.label("latest_version"),
            latest_version.c.eval_status,
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
            "skill_name": row.skill_name,
            "latest_version": row.latest_version,
            "eval_status": row.eval_status,
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
