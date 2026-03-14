-- Cisco skill-scanner integration: scan_reports + scan_findings tables.
-- Stores scanner results alongside the gauntlet's eval_audit_logs.
--
-- Detects and drops leftover tables from the old PR #191 branch (which had
-- a different schema with a "grade" column). Leaves our own tables intact
-- if they already exist (idempotent via IF NOT EXISTS).

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'scan_reports'
          AND column_name = 'grade'
    ) THEN
        RAISE NOTICE 'Detected old PR #191 scan_reports schema — dropping';
        DROP TABLE IF EXISTS scan_findings;
        DROP TABLE IF EXISTS scan_reports;
    END IF;
END
$$;

-- One row per scan execution (one per publish or backfill run)
CREATE TABLE IF NOT EXISTS scan_reports (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id              UUID REFERENCES versions(id) ON DELETE CASCADE,
    org_slug                TEXT NOT NULL,
    skill_name              TEXT NOT NULL,
    semver                  TEXT NOT NULL,

    -- ScanResult mechanical rollup
    is_safe                 BOOLEAN NOT NULL,
    max_severity            TEXT NOT NULL,
    findings_count          INTEGER NOT NULL DEFAULT 0,

    -- Analyzer metadata
    analyzers_used          TEXT[] NOT NULL DEFAULT '{}',
    analyzers_failed        JSONB DEFAULT '[]',

    -- Analyzability
    analyzability_score     DOUBLE PRECISION,
    analyzability_details   JSONB,

    -- Meta-analysis verdict (NULL when meta didn't run)
    meta_verdict            TEXT,
    meta_risk_level         TEXT,
    meta_summary            TEXT,
    meta_top_priority       TEXT,

    -- Meta-analysis structured data
    meta_correlations       JSONB,
    meta_recommendations    JSONB,
    meta_false_positive_count INTEGER,

    -- Scan configuration
    scanner_version         TEXT,
    scanner_model           TEXT,
    policy_name             TEXT,
    scan_duration_ms        INTEGER,

    -- Full blobs for deep inspection
    full_report             JSONB,
    meta_analysis           JSONB,
    scan_metadata           JSONB,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scan_reports_version ON scan_reports(version_id);
CREATE INDEX IF NOT EXISTS idx_scan_reports_skill ON scan_reports(org_slug, skill_name);

ALTER TABLE scan_reports ENABLE ROW LEVEL SECURITY;

DROP TRIGGER IF EXISTS set_scan_reports_updated_at ON scan_reports;
CREATE TRIGGER set_scan_reports_updated_at
    BEFORE UPDATE ON scan_reports
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Denormalized findings for querying and display
CREATE TABLE IF NOT EXISTS scan_findings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id           UUID NOT NULL REFERENCES scan_reports(id) ON DELETE CASCADE,

    rule_id             TEXT NOT NULL,
    category            TEXT NOT NULL,
    severity            TEXT NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT,
    file_path           TEXT,
    line_number         INTEGER,
    snippet             TEXT,
    remediation         TEXT,
    analyzer            TEXT,

    -- Meta-analysis enrichment
    is_false_positive   BOOLEAN,
    meta_confidence     TEXT,
    meta_priority       INTEGER,

    -- Full metadata blob (aitech_code, policy fingerprint, etc.)
    metadata            JSONB NOT NULL DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scan_findings_report ON scan_findings(report_id);
CREATE INDEX IF NOT EXISTS idx_scan_findings_severity ON scan_findings(severity);

ALTER TABLE scan_findings ENABLE ROW LEVEL SECURITY;
