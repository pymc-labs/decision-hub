-- Fix migration gap: eval_runs table and organizations.is_personal column were
-- created by metadata.create_all() but never had migration files.
-- Uses IF NOT EXISTS / IF NOT EXISTS so this is safe on existing DBs.

-- 1. Add is_personal column to organizations (may already exist)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'organizations' AND column_name = 'is_personal'
    ) THEN
        ALTER TABLE organizations ADD COLUMN is_personal BOOLEAN NOT NULL DEFAULT false;
    END IF;
END
$$;

-- 2. Create eval_runs table (may already exist)
CREATE TABLE IF NOT EXISTS eval_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id    UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES users(id),
    agent         VARCHAR NOT NULL,
    judge_model   VARCHAR NOT NULL,
    status        VARCHAR NOT NULL DEFAULT 'pending',
    stage         VARCHAR,
    current_case  VARCHAR,
    current_case_index INTEGER,
    total_cases   INTEGER NOT NULL,
    heartbeat_at  TIMESTAMPTZ,
    log_s3_prefix TEXT NOT NULL,
    log_seq       INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ
);

-- 3. Enable RLS on eval_runs (was removed from 010 since the table didn't exist yet)
ALTER TABLE eval_runs ENABLE ROW LEVEL SECURITY;
