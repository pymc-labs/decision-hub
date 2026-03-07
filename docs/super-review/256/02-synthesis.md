# Unified Code Review Report -- PR #256: First-Class Agent Plugin Support

## Summary

| Severity | Count |
|----------|-------|
| Critical | 2     |
| High     | 4     |
| Medium   | 8     |
| Low      | 5     |
| **Total** | **19** |

**Key themes:**

1. **Server-side `create_zip` strips `.claude-plugin/` directories**, breaking all tracker and crawler plugin publishes (Critical -- flagged by all three reviewers)
2. **Missing `search_vector` trigger** for the `plugins` table means full-text search silently returns zero results (Critical -- flagged by all three reviewers)
3. **Cross-tenant data mutation** in plugin-driven skill deprecation and **privacy leaks** in the org listing endpoint (High)
4. **Multiple pagination/query correctness issues** -- missing `NULLS LAST`, no unique tiebreaker, unbounded version listing
5. **DRY violations** in visibility enforcement code, repeated across four endpoints

**Overall assessment:** The feature introduces a substantial, well-structured plugin system, but has two showstopper bugs that will prevent plugin publishing and discovery from working via tracker/crawler paths. The cross-org deprecation bug is a security concern. These must be fixed before merge. The medium/low findings are real quality issues but can be addressed in a fast-follow.

---

## Findings by File

### `server/migrations/20260305_223006_add_plugin_tables.sql`

#### CRITICAL -- Missing `search_vector` trigger for `plugins` table

- **Line:** after line 54 (missing)
- **Reviewers:** Codex (P1), Claude (C1), Gemini (implicit via search filtering at line 3742)
- **Description:** The migration creates the `search_vector TSVECTOR` column and a GIN index on it, but never creates a trigger function to populate it (unlike the skills table, which has `skills_search_vector_update()` from migration `20260212_130000`). The column will always be `NULL`. Any search query in `fetch_paginated_plugins` that applies the `@@` operator (line 3742 of `database.py`) will filter out all plugins. Full-text search for plugins is completely broken.

#### MEDIUM -- `deprecated_by_plugin_id` FK lacks `ON DELETE SET NULL`

- **Line:** 90
- **Reviewer:** Claude (M7)
- **Description:** `ALTER TABLE skills ADD COLUMN IF NOT EXISTS deprecated_by_plugin_id UUID REFERENCES plugins(id);` has no `ON DELETE` clause. If a plugin is ever deleted, the FK will prevent deletion or leave dangling references depending on the default behavior (`NO ACTION`). Should be `ON DELETE SET NULL` to match the semantics (the skill remains deprecated, but the link to the deleted plugin is cleared).

---

### `server/src/decision_hub/domain/repo_utils.py`

#### CRITICAL -- `create_zip` strips `.claude-plugin/` directories, breaking tracker and crawler publishes

- **Lines:** 94-108
- **Reviewers:** Codex (P1), Claude (C2)
- **Description:** The server-side `create_zip()` unconditionally skips all path components starting with `.` (line 106: `any(part.startswith(".") ...)`). Plugin manifests live under `.claude-plugin/`, so the archive will be missing `plugin.json` and related files. `parse_plugin_manifest()` will fail when processing the extracted zip. This affects both `_publish_plugin_from_tracker` (tracker_service.py:826) and `_process_plugin_from_repo` (crawler/processing.py:577). Note: the client-side `_create_zip` in `client/src/dhub/cli/registry.py` already handles this correctly with a `preserve_dot_dirs` parameter (line 654), but the server-side equivalent was not updated.

---

### `server/src/decision_hub/infra/database.py`

#### HIGH -- `deprecate_skills_by_repo_url` is not scoped to publishing org (cross-tenant mutation)

- **Lines:** 3669-3675
- **Reviewers:** Codex (P1), Gemini (implied in atomicity concern)
- **Description:** The `WHERE` clause filters only on `source_repo_url` and `deprecated == False`, with no `org_id` constraint. If multiple organizations publish skills from the same repository (e.g., a popular open-source repo), publishing a plugin in one org will deprecate another org's skills. This is a cross-tenant data mutation. The function signature should accept `org_id` and add it to the filter.

#### HIGH -- `list_all_org_profiles` exposes orgs with only private plugins

