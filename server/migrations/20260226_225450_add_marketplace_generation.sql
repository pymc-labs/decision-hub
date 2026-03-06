-- Lightweight key-value config table for server-internal counters.
CREATE TABLE IF NOT EXISTS server_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '0',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE server_config ENABLE ROW LEVEL SECURITY;

-- Seed the marketplace generation counter.
INSERT INTO server_config (key, value)
VALUES ('marketplace_generation', '0')
ON CONFLICT (key) DO NOTHING;
