-- Index to speed up claim_due_trackers() which filters on
-- enabled = true and orders/filters by last_checked_at.
-- Partial index keeps the index small by excluding disabled trackers.
CREATE INDEX IF NOT EXISTS ix_skill_trackers_due
    ON skill_trackers (last_checked_at NULLS FIRST)
    WHERE enabled = true;
