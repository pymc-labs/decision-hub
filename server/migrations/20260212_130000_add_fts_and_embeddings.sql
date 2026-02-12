-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. Add tsvector column for full-text search
ALTER TABLE skills ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- 2. Add embedding column (768-dim via Gemini outputDimensionality)
ALTER TABLE skills ADD COLUMN IF NOT EXISTS embedding vector(768);

-- 3. FTS trigger function (weighted: name > org/category > description)
CREATE OR REPLACE FUNCTION skills_search_vector_update() RETURNS TRIGGER AS $$
DECLARE org_slug TEXT;
BEGIN
    SELECT slug INTO org_slug FROM organizations WHERE id = NEW.org_id;
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(org_slug, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.category, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'C');
    RETURN NEW;
END; $$ LANGUAGE plpgsql;

-- 4. FTS trigger
DO $$ BEGIN
    CREATE TRIGGER trg_skills_search_vector
        BEFORE INSERT OR UPDATE OF name, description, category, org_id
        ON skills FOR EACH ROW
        EXECUTE FUNCTION skills_search_vector_update();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 5. GIN index for FTS
CREATE INDEX IF NOT EXISTS idx_skills_search_vector ON skills USING GIN (search_vector);

-- 6. HNSW index for embedding similarity (cosine distance)
CREATE INDEX IF NOT EXISTS idx_skills_embedding_hnsw
    ON skills USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 7. Backfill tsvector (trigger fires on UPDATE, no API calls needed)
UPDATE skills SET name = name WHERE search_vector IS NULL;

-- Embedding backfill requires Gemini API calls — see backfill_embeddings.py script
