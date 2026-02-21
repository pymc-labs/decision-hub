-- When the last skill sourced from a given repo is deleted, automatically
-- remove the tracker for that repo. A tracker is "orphaned" when no skill
-- in the skills table still references its repo_url via source_repo_url.
--
-- This fires AFTER DELETE on skills so that the deleted row is no longer
-- visible when we check for remaining skills from the same repo.

CREATE OR REPLACE FUNCTION cleanup_orphaned_tracker()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.source_repo_url IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM skills WHERE source_repo_url = OLD.source_repo_url
        ) THEN
            DELETE FROM skill_trackers WHERE repo_url = OLD.source_repo_url;
        END IF;
    END IF;
    RETURN OLD;
END;
$$;

CREATE TRIGGER trg_cleanup_orphaned_tracker
AFTER DELETE ON skills
FOR EACH ROW
EXECUTE FUNCTION cleanup_orphaned_tracker();
