-- Tracker cron metrics: one row per check_trackers invocation.
-- Records key counters for observability and health monitoring.

CREATE TABLE IF NOT EXISTS tracker_metrics (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recorded_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    iterations             INTEGER NOT NULL,
    total_checked          INTEGER NOT NULL,
    trackers_due           INTEGER NOT NULL DEFAULT 0,
    trackers_unchanged     INTEGER NOT NULL DEFAULT 0,
    trackers_changed       INTEGER NOT NULL DEFAULT 0,
    trackers_errored       INTEGER NOT NULL DEFAULT 0,
    trackers_processed     INTEGER NOT NULL DEFAULT 0,
    trackers_failed        INTEGER NOT NULL DEFAULT 0,
    skipped_rate_limit     INTEGER NOT NULL DEFAULT 0,
    github_rate_remaining  INTEGER,
    batch_duration_seconds REAL NOT NULL
);

ALTER TABLE tracker_metrics ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS ix_tracker_metrics_recorded_at
    ON tracker_metrics (recorded_at DESC);