- **Lines:** 985-986
- **Reviewers:** Gemini (High), Codex (P2)
- **Description:** The `plugin_org_ids` subquery includes all orgs with a published plugin (`latest_semver IS NOT NULL`) but does not filter by `visibility = 'public'`. An org that exclusively publishes `visibility="org"` plugins will appear in the public `/v1/orgs` endpoint, leaking its existence. The skills subquery correctly filters on visibility (line 980).

#### MEDIUM -- `deprecated_by_plugin_id` column missing `ForeignKey` declaration in SQLAlchemy model

- **Line:** 171
- **Reviewer:** Claude (M2)
- **Description:** The SQLAlchemy column definition is `Column("deprecated_by_plugin_id", PG_UUID(as_uuid=True), nullable=True)` with no `ForeignKey(...)`, while the SQL migration has `REFERENCES plugins(id)`. CI schema-drift check will flag this mismatch.

#### MEDIUM -- `_PLUGIN_SUMMARY_COLUMNS` omits `source_repo_removed` and `github_is_archived`

- **Lines:** 761-781
- **Reviewer:** Gemini (Low -- but functionally relevant)
- **Description:** These fields exist on the `plugins` table but are never fetched in plugin list/search queries. They will silently default to `False` in any code that checks them, giving incorrect data for archived or removed repos.

#### MEDIUM -- `fetch_paginated_plugins` sort by `github_stars` has no `NULLS LAST`

- **Lines:** 3757-3761
- **Reviewer:** Claude (M3)
- **Description:** When sorting by `github_stars` (nullable), NULL values will sort to the top in descending order by PostgreSQL default. The skill equivalent uses `.nulls_last()` (line 1956). This should be consistent.

#### MEDIUM -- `fetch_paginated_plugins` pagination order lacks unique tiebreaker

- **Lines:** 3759-3761
- **Reviewers:** Codex (P2), project CLAUDE.md rule
- **Description:** The `ORDER BY` is `(sort_col, plugins_table.c.name)`. When `sort_col` is `name`, the tiebreaker is the same column, meaning ties on name produce non-deterministic ordering. Per project rules, every `LIMIT` query must have a unique tiebreaker. Add `plugins_table.c.id` as a final tiebreaker.

#### MEDIUM -- `list_plugin_versions` has no LIMIT clause

- **Lines:** 3814-3826
- **Reviewer:** Claude (M5)
- **Description:** Returns all versions for a plugin without any bound. While most plugins will have few versions, this is an unbounded query on a public endpoint. Should have a reasonable LIMIT or use pagination.

---

### `server/src/decision_hub/api/plugin_routes.py`

#### HIGH -- No input validation on `org_slug` and `plugin_name` path parameters

- **Lines:** 282-283, 332-334, 363-365, 396-397
- **Reviewer:** Claude (H3)
- **Description:** Path parameters `org_slug` and `plugin_name` across all public endpoints (detail, resolve, versions, audit) have no `max_length` or `pattern` constraints. Per project conventions, all public endpoint parameters should have `max_length` to prevent oversized payloads reaching the DB. The list endpoint correctly constrains its query parameters (lines 218-224).

#### MEDIUM -- Visibility check code repeated across 4 plugin endpoints (DRY violation)

- **Lines:** 293-295, 378-379, 410-411, and resolve endpoint
- **Reviewer:** Claude (M4)
- **Description:** The pattern `if plugin.visibility == "org" and (user_org_ids is None or plugin.org_id not in user_org_ids): raise HTTPException(...)` is duplicated in detail, versions, audit, and implicitly in resolve. Extract to a shared helper (e.g., `_enforce_plugin_visibility(plugin, user_org_ids)`).

#### MEDIUM -- `resolve_plugin` does redundant DB lookup

- **Lines:** 342-352
- **Reviewer:** Claude (M6)
- **Description:** `resolve_plugin_version()` already joins through the plugins table to find the version. Then `find_plugin_by_slug()` is called separately just to get `plugin.id` for `increment_plugin_downloads`. The plugin ID is available on the version record's `plugin_id` column; the second query is unnecessary.

#### LOW -- `PluginResolveResponse` lacks `kind` field

- **Lines:** 90-95
- **Reviewer:** Claude (L3)
- **Description:** The main `resolve_skill` endpoint returns `kind="plugin"` in its `ResolveResponse`, but the dedicated `PluginResolveResponse` does not include a `kind` field. Minor inconsistency for API consumers.

