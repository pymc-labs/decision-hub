-- Add source_repo_removed flag to skills table.
-- Denormalized boolean (same pattern as latest_semver, latest_eval_status)
-- to avoid JOINing skill_trackers on the hot listing path.
ALTER TABLE skills ADD COLUMN IF NOT EXISTS source_repo_removed BOOLEAN NOT NULL DEFAULT false;
