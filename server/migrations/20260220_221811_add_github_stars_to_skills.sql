-- Add github_stars column to skills table for tracking source repo star counts.
-- Updated by the tracker on each check cycle via batch GraphQL.
ALTER TABLE skills ADD COLUMN IF NOT EXISTS github_stars INTEGER;
