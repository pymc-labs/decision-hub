#!/usr/bin/env python3
"""Validate migration file naming and detect duplicate prefixes/timestamps.

Accepts two filename formats:
  - Legacy:  NNN_description.sql  (3-digit numeric, covers existing 001-011)
  - New:     YYYYMMDD_HHMMSS_description.sql  (timestamp-based)

Run as a pre-commit hook or in CI.
"""

import re
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "server" / "migrations"

LEGACY_RE = re.compile(r"^(\d{3})_\w+\.sql$")
TIMESTAMP_RE = re.compile(r"^(\d{8}_\d{6})_\w+\.sql$")


def main() -> int:
    if not MIGRATIONS_DIR.exists():
        return 0

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        return 0

    errors: list[str] = []
    legacy_prefixes: dict[str, list[str]] = {}
    timestamp_prefixes: dict[str, list[str]] = {}

    for f in sql_files:
        legacy_match = LEGACY_RE.match(f.name)
        timestamp_match = TIMESTAMP_RE.match(f.name)

        if legacy_match:
            prefix = legacy_match.group(1)
            legacy_prefixes.setdefault(prefix, []).append(f.name)
        elif timestamp_match:
            prefix = timestamp_match.group(1)
            timestamp_prefixes.setdefault(prefix, []).append(f.name)
        else:
            errors.append(f"ERROR: Unrecognized migration filename format: {f.name}")
            errors.append("  Expected: NNN_description.sql (legacy) or YYYYMMDD_HHMMSS_description.sql (new)")

    # Check for duplicate legacy prefixes
    for prefix, files in legacy_prefixes.items():
        if len(files) > 1:
            errors.append(f"ERROR: Duplicate legacy migration prefix {prefix}:")
            for name in files:
                errors.append(f"  - {name}")

    # Check for duplicate timestamps
    for prefix, files in timestamp_prefixes.items():
        if len(files) > 1:
            errors.append(f"ERROR: Duplicate timestamp migration prefix {prefix}:")
            for name in files:
                errors.append(f"  - {name}")

    if errors:
        for line in errors:
            print(line)
        print("\nFix migration filenames before merging.")
        return 1

    print(f"OK: {len(sql_files)} migration files validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
