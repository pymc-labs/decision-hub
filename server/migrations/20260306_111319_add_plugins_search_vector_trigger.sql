-- Add search_vector trigger for plugins table (mirrors skills pattern)

CREATE OR REPLACE FUNCTION plugins_search_vector_update()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE org_slug TEXT;
BEGIN
    SELECT slug INTO org_slug FROM organizations WHERE id = NEW.org_id;
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(org_slug, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.category, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'C');
    RETURN NEW;
END;
$$;

DO $$ BEGIN
    CREATE TRIGGER trg_plugins_search_vector
        BEFORE INSERT OR UPDATE OF name, description, category, org_id
        ON plugins FOR EACH ROW
        EXECUTE FUNCTION plugins_search_vector_update();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Backfill existing rows
ALTER TABLE plugins DISABLE TRIGGER set_plugins_updated_at;
UPDATE plugins SET name = name WHERE search_vector IS NULL;
ALTER TABLE plugins ENABLE TRIGGER set_plugins_updated_at;
