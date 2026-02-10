#!/usr/bin/env python3
"""Check that migration files have unique sequence numbers.

Catches the common case where two developers on parallel branches both create
migration 009_*.sql. Run as a pre-commit hook or in CI.
"""

import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "server" / "migrations"


def main() -> int:
    if not MIGRATIONS_DIR.exists():
        return 0

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    prefixes: dict[str, list[str]] = {}

    for f in sql_files:
        # Extract numeric prefix (e.g. "008" from "008_add_semver_int_columns.sql")
        prefix = f.name.split("_", 1)[0]
        prefixes.setdefault(prefix, []).append(f.name)

    errors = False
    for prefix, files in prefixes.items():
        if len(files) > 1:
            print(f"ERROR: Duplicate migration prefix {prefix}:")
            for name in files:
                print(f"  - {name}")
            errors = True

    if errors:
        print("\nTwo branches likely created migrations with the same sequence number.")
        print("Renumber one of them before merging.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
