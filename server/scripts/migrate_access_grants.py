"""Migration script: add visibility column to skills and create skill_access_grants table.

Run from the server/ directory:
    DHUB_ENV=dev uv run --package decision-hub-server python scripts/migrate_access_grants.py
    DHUB_ENV=prod uv run --package decision-hub-server python scripts/migrate_access_grants.py
"""

import sys

import sqlalchemy as sa

from decision_hub.infra.database import create_engine, metadata, skill_access_grants_table, skills_table
from decision_hub.settings import create_settings


def migrate(env: str) -> None:
    settings = create_settings(env)
    engine = create_engine(settings.database_url)

    with engine.connect() as conn:
        # 1. Add visibility column to skills table if it doesn't exist
        result = conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'skills' AND column_name = 'visibility'"
        ))
        if result.first() is None:
            print(f"[{env}] Adding 'visibility' column to 'skills' table...")
            conn.execute(sa.text(
                "ALTER TABLE skills ADD COLUMN visibility VARCHAR(10) NOT NULL DEFAULT 'public'"
            ))
            print(f"[{env}] Done — all existing skills default to 'public'.")
        else:
            print(f"[{env}] Column 'visibility' already exists on 'skills' — skipping.")

        # 2. Create skill_access_grants table if it doesn't exist
        result = conn.execute(sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = 'skill_access_grants'"
        ))
        if result.first() is None:
            print(f"[{env}] Creating 'skill_access_grants' table...")
            skill_access_grants_table.create(conn)
            print(f"[{env}] Done.")
        else:
            print(f"[{env}] Table 'skill_access_grants' already exists — skipping.")

        conn.commit()

    print(f"[{env}] Migration complete.")


if __name__ == "__main__":
    import os

    env = os.environ.get("DHUB_ENV", "dev")
    print(f"Running migration for environment: {env}")
    migrate(env)