---

### `server/src/decision_hub/api/registry_routes.py`

#### HIGH -- Plugin precedence in `resolve_skill` is a silent behavioral change

- **Lines:** 720-732
- **Reviewer:** Claude (H1)
- **Description:** The unified `resolve_skill` endpoint now tries plugin resolution first, before skill resolution. If an org has both a skill and a plugin with the same name, `dhub install org/foo` will silently start returning the plugin instead of the skill. This is a breaking behavioral change with no migration path or client-side opt-in. Consider: (a) requiring an explicit `kind` query parameter, (b) preferring skills for backward compatibility with a deprecation notice, or (c) documenting this as an intentional precedence rule.

---

### `server/src/decision_hub/api/search_routes.py`

#### MEDIUM -- Search `candidate_map` overwrites entries when skill and plugin share a name

- **Lines:** 397-398
- **Reviewer:** Gemini (Medium)
- **Description:** The `candidate_map` is keyed by `(org_slug, name)`. Since plugins and skills have independent uniqueness constraints, a dict comprehension will silently overwrite the skill entry with the plugin entry (or vice versa) when both exist for the same org+name. Use a composite key that includes entity type, e.g., `(org_slug, name, "skill"|"plugin")`.

---

### `server/src/decision_hub/domain/tracker_service.py`

#### MEDIUM -- Permanently failed trackers do not mark plugins as removed

- **Lines:** 192-204
- **Reviewer:** Gemini (Medium)
- **Description:** When trackers cross the permanent-failure threshold, `mark_skills_source_removed(conn, removed_urls)` is called but there is no corresponding `mark_plugins_source_removed`. Plugin records will never have `source_repo_removed` set to `true`, even when the repo is confirmed gone.

#### LOW -- `_publish_plugin_from_tracker` missing `VersionConflictError` handler

- **Lines:** 834-889
- **Reviewer:** Claude (M8)
- **Description:** The `try` block catches `GauntletRejectionError` but not `VersionConflictError`. If the tracker attempts to republish a version that already exists, the unhandled exception will propagate as a transient error, incrementing the failure counter unnecessarily. The skill tracker path handles this case.

---

### `server/src/decision_hub/domain/plugin_publish_pipeline.py`

#### LOW -- S3 upload failure leaves deprecation uncommitted

- **Lines:** 352-375
- **Reviewer:** Gemini (Low)
- **Description:** Step 10 commits the DB (plugin version record), then step 11 uploads to S3, then deprecates skills. If S3 upload fails (line 356-363), the exception is re-raised before `deprecate_skills_by_repo_url` runs. The plugin version record exists in DB pointing to a missing S3 key, and old skills remain un-deprecated. The code has an explicit comment acknowledging this matches the skill pipeline, so this is a known limitation, not a new bug. Documenting here for completeness.

---

### `frontend/src/hooks/useInfiniteScroll.ts`

#### LOW -- Old items remain briefly visible during filter change

- **Lines:** 40-67
- **Reviewer:** Claude (H4 -- downgraded to Low after code inspection)
- **Description:** When deps change, `setItems([])` is not called synchronously before the fetch. Old items remain in state while `loading` is set to `true`. If consuming components render `items` during the loading state (before the skeleton/spinner), there will be a brief flash of stale data. In practice, most consumers check `loading` first and show a skeleton, making this a cosmetic issue.

---

### `frontend/src/pages/PluginDetailPage.tsx`

#### LOW -- Non-null assertions without runtime guards

- **Reviewer:** Claude (L1)
- **Description:** Component uses non-null assertions (`!`) on data that could be undefined during loading or error states. Should add explicit null checks or optional chaining.

---

## Deduplication Notes

The following issues were independently flagged by multiple reviewers, increasing confidence in their validity:

| Finding | Reviewers |
|---------|-----------|
| `create_zip` strips `.claude-plugin/` directories | Codex, Claude (+ Gemini implicitly) |
| Missing `search_vector` trigger | Codex, Claude |
| Org listing exposes private-plugin-only orgs | Gemini, Codex |
| Cross-org deprecation in `deprecate_skills_by_repo_url` | Codex (explicitly), Gemini (partially) |
