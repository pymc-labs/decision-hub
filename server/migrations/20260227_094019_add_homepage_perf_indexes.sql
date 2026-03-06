-- Partial indexes to speed up homepage queries (stats, skill listing).

CREATE INDEX IF NOT EXISTS idx_skills_visibility
  ON skills (visibility)
  WHERE latest_semver IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_skills_category
  ON skills (category)
  WHERE latest_semver IS NOT NULL AND category IS NOT NULL AND category != '';
