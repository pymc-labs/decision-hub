-- Drop the unused org_invites table (feature was removed).
DROP TABLE IF EXISTS org_invites;

-- Enable Row Level Security on all public tables.
--
-- The backend connects as the table owner via SQLAlchemy (direct DATABASE_URL),
-- which bypasses RLS by default. Enabling RLS with no policies blocks
-- Supabase PostgREST access (anon/authenticated roles) from querying tables
-- directly, ensuring all data access goes through the FastAPI API layer.

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval_audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE search_logs ENABLE ROW LEVEL SECURITY;
