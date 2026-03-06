-- Add plugin_version_id FK to eval_audit_logs so plugin publishes
-- don't incorrectly reference the skill versions table.
ALTER TABLE eval_audit_logs
    ADD COLUMN IF NOT EXISTS plugin_version_id UUID
        REFERENCES plugin_versions(id) ON DELETE SET NULL;
