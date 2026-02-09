"""Migration: add email column to organizations table.

Usage (from server/):
    DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.migrate_add_org_email
"""

import sqlalchemy as sa

from decision_hub.infra.database import create_engine
from decision_hub.settings import create_settings, get_env


def migrate():
    env = get_env()
    settings = create_settings(env)
    engine = create_engine(settings.database_url)

    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'organizations' AND column_name = 'email'"
        ))
        if result.first() is not None:
            print("Column 'email' already exists on organizations — nothing to do.")
            return

        conn.execute(sa.text("ALTER TABLE organizations ADD COLUMN email TEXT"))
        conn.commit()
        print(f"Added 'email' column to organizations table (env={env}).")


if __name__ == "__main__":
    migrate()
