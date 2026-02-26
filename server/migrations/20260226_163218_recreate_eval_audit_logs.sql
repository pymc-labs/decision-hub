-- Recreate eval_audit_logs table (was manually dropped on dev)
CREATE TABLE IF NOT EXISTS eval_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_slug TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    semver TEXT NOT NULL,
    grade VARCHAR(1) NOT NULL,
    version_id UUID REFERENCES versions(id) ON DELETE SET NULL,
    check_results JSONB NOT NULL,
    llm_reasoning JSONB,
    publisher TEXT NOT NULL DEFAULT '',
    quarantine_s3_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_skill ON eval_audit_logs (org_slug, skill_name);
CREATE INDEX IF NOT EXISTS idx_audit_logs_version ON eval_audit_logs (version_id);

ALTER TABLE eval_audit_logs ENABLE ROW LEVEL SECURITY;
