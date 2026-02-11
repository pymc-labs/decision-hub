#!/usr/bin/env python3
"""Apply SQL migration files with tracking.

Replaces metadata.create_all() as the migration mechanism. Each migration
runs in its own transaction, recorded in a schema_migrations tracking table.

Bootstrap logic: on first run against an existing DB (has `users` table but
empty schema_migrations), seeds all legacy NNN_ prefixed files as already
applied so they are not re-run.

Usage:
    cd server && DHUB_ENV=dev uv run --package decision-hub-server python ../scripts/run_migrations.py
    DATABASE_URL=postgresql://... python scripts/run_migrations.py
"""

import os
import re
import sys
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "server" / "migrations"

LEGACY_PREFIX_RE = re.compile(r"^\d{3}_.*\.sql$")


def _get_database_url() -> str:
    """Resolve DATABASE_URL from env var or settings."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    # Fall back to pydantic-settings (requires running from server/)
    from decision_hub.settings import create_settings

    env = os.environ.get("DHUB_ENV", "prod")
    settings = create_settings(env)
    return settings.database_url


def _ensure_tracking_table(conn: sa.engine.Connection) -> None:
    """Create the schema_migrations tracking table if it doesn't exist."""
    conn.execute(
        text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename    TEXT PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
    )


def _has_table(conn: sa.engine.Connection, table_name: str) -> bool:
    """Check whether a table exists in the public schema."""
    result = conn.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = :name
            )
        """),
        {"name": table_name},
    )
    return result.scalar()


def _get_applied(conn: sa.engine.Connection) -> set[str]:
    """Return the set of already-applied migration filenames."""
    rows = conn.execute(text("SELECT filename FROM schema_migrations"))
    return {row[0] for row in rows}


def _get_migration_files() -> list[Path]:
    """Return sorted list of .sql files in the migrations directory."""
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _bootstrap_legacy(conn: sa.engine.Connection, files: list[Path]) -> None:
    """Seed legacy migration files as already applied on existing databases.

    Called on first run when schema_migrations is empty but the DB already has
    tables (created by metadata.create_all()). Marks all legacy NNN_ prefixed
    files as applied so they won't be re-executed.
    """
    legacy_files = [f for f in files if LEGACY_PREFIX_RE.match(f.name)]
    if not legacy_files:
        return

    print(f"  Bootstrapping {len(legacy_files)} legacy migrations as already applied...")
    for f in legacy_files:
        conn.execute(
            text("INSERT INTO schema_migrations (filename) VALUES (:name)"),
            {"name": f.name},
        )
        print(f"    seeded: {f.name}")


def run_migrations() -> int:
    """Apply pending migrations. Returns 0 on success, 1 on error."""
    database_url = _get_database_url()
    engine = sa.create_engine(database_url, poolclass=NullPool)

    files = _get_migration_files()
    if not files:
        print("No migration files found.")
        return 0

    with engine.begin() as conn:
        _ensure_tracking_table(conn)

        # Bootstrap: existing DB with no tracking history
        applied = _get_applied(conn)
        if not applied and _has_table(conn, "users"):
            _bootstrap_legacy(conn, files)
            applied = _get_applied(conn)

    # Apply each pending migration in its own transaction
    pending = [f for f in files if f.name not in applied]
    if not pending:
        print("All migrations already applied.")
        return 0

    print(f"Applying {len(pending)} migration(s)...")
    for f in pending:
        sql = f.read_text()
        print(f"  Applying: {f.name}...", end=" ", flush=True)
        with engine.begin() as conn:
            conn.execute(text(sql))
            conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:name)"),
                {"name": f.name},
            )
        print("OK")

    print(f"Done. {len(pending)} migration(s) applied.")
    return 0


if __name__ == "__main__":
    sys.exit(run_migrations())
