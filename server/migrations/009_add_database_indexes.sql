-- Add missing indexes for common query patterns.

-- eval_runs: filter by version_id, order by created_at (used by
-- find_eval_run_for_version, list_eval_runs_for_version)
CREATE INDEX IF NOT EXISTS idx_eval_runs_version_created
    ON eval_runs (version_id, created_at);

-- eval_runs: filter by user_id, order by created_at (used by
-- find_recent_eval_runs_for_user)
CREATE INDEX IF NOT EXISTS idx_eval_runs_user_created
    ON eval_runs (user_id, created_at);

-- versions: partial index on eval_status for the common
-- IN ('A', 'B', 'passed') filter (used by resolve_version)
CREATE INDEX IF NOT EXISTS idx_versions_eval_status_partial
    ON versions (eval_status)
    WHERE eval_status IN ('A', 'B', 'passed');
