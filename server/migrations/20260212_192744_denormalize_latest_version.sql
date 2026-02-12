-- Denormalize latest version metadata onto the skills table.
-- Eliminates costly LATERAL subqueries from listing/search/stats queries.

-- Add columns (nullable = no version published yet)
ALTER TABLE skills ADD COLUMN IF NOT EXISTS latest_semver TEXT;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS latest_eval_status TEXT;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS latest_published_at TIMESTAMPTZ;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS latest_published_by TEXT;

-- Backfill from versions (DISTINCT ON picks highest semver per skill)
UPDATE skills s SET
    latest_semver = v.semver,
    latest_eval_status = v.eval_status,
    latest_published_at = v.created_at,
    latest_published_by = v.published_by
FROM (
    SELECT DISTINCT ON (skill_id) skill_id, semver, eval_status, created_at, published_by
    FROM versions
    ORDER BY skill_id, semver_major DESC, semver_minor DESC, semver_patch DESC
) v WHERE s.id = v.skill_id;

-- Index for default sort (partial: only published skills)
CREATE INDEX IF NOT EXISTS idx_skills_latest_published_at
    ON skills (latest_published_at DESC, org_id, name)
    WHERE latest_semver IS NOT NULL;

-- Index for grade filtering
CREATE INDEX IF NOT EXISTS idx_skills_latest_eval_status
    ON skills (latest_eval_status)
    WHERE latest_semver IS NOT NULL;
