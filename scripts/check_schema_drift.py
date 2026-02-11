#!/usr/bin/env python3
"""Detect schema drift between SQL migrations and SQLAlchemy metadata.

Applies all SQL migration files to the `public` schema, then runs
metadata.create_all() into a separate `metadata_check` schema. Compares
tables and columns (name, type, nullable) between the two and exits 1
on differences.

Requires DATABASE_URL env var pointing to an empty Postgres database.
Intended for CI use only.
"""

import os
import sys
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "server" / "migrations"
METADATA_CHECK_SCHEMA = "metadata_check"


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL env var is required.")
        sys.exit(1)
    return url


def _apply_migrations(engine: sa.engine.Engine) -> None:
    """Apply all SQL migration files to the public schema."""
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for f in files:
        sql = f.read_text()
        with engine.begin() as conn:
            conn.execute(text(sql))


def _create_metadata_schema(engine: sa.engine.Engine) -> None:
    """Create SQLAlchemy metadata tables in a separate schema for comparison."""
    from decision_hub.infra.database import metadata

    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {METADATA_CHECK_SCHEMA}"))

    # Create all tables in the check schema
    metadata.create_all(engine, checkfirst=True)

    # metadata.create_all creates in public; we need a fresh schema comparison.
    # Drop and recreate using schema-qualified metadata instead.
    with engine.begin() as conn:
        # Drop and recreate using schema-qualified metadata
        conn.execute(text(f"DROP SCHEMA IF EXISTS {METADATA_CHECK_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {METADATA_CHECK_SCHEMA}"))

    check_metadata = sa.MetaData(schema=METADATA_CHECK_SCHEMA)
    for table in metadata.sorted_tables:
        table.to_metadata(check_metadata)
    check_metadata.create_all(engine)


def _compare_schemas(engine: sa.engine.Engine) -> list[str]:
    """Compare public schema (migrations) with metadata_check schema (SQLAlchemy).

    Returns a list of difference descriptions. Empty list means no drift.
    """
    insp = inspect(engine)
    differences: list[str] = []

    migration_tables = set(insp.get_table_names(schema="public"))
    metadata_tables = set(insp.get_table_names(schema=METADATA_CHECK_SCHEMA))

    # Ignore tracking tables not in SQLAlchemy metadata
    migration_tables.discard("schema_migrations")

    # Tables only in migrations
    for t in sorted(migration_tables - metadata_tables):
        differences.append(f"Table '{t}' exists in migrations but not in SQLAlchemy metadata")

    # Tables only in metadata
    for t in sorted(metadata_tables - migration_tables):
        differences.append(f"Table '{t}' exists in SQLAlchemy metadata but not in migrations")

    # Compare columns for shared tables
    for table_name in sorted(migration_tables & metadata_tables):
        mig_cols = {c["name"]: c for c in insp.get_columns(table_name, schema="public")}
        meta_cols = {c["name"]: c for c in insp.get_columns(table_name, schema=METADATA_CHECK_SCHEMA)}

        for col in sorted(set(mig_cols) - set(meta_cols)):
            differences.append(f"Column '{table_name}.{col}' exists in migrations but not in metadata")

        for col in sorted(set(meta_cols) - set(mig_cols)):
            differences.append(f"Column '{table_name}.{col}' exists in metadata but not in migrations")

        for col in sorted(set(mig_cols) & set(meta_cols)):
            m = mig_cols[col]
            s = meta_cols[col]
            mig_type = str(m["type"])
            meta_type = str(s["type"])
            if mig_type != meta_type:
                differences.append(
                    f"Column '{table_name}.{col}' type differs: migrations={mig_type}, metadata={meta_type}"
                )
            if m["nullable"] != s["nullable"]:
                differences.append(
                    f"Column '{table_name}.{col}' nullable differs: "
                    f"migrations={m['nullable']}, metadata={s['nullable']}"
                )

    return differences


def main() -> int:
    database_url = _get_database_url()
    engine = sa.create_engine(database_url, poolclass=NullPool)

    print("Applying migrations to public schema...")
    _apply_migrations(engine)

    print("Creating SQLAlchemy metadata in check schema...")
    _create_metadata_schema(engine)

    print("Comparing schemas...")
    differences = _compare_schemas(engine)

    if differences:
        print(f"\nSchema drift detected ({len(differences)} difference(s)):")
        for diff in differences:
            print(f"  - {diff}")
        print("\nEnsure SQL migrations and SQLAlchemy table definitions are in sync.")
        return 1

    print("No schema drift detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
