-- Plugin support tables and columns

-- New plugins table
CREATE TABLE IF NOT EXISTS plugins (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    author_name     TEXT,
    homepage        TEXT,
    license         TEXT,
    keywords        TEXT[] NOT NULL DEFAULT '{}',
    platforms       TEXT[] NOT NULL DEFAULT '{}',
    skill_count     INTEGER NOT NULL DEFAULT 0,
    hook_count      INTEGER NOT NULL DEFAULT 0,
    agent_count     INTEGER NOT NULL DEFAULT 0,
    command_count   INTEGER NOT NULL DEFAULT 0,
    category        TEXT NOT NULL DEFAULT '',
    download_count  INTEGER NOT NULL DEFAULT 0,
    visibility      VARCHAR(10) NOT NULL DEFAULT 'public',
    source_repo_url TEXT,
    manifest_path   TEXT,
    source_repo_removed BOOLEAN NOT NULL DEFAULT false,
    github_stars    INTEGER,
    github_forks    INTEGER,
    github_watchers INTEGER,
    github_is_archived BOOLEAN,
    github_license  TEXT,
    search_vector   TSVECTOR,
    embedding       vector(768),
    latest_semver           TEXT,
    latest_eval_status      TEXT,
    latest_gauntlet_summary TEXT,
    latest_published_at     TIMESTAMPTZ,
    latest_published_by     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(org_id, name)
);

ALTER TABLE plugins ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_plugins_search_vector ON plugins USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_plugins_created_at ON plugins(created_at);
CREATE INDEX IF NOT EXISTS idx_plugins_latest_published_at ON plugins(latest_published_at DESC, org_id, name) WHERE latest_semver IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_plugins_category ON plugins(category) WHERE latest_semver IS NOT NULL AND category IS NOT NULL AND category != '';
CREATE INDEX IF NOT EXISTS idx_plugins_visibility ON plugins(visibility) WHERE latest_semver IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_plugins_embedding_hnsw ON plugins
    USING hnsw(embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE TRIGGER set_plugins_updated_at
    BEFORE UPDATE ON plugins
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- New plugin_versions table
CREATE TABLE IF NOT EXISTS plugin_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plugin_id       UUID NOT NULL REFERENCES plugins(id) ON DELETE CASCADE,
    semver          TEXT NOT NULL,
    semver_major    INTEGER NOT NULL DEFAULT 0,
    semver_minor    INTEGER NOT NULL DEFAULT 0,
    semver_patch    INTEGER NOT NULL DEFAULT 0,
    s3_key          TEXT NOT NULL,
    checksum        TEXT NOT NULL,
    plugin_manifest JSONB,
    runtime_config  JSONB,
    published_by    TEXT NOT NULL,
    eval_status     TEXT,
    gauntlet_summary TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(plugin_id, semver)
);

ALTER TABLE plugin_versions ENABLE ROW LEVEL SECURITY;

CREATE TRIGGER set_plugin_versions_updated_at
    BEFORE UPDATE ON plugin_versions
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE INDEX IF NOT EXISTS idx_plugin_versions_semver_parts
    ON plugin_versions(plugin_id, semver_major DESC, semver_minor DESC, semver_patch DESC);

-- Tracker kind column
ALTER TABLE skill_trackers ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'skill';

-- Skill deprecation columns
ALTER TABLE skills ADD COLUMN IF NOT EXISTS deprecated BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE skills ADD COLUMN IF NOT EXISTS deprecated_by_plugin_id UUID REFERENCES plugins(id);
ALTER TABLE skills ADD COLUMN IF NOT EXISTS deprecation_message TEXT;

CREATE INDEX IF NOT EXISTS idx_skills_deprecated ON skills(deprecated) WHERE deprecated = true;

-- Audit log plugin reference
ALTER TABLE eval_audit_logs ADD COLUMN IF NOT EXISTS plugin_id UUID REFERENCES plugins(id);
ALTER TABLE eval_audit_logs ADD COLUMN IF NOT EXISTS plugin_name TEXT;
