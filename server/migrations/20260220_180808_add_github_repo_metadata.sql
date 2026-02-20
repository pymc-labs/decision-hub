ALTER TABLE skills
  ADD COLUMN IF NOT EXISTS github_forks       INTEGER,
  ADD COLUMN IF NOT EXISTS github_watchers    INTEGER,
  ADD COLUMN IF NOT EXISTS github_is_archived BOOLEAN,
  ADD COLUMN IF NOT EXISTS github_license     TEXT;
