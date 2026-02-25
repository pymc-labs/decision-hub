-- All audit/scan data is now served from scan_reports + scan_findings.
-- Backfill script must be run BEFORE deploying this migration.
DROP TABLE IF EXISTS eval_audit_logs;
