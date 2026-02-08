-- Fix schema drift between SQLAlchemy metadata and migrations.
-- eval_reports.version_id should be unique (one report per version).
-- Uses IF NOT EXISTS so this is safe to re-run.
CREATE UNIQUE INDEX IF NOT EXISTS eval_reports_version_id_key ON eval_reports(version_id);
