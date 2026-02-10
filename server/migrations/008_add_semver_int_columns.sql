-- Add integer semver columns for indexed ordering (replaces split_part casts).
-- Backfill from existing semver text, then create a composite index.

ALTER TABLE versions
    ADD COLUMN semver_major INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN semver_minor INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN semver_patch INTEGER NOT NULL DEFAULT 0;

-- Backfill existing rows from the semver text column
UPDATE versions SET
    semver_major = CAST(split_part(semver, '.', 1) AS INTEGER),
    semver_minor = CAST(split_part(semver, '.', 2) AS INTEGER),
    semver_patch = CAST(split_part(semver, '.', 3) AS INTEGER);

-- Composite index for "find latest version per skill" queries
CREATE INDEX idx_versions_skill_semver_parts
    ON versions (skill_id, semver_major DESC, semver_minor DESC, semver_patch DESC);
