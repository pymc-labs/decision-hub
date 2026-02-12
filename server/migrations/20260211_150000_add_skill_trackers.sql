CREATE TABLE IF NOT EXISTS skill_trackers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    org_slug        TEXT NOT NULL,
    repo_url        TEXT NOT NULL,
    branch          VARCHAR NOT NULL DEFAULT 'main',
    last_commit_sha VARCHAR,
    poll_interval_minutes INTEGER NOT NULL DEFAULT 60,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    last_checked_at TIMESTAMPTZ,
    last_published_at TIMESTAMPTZ,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, repo_url, branch)
);
