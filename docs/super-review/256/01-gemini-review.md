# PR #256 Code Review: feat: first-class agent plugin support (Gemini)

This PR introduces a substantial new feature set by adding a parallel "plugins" ecosystem alongside the existing "skills" architecture. Overall, the implementation correctly mirrors the existing patterns, implements strong validation for zip extraction, and handles the crawler/tracker logic well.

However, there are several correctness bugs and one privacy issue regarding data visibility and state management.

### 1. Privacy Leak: `list_all_org_profiles` exposes orgs with private plugins (High)
**Location:** `server/src/decision_hub/infra/database.py` (lines 989-990)
**Issue:** The query building `plugin_org_ids` does not filter by plugin visibility. If an organization exclusively publishes `visibility="org"` (private) plugins and has no public skills, it will still be exposed to unauthenticated users in the public `/v1/orgs` endpoint.
**Fix:** Add the visibility filter to the plugin subquery:
```python
    plugin_org_ids = (
        sa.select(plugins_table.c.org_id)
        .where(
            sa.and_(
                plugins_table.c.visibility == "public",
                plugins_table.c.latest_semver.isnot(None),
            )
        )
        .distinct()
    )
```

### 2. Data Mixing Bug: Search `candidate_map` overwrites sharing names (Medium)
**Location:** `server/src/decision_hub/api/search_routes.py` (line 397)
**Issue:** The `candidate_map` is keyed by `(org_slug, name)`. Because `plugins` and `skills` are stored in separate tables with independent uniqueness constraints, an org can publish a skill and a plugin with the exact same name. In hybrid search, the plugin will overwrite the skill in the dictionary. When assembling the final `AskResponse`, the API will apply the plugin's description, safety rating, and download count to the skill's LLM reference.
**Fix:** Include `kind` in the map's key:
```python
    candidate_map: dict[tuple[str, str, str], dict] = {
        (
            row["org_slug"],
            row.get("skill_name") or row.get("plugin_name", ""),
            row.get("kind", "skill")
        ): row
        for row in result.candidates
    }
```
And retrieve it via `candidate_map.get((e.org_slug, e.skill_name, e.kind), {})` later in the function.

### 3. State Bug: Permanently failed trackers do not mark plugins as removed (Medium)
**Location:** `server/src/decision_hub/domain/tracker_service.py` (lines 201-202)
**Issue:** When a tracker crosses the `consecutive_permanent_failures` threshold, the system auto-disables the tracker and calls `mark_skills_source_removed(conn, removed_urls)`. However, there is no corresponding call to mark **plugins** as removed. If a plugin's source repository is deleted from GitHub, its tracker will eventually die, but the plugin will incorrectly remain marked as `source_repo_removed = False`.
**Fix:** Create a `mark_plugins_source_removed` function in `database.py` (mirroring the skill version) and invoke it right after `mark_skills_source_removed`.

### 4. Logic Gap: Plugin summary columns missing GitHub status fields (Low)
**Location:** `server/src/decision_hub/infra/database.py` (lines 758-778)
**Issue:** The `_PLUGIN_SUMMARY_COLUMNS` array omits `plugins_table.c.source_repo_removed` and `plugins_table.c.github_is_archived`. Because `search_plugins_hybrid` uses this array, these fields are never fetched. In `search_routes.py`'s `_run_retrieval`, `row.get("source_repo_removed", False)` will silently default to `False`, bypassing the LLM prompt instructions designed to demote removed/archived sources.
**Fix:** Add the missing columns to `_PLUGIN_SUMMARY_COLUMNS`.
```python
    plugins_table.c.source_repo_removed,
    plugins_table.c.github_is_archived,
```

### 5. Atomicity & State Inconsistency: S3 upload failure drops deprecation (Low)
**Location:** `server/src/decision_hub/domain/plugin_publish_pipeline.py` (lines 352-371)
**Issue:** You noted in the comments that the DB commit occurs before the S3 upload. However, because `deprecate_skills_by_repo_url()` happens *after* the `upload_skill_zip` call, an S3 upload failure (which raises an exception) will prevent the older skills from being deprecated. The database will permanently store the plugin version, but the targeted skills will remain active and un-deprecated.
**Fix:** Either move the `deprecate_skills_by_repo_url()` logic above the `conn.commit()` block so it becomes part of the DB metadata transaction, or catch the S3 exception to run cleanup on the ghost record.
