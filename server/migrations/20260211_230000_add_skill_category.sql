-- Add category column to skills table for LLM-based skill classification.
ALTER TABLE skills ADD COLUMN IF NOT EXISTS category VARCHAR NOT NULL DEFAULT '';
