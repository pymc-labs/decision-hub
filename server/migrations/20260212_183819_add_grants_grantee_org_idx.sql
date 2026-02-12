-- Speed up list_granted_skill_ids() which filters by grantee_org_id.
-- This query runs on every authenticated list/search request.
CREATE INDEX IF NOT EXISTS idx_skill_access_grants_grantee_org
    ON skill_access_grants (grantee_org_id);
