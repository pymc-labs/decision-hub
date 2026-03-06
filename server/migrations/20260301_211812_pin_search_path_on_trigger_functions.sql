-- Pin search_path on all trigger functions to prevent search-path hijacking.
-- Fixes Supabase security advisor warning: "Function has a role mutable search_path".
-- Tables referenced inside the functions are qualified with public. schema prefix.

-- 1. set_updated_at — only uses now() from pg_catalog
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

-- 2. skills_search_vector_update — references organizations table
CREATE OR REPLACE FUNCTION skills_search_vector_update()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE org_slug TEXT;
BEGIN
    SELECT slug INTO org_slug FROM public.organizations WHERE id = NEW.org_id;
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(org_slug, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.category, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'C');
    RETURN NEW;
END;
$$;

-- 3. cleanup_orphaned_tracker — references organizations, skills, skill_trackers
CREATE OR REPLACE FUNCTION cleanup_orphaned_tracker()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    v_org_slug TEXT;
BEGIN
    IF OLD.source_repo_url IS NOT NULL THEN
        SELECT slug INTO v_org_slug FROM public.organizations WHERE id = OLD.org_id;

        IF NOT EXISTS (
            SELECT 1 FROM public.skills
            WHERE source_repo_url = OLD.source_repo_url
              AND org_id = OLD.org_id
        ) THEN
            DELETE FROM public.skill_trackers
            WHERE repo_url = OLD.source_repo_url
              AND org_slug = v_org_slug;
        END IF;
    END IF;
    RETURN OLD;
END;
$$;
