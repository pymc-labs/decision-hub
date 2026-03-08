-- Add trackers_disabled column to tracker_metrics for observability.
-- Tracks how many trackers were permanently disabled in each cron tick.
ALTER TABLE tracker_metrics ADD COLUMN IF NOT EXISTS trackers_disabled INTEGER NOT NULL DEFAULT 0;
