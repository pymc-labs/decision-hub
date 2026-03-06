-- Add consecutive_permanent_failures counter to skill_trackers.
-- Prevents a single transient GraphQL failure from permanently disabling
-- trackers and marking all their skills as removed.
ALTER TABLE skill_trackers
    ADD COLUMN IF NOT EXISTS consecutive_permanent_failures INTEGER NOT NULL DEFAULT 0;
