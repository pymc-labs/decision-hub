-- Add LLM model provenance columns to scan_reports for reproducibility.
-- scanner_model: the Gemini model string used for LLM + meta analysis
-- scanner_version: the cisco-ai-skill-scanner package version
-- llm_retries: number of LLM retry attempts before success
-- batch_id: groups reports from the same backfill/crawler/tracker run

ALTER TABLE scan_reports
    ADD COLUMN IF NOT EXISTS scanner_model   TEXT,
    ADD COLUMN IF NOT EXISTS scanner_version TEXT,
    ADD COLUMN IF NOT EXISTS llm_retries     INTEGER,
    ADD COLUMN IF NOT EXISTS batch_id        UUID;
