-- Revoke all privileges from anon and authenticated roles on public schema.
-- All data access goes through the FastAPI backend (which connects as the table
-- owner and bypasses RLS), so these roles should have zero access.  Previously,
-- Supabase default grants gave them full CRUD + TRUNCATE + TRIGGER on every
-- table, meaning a single accidental RLS disable would expose all data via the
-- public anon API key.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;

-- Also revoke default privileges so future tables/functions don't inherit grants.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;

-- Set idle_in_transaction_session_timeout to 120 seconds (2 minutes).
-- Prevents forgotten transactions from holding locks indefinitely.
ALTER DATABASE postgres SET idle_in_transaction_session_timeout = '120s';
