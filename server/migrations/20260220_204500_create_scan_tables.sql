-- Scan reports and findings tables for skill-scanner integration.
-- Replaces the sparse check_results/llm_reasoning JSONB in eval_audit_logs
-- with structured, queryable per-finding data.

-- Top-level scan result, one per publish/crawl/tracker scan attempt
CREATE TABLE IF NOT EXISTS scan_reports (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id          UUID REFERENCES versions(id) ON DELETE SET NULL,
    org_slug            TEXT NOT NULL,
    skill_name          TEXT NOT NULL,
    semver              TEXT NOT NULL,
    is_safe             BOOLEAN NOT NULL,
    max_severity        TEXT NOT NULL,
    grade               CHAR(1) NOT NULL,
    findings_count      INTEGER NOT NULL DEFAULT 0,
    analyzers_used      TEXT[] NOT NULL DEFAULT '{}',
    analyzability_score REAL,
    scan_duration_ms    INTEGER,
    policy_name         TEXT,
    policy_fingerprint  TEXT,
    full_report         JSONB,
    meta_analysis       JSONB,
    publisher           TEXT NOT NULL DEFAULT '',
    quarantine_s3_key   TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Individual findings, normalized for querying/aggregation
CREATE TABLE IF NOT EXISTS scan_findings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id       UUID NOT NULL REFERENCES scan_reports(id) ON DELETE CASCADE,
    rule_id         TEXT NOT NULL,
    category        TEXT NOT NULL,
    severity        TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    file_path       TEXT,
    line_number     INTEGER,
    snippet         TEXT,
    remediation     TEXT,
    analyzer        TEXT,
    aitech_code     TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_scan_reports_version ON scan_reports(version_id);
CREATE INDEX IF NOT EXISTS idx_scan_reports_org_skill ON scan_reports(org_slug, skill_name);
CREATE INDEX IF NOT EXISTS idx_scan_reports_grade ON scan_reports(grade);
CREATE INDEX IF NOT EXISTS idx_scan_findings_report ON scan_findings(report_id);
CREATE INDEX IF NOT EXISTS idx_scan_findings_severity ON scan_findings(severity);
CREATE INDEX IF NOT EXISTS idx_scan_findings_category ON scan_findings(category);
CREATE INDEX IF NOT EXISTS idx_scan_findings_rule ON scan_findings(rule_id);

ALTER TABLE scan_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE scan_findings ENABLE ROW LEVEL SECURITY;

CREATE TRIGGER set_scan_reports_updated_at
    BEFORE UPDATE ON scan_reports
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
