# PR #29 — Add created_at/updated_at Timestamps to All Tables

## Overview

Add `created_at` and `updated_at` timestamp columns to every mutable table in the database. Several tables (`versions`, `user_api_keys`, `eval_audit_logs`, `eval_reports`, `eval_runs`, `skill_trackers`) already have `created_at`; the remaining tables (`users`, `organizations`, `org_members`, `skills`) do not. No table currently has `updated_at`.

A PostgreSQL trigger function (`set_updated_at()`) auto-updates `updated_at` on every row modification. Four time-based indexes support common queries (e.g. "recently updated skills").

This is a pure infrastructure change — no API or CLI behavior changes.

## Archived Branch

- Branch: `claude/add-database-timestamps-rIhRn`
- Renamed to: `REIMPLEMENTED/claude/add-database-timestamps-rIhRn`
- Original PR: #29

## Schema Changes

### SQL Migration

Create a timestamp-based migration file (e.g. `YYYYMMDD_HHMMSS_add_timestamps.sql`) in `server/migrations/`.

```sql
-- 1. Reusable trigger function for auto-updating updated_at
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. Add created_at where missing
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE org_members ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE skills ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- 3. Add updated_at to all mutable tables
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE org_members ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE skills ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE versions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE user_api_keys ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE eval_reports ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- 4. Auto-update triggers (one per mutable table)
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_organizations_updated_at BEFORE UPDATE ON organizations FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_org_members_updated_at BEFORE UPDATE ON org_members FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_skills_updated_at BEFORE UPDATE ON skills FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_versions_updated_at BEFORE UPDATE ON versions FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_user_api_keys_updated_at BEFORE UPDATE ON user_api_keys FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_eval_reports_updated_at BEFORE UPDATE ON eval_reports FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_eval_runs_updated_at BEFORE UPDATE ON eval_runs FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 5. Indexes for time-based queries
CREATE INDEX IF NOT EXISTS idx_skills_created_at ON skills (created_at);
CREATE INDEX IF NOT EXISTS idx_versions_updated_at ON versions (updated_at);
CREATE INDEX IF NOT EXISTS idx_eval_reports_updated_at ON eval_reports (updated_at);
CREATE INDEX IF NOT EXISTS idx_eval_runs_updated_at ON eval_runs (updated_at);
```

**Important**: The original branch used filename `009_add_timestamps.sql`, which conflicts with `009_add_search_logs.sql` on main. Use a timestamp-based filename per current conventions.

### SQLAlchemy Model Updates

Add `created_at` and `updated_at` Column declarations to every table definition in `database.py`, plus `sa.Index()` for the four indexes listed above.

Tables needing new `created_at` + `updated_at`: `users_table`, `organizations_table`, `org_members_table`, `skills_table`.
Tables needing only `updated_at` (already have `created_at`): `versions_table`, `user_api_keys_table`, `eval_reports_table`, `eval_runs_table`.

Append-only tables (`eval_audit_logs`, `search_logs_table`, `skill_trackers_table`) do NOT get `updated_at`.

## API Changes

None.

## CLI Changes

None.

## Implementation Details

### Why triggers instead of application-level updates

- **Single source of truth**: Triggers guarantee `updated_at` is always current, even for raw SQL or future code paths.
- **No application changes**: Existing `sa.update()` calls don't need to include `updated_at=sa.func.now()`.
- **No performance concern**: A single `now()` assignment per row per UPDATE is negligible.

### Tables excluded from updated_at

- `eval_audit_logs`: Append-only audit trail — rows are never updated.
- `search_logs_table`: Append-only log — rows are never updated.
- `skill_trackers_table`: Already has `last_checked_at` and `last_published_at` for temporal tracking.

## Files to Create/Modify

| Action | File |
|--------|------|
| Create | `server/migrations/YYYYMMDD_HHMMSS_add_timestamps.sql` |
| Modify | `server/src/decision_hub/infra/database.py` |

## Notes for Re-implementation

1. **Filename collision**: The original branch used `009_add_timestamps.sql` which conflicts with existing `009_add_search_logs.sql`. Use timestamp-based naming.
2. **Use `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`**: For idempotency, since some tables already have `created_at`.
3. **Do not include unrelated changes**: The original branch included ruff formatting fixes in unrelated test files. Keep the PR focused.
4. **`skill_trackers_table`**: Already has `created_at` and temporal columns. Consider whether it also needs `updated_at` — the original PR excluded it, which is reasonable.
