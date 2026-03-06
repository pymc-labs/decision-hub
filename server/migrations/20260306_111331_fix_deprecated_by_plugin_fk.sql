-- Fix deprecated_by_plugin_id FK to use ON DELETE SET NULL
ALTER TABLE skills DROP CONSTRAINT IF EXISTS skills_deprecated_by_plugin_id_fkey;
ALTER TABLE skills ADD CONSTRAINT skills_deprecated_by_plugin_id_fkey
    FOREIGN KEY (deprecated_by_plugin_id) REFERENCES plugins(id) ON DELETE SET NULL;
