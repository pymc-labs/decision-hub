-- Fix cleanup_orphaned_tracker to scope deletion to the org of the deleted skill.
--
-- The original trigger deleted from skill_trackers by repo_url alone. If two
-- different orgs both track the same repo, deleting one org's last skill would
-- also remove the other org's tracker. The corrected function only deletes the
-- tracker when no other skill in the *same org* still references the repo.

CREATE OR REPLACE FUNCTION cleanup_orphaned_tracker()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_org_slug TEXT;
BEGIN
    IF OLD.source_repo_url IS NOT NULL THEN
        SELECT slug INTO v_org_slug FROM organizations WHERE id = OLD.org_id;

        IF NOT EXISTS (
            SELECT 1 FROM skills
            WHERE source_repo_url = OLD.source_repo_url
              AND org_id = OLD.org_id
        ) THEN
            DELETE FROM skill_trackers
            WHERE repo_url = OLD.source_repo_url
              AND org_slug = v_org_slug;
        END IF;
    END IF;
    RETURN OLD;
END;
$$;
