-- Add GitHub metadata columns to organizations for display on org profile pages.
-- Synced periodically from the GitHub API.
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS avatar_url TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS blog TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS github_synced_at TIMESTAMPTZ;
