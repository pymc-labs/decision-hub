-- Add created_at / updated_at timestamps to all tables
-- Tables already with created_at: versions, user_api_keys, eval_audit_logs, eval_reports, eval_runs
-- eval_audit_logs is append-only so it does NOT get updated_at.

-- ---------------------------------------------------------------------------
-- 1. Reusable trigger function for auto-updating updated_at
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ---------------------------------------------------------------------------
-- 2. Add created_at where missing
-- ---------------------------------------------------------------------------
ALTER TABLE users
    ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE organizations
    ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE org_members
    ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE skills
    ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now();


-- ---------------------------------------------------------------------------
-- 3. Add updated_at to all mutable tables
-- ---------------------------------------------------------------------------
ALTER TABLE users
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE organizations
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE org_members
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE skills
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE versions
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE user_api_keys
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE eval_reports
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE eval_runs
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();


-- ---------------------------------------------------------------------------
-- 4. Auto-update triggers
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_org_members_updated_at
    BEFORE UPDATE ON org_members
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_skills_updated_at
    BEFORE UPDATE ON skills
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_versions_updated_at
    BEFORE UPDATE ON versions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_user_api_keys_updated_at
    BEFORE UPDATE ON user_api_keys
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_eval_reports_updated_at
    BEFORE UPDATE ON eval_reports
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_eval_runs_updated_at
    BEFORE UPDATE ON eval_runs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ---------------------------------------------------------------------------
-- 5. Indexes for time-based queries
-- ---------------------------------------------------------------------------
CREATE INDEX idx_skills_created_at ON skills (created_at);
CREATE INDEX idx_versions_updated_at ON versions (updated_at);
CREATE INDEX idx_eval_reports_updated_at ON eval_reports (updated_at);
CREATE INDEX idx_eval_runs_updated_at ON eval_runs (updated_at);
