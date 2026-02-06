-- Eval reports table: stores results from agent eval pipelines
CREATE TABLE IF NOT EXISTS eval_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    agent TEXT NOT NULL,
    judge_model TEXT NOT NULL,
    case_results JSONB NOT NULL DEFAULT '[]'::jsonb,
    passed INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    total_duration_ms INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_eval_reports_version_id ON eval_reports(version_id);
