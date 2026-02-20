-- Add next_check_at column to skill_trackers for index-based due scheduling.
-- Replaces the old ix_skill_trackers_due index with a more efficient one
-- that can be scanned directly by next_check_at.

ALTER TABLE skill_trackers ADD COLUMN IF NOT EXISTS next_check_at TIMESTAMPTZ;

-- Backfill: never-checked trackers get epoch (immediately due);
-- already-checked ones get last_checked_at + poll_interval.
UPDATE skill_trackers SET next_check_at = CASE
    WHEN last_checked_at IS NULL THEN '1970-01-01T00:00:00Z'::timestamptz
    ELSE last_checked_at + (poll_interval_minutes * INTERVAL '1 minute')
END
WHERE next_check_at IS NULL;

-- Drop the old index and create the new one.
DROP INDEX IF EXISTS ix_skill_trackers_due;
CREATE INDEX IF NOT EXISTS ix_skill_trackers_next_check
    ON skill_trackers (next_check_at ASC NULLS FIRST) WHERE enabled = true;
