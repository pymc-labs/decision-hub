-- Add GitHub-sourced metadata columns to organizations.
-- Synced from the GitHub API during OAuth login (best-effort).

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS avatar_url TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS blog TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS github_synced_at TIMESTAMPTZ;
