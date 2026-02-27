-- Add manifest_path column to skills table.
-- Stores the relative path to SKILL.md within the source repo
-- (e.g. "SKILL.md" for root-level skills, "skills/my-skill/SKILL.md" for nested ones).
-- Used to construct direct GitHub links to the skill manifest.

ALTER TABLE skills ADD COLUMN IF NOT EXISTS manifest_path TEXT;
