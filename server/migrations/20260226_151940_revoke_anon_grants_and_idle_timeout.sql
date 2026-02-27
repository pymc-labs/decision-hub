-- Revoke all privileges from anon and authenticated roles on public schema.
-- All data access goes through the FastAPI backend (which connects as the table
-- owner and bypasses RLS), so these roles should have zero access.  Previously,
-- Supabase default grants gave them full CRUD + TRUNCATE + TRIGGER on every
-- table, meaning a single accidental RLS disable would expose all data via the
-- public anon API key.
--
-- Guarded with DO blocks so local Postgres (which lacks Supabase roles) doesn't fail.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;
    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon;
    REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon;
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM authenticated;
    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM authenticated;
    REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM authenticated;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM authenticated;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM authenticated;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM authenticated;
  END IF;
END $$;

-- Set idle_in_transaction_session_timeout to 120 seconds (2 minutes).
-- Prevents forgotten transactions from holding locks indefinitely.
-- Use current_database() so it works regardless of DB name (postgres vs decision_hub).
DO $$ BEGIN
  EXECUTE format('ALTER DATABASE %I SET idle_in_transaction_session_timeout = ''120s''', current_database());
END $$;
