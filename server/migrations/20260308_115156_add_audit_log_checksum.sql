-- Add content checksum to audit logs for quarantine dedup.
-- Trackers use this to skip re-running the gauntlet on identical content
-- that was already rejected within a configurable TTL window.

ALTER TABLE eval_audit_logs
  ADD COLUMN IF NOT EXISTS checksum TEXT;

-- Index for the quarantine dedup query:
-- WHERE org_slug = ? AND skill_name = ? AND checksum = ? AND grade = 'F'
--   AND created_at > now() - interval '...'
CREATE INDEX IF NOT EXISTS idx_eval_audit_logs_quarantine_dedup
  ON eval_audit_logs (org_slug, skill_name, checksum, grade)
  WHERE grade = 'F' AND checksum IS NOT NULL;
