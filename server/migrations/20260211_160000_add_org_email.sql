-- Add optional email column to organizations for public contact info.
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS email TEXT;
