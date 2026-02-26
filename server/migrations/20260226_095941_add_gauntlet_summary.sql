-- Add gauntlet_summary to skill_versions and denormalized latest_gauntlet_summary to skills.
-- Stores a brief human-readable summary of non-pass gauntlet findings so the
-- ask LLM can explain *why* a skill received a particular safety grade.

ALTER TABLE skill_versions
    ADD COLUMN IF NOT EXISTS gauntlet_summary TEXT;

ALTER TABLE skills
    ADD COLUMN IF NOT EXISTS latest_gauntlet_summary TEXT;
