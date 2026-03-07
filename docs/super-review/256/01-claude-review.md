# PR #256 Code Review: feat: first-class agent plugin support (Claude)

## Summary

This is a large feature PR (~3,500 lines of new code) adding a complete plugin system alongside the existing skills system. It introduces: plugin manifest parsing (`shared/`), a full publish pipeline with gauntlet safety checks (`server/`), new API routes, database tables + migrations, crawler/tracker plugin support, and a complete frontend (list + detail pages). The implementation is generally well-structured and follows existing codebase patterns. However, there are several issues ranging from critical to low severity.

---

## Critical

### C1. Missing `search_vector` trigger for `plugins` table -- FTS will silently return zero results

**Files:** `server/migrations/20260305_223006_add_plugin_tables.sql`

The `plugins` table has a `search_vector TSVECTOR` column and a GIN index on it, and both `fetch_paginated_plugins` and `search_plugins_hybrid` query it. However, there is **no trigger function** to populate this column. The skills table has `skills_search_vector_update()` (created in `20260212_130000_add_fts_and_embeddings.sql`), but no equivalent exists for plugins.

**Impact:** The `search_vector` column will always be `NULL` for every plugin row. The list endpoint's `search` filter and the hybrid search FTS leg will never match any plugins. Users will be unable to find plugins via search.

**Fix:** Add a `plugins_search_vector_update()` trigger function and corresponding `BEFORE INSERT OR UPDATE` trigger in the migration, mirroring the skills pattern. The trigger should build the vector from `name`, `description`, `category`, and the org slug.

### C2. Server-side `create_zip` strips plugin directories when publishing from tracker/crawler

**Files:** `server/src/decision_hub/domain/tracker_service.py` (line ~826), `server/src/decision_hub/domain/repo_utils.py` (line 94-108), `server/src/decision_hub/scripts/crawler/processing.py` (line ~575)

The server-side `create_zip()` in `repo_utils.py` unconditionally skips all directories starting with `.` (line 106). When `_publish_plugin_from_tracker` and `_publish_plugin` in the crawler call `create_zip(repo_root)`, the resulting zip will **exclude** `.claude-plugin/`, `.cursor-plugin/`, etc. The `extract_plugin_to_dir` call downstream will then find no platform directories and `parse_plugin_manifest` will raise `ValueError("No plugin platform directories found")`.

The client-side `_create_zip` was correctly updated with `preserve_dot_dirs`, but the server-side counterpart was not.

**Impact:** All tracker-based and crawler-based plugin publishes will fail with a ValueError on manifest parsing.

**Fix:** Either (a) add a `preserve_dot_dirs` parameter to `repo_utils.create_zip` matching the client implementation, or (b) call `_create_zip` from client code if appropriate. Both `_publish_plugin_from_tracker` and `_publish_plugin` in crawler processing need to pass the plugin dot dirs.

---

## High

### H1. Plugin precedence in `resolve_skill` is a breaking behavioral change

**File:** `server/src/decision_hub/api/registry_routes.py` (lines 720-732)

The `resolve_skill` endpoint now tries plugin resolution **first**, falling back to skills only if no plugin matches. If an org has both a skill named `foo` and a plugin named `foo`, the existing `dhub install org/foo` behavior silently changes from installing the skill to installing the plugin. This is undocumented and could break existing workflows.

**Recommendation:** Either (a) use the `kind` field from the request to disambiguate (add an optional `kind` query parameter, defaulting to skill-first for backward compatibility), or (b) at minimum, document this precedence clearly and ensure there's no existing name collision in the current dataset before merging.

### H2. `_publish_plugin_from_tracker` calls `conn.commit()` on a connection obtained from `engine.connect()`, but `execute_plugin_publish` already called `conn.commit()` internally

**File:** `server/src/decision_hub/domain/tracker_service.py` (lines ~852-870)

`execute_plugin_publish` calls `conn.commit()` at line 4095 of the pipeline, and then `_publish_plugin_from_tracker` calls `conn.commit()` again at line ~868 after `update_skill_tracker`. This means that if `update_skill_tracker` fails, the plugin version is already committed but the tracker is in an inconsistent state (committed version but stale tracker SHA). The skill equivalent `_publish_skill_from_tracker` has similar structure, so this may be an inherited pattern, but it's worth flagging since the plugin pipeline has an extra `deprecate_skills_by_repo_url` commit between them.

### H3. No input validation on `org_slug` and `plugin_name` path parameters in public endpoints

**File:** `server/src/decision_hub/api/plugin_routes.py`

The public endpoints `get_plugin_detail`, `resolve_plugin`, `get_plugin_versions`, and `get_plugin_audit_log` accept `org_slug` and `plugin_name` as bare path parameters with no `max_length` or `pattern` constraints. The skills routes have `max_length` on query params but also rely on the DB for path params. However, these values flow into SQL `WHERE` clauses and into the `find_plugin_by_slug` function. While SQLAlchemy parameterizes them (no injection risk), excessively long strings could hit the 30s statement_timeout or consume resources.

**Recommendation:** Add `Path(max_length=100)` constraints or similar validation to path parameters, matching the existing pattern for query parameters.

### H4. `useInfiniteScroll` hook change removes `setItems([])` on filter change -- stale data flash

**File:** `frontend/src/hooks/useInfiniteScroll.ts` (line removed at diff line 602-603)

The removal of `setItems([])` when the fetch key changes means old items remain visible while new data loads. On the SkillsPage (which also uses this hook), changing a filter will briefly show stale results from the previous filter before the new data arrives. The CLAUDE.md states: "Reset state on context changes."

**Recommendation:** Restore `setItems([])` or use a different mechanism (like a loading overlay that hides old items) to prevent stale data display.

---

## Medium

### M1. `_create_zip` `preserve_dot_dirs` only checks top-level parts, not nested

**File:** `client/src/dhub/cli/registry.py` (line 249)

The condition `part not in _preserve` checks each component of the path. If a dot directory is nested (e.g., `subdir/.claude-plugin/plugin.json`), the `subdir` part won't be skipped but `.claude-plugin` will match `_preserve`. However, the current `_preserve` set is built from `path.iterdir()` which only finds top-level dirs. A nested `.claude-plugin/` wouldn't be in the set. This is correct behavior for the current use case but the logic is fragile -- the `any()` check treats `_preserve` as applying to any level, which is inconsistent with how it's populated.

### M2. Missing `ForeignKey` declaration for `deprecated_by_plugin_id` on the SQLAlchemy skills table definition

**File:** `server/src/decision_hub/infra/database.py` (line ~459)

The migration has `ALTER TABLE skills ADD COLUMN IF NOT EXISTS deprecated_by_plugin_id UUID REFERENCES plugins(id)`, but the SQLAlchemy table definition only has:
```python
Column("deprecated_by_plugin_id", PG_UUID(as_uuid=True), nullable=True),
```
It is missing the `ForeignKey("plugins.id")` declaration. While this doesn't affect runtime behavior (the migration creates the FK), it will cause the CI schema-drift check to flag a difference between the SQLAlchemy metadata and the actual database schema.

### M3. `fetch_paginated_plugins` sort by `github_stars` has no `NULLS LAST` handling

**File:** `server/src/decision_hub/infra/database.py` (~line 3750-3756)

When sorting by `github_stars` descending, plugins without stars (`NULL`) will sort before starred plugins in PostgreSQL (NULLs sort first in DESC). The skills pagination has the same issue, but it's worth noting for new code. Users sorting by stars will see all unstarred plugins first.

### M4. DRY violation: visibility check code is repeated across 4 plugin endpoints

**File:** `server/src/decision_hub/api/plugin_routes.py` (lines ~3068-3073, ~3155-3156, ~3185-3188)

The pattern `if plugin.visibility == "org" and (user_org_ids is None or plugin.org_id not in user_org_ids): raise HTTPException(status_code=404, ...)` is repeated in `get_plugin_detail`, `get_plugin_versions`, and `get_plugin_audit_log`. This should be extracted to a helper function like `_enforce_plugin_visibility(plugin, user_org_ids)`.

### M5. `list_plugin_versions` and `find_plugin_audit_logs` are unbounded or have only a large limit

**File:** `server/src/decision_hub/infra/database.py`

`list_plugin_versions` has no `LIMIT` clause at all -- a plugin with many versions would return all of them. `find_plugin_audit_logs` has a `.limit(50)` which is reasonable. The versions endpoint should have a limit to prevent excessive response sizes.

### M6. `resolve_plugin` endpoint does two DB lookups -- `resolve_plugin_version` then `find_plugin_by_slug`

**File:** `server/src/decision_hub/api/plugin_routes.py` (lines ~3120-3129)

The `resolve_plugin` endpoint calls `resolve_plugin_version` (which joins plugins and organizations) and then separately calls `find_plugin_by_slug` just to get the plugin ID for `increment_plugin_downloads`. The plugin ID is available in the version record (`plugin_ver.plugin_id`) and could be used directly, avoiding the redundant query.

### M7. `deprecated_by_plugin_id` FK in the migration lacks `ON DELETE SET NULL`

**File:** `server/migrations/20260305_223006_add_plugin_tables.sql` (line ~93)

```sql
ALTER TABLE skills ADD COLUMN IF NOT EXISTS deprecated_by_plugin_id UUID REFERENCES plugins(id);
```

If a plugin is deleted, this FK will prevent the deletion (`ON DELETE NO ACTION` is the default). Given that `plugin_versions` uses `ON DELETE CASCADE`, there's an inconsistency. A deleted plugin should probably SET NULL on the deprecation reference so the skill becomes un-deprecated rather than blocking plugin deletion.

### M8. `_publish_plugin_from_tracker` catches `GauntletRejectionError` but not `VersionConflictError` or other exceptions

**File:** `server/src/decision_hub/domain/tracker_service.py` (lines ~854-892)

Unlike `_publish_skill_from_tracker` which handles various failure modes, the plugin tracker publish function only catches `GauntletRejectionError`. A `VersionConflictError` (unlikely with `auto_bump_version=True` but possible in a race) or any other exception will propagate and potentially mark the tracker as errored without useful context.

---

## Low

### L1. `PluginDetailPage` uses non-null assertions (`orgSlug!`, `pluginName!`) without guards

**File:** `frontend/src/pages/PluginDetailPage.tsx` (lines ~1245-1246)

`useParams` returns potentially undefined values, but the code uses `!` assertions in the `useApi` callbacks. If someone navigates directly to a malformed URL, this will crash. A guard early in the component (returning NotFound if params are undefined) would be safer.

### L2. Hardcoded platform list in frontend

**File:** `frontend/src/pages/PluginsPage.tsx` (line ~2067)

```typescript
const PLATFORM_OPTIONS = ["All", "Claude", "Cursor", "Codex"];
```

This list will need manual updating as new platforms are added. Consider fetching available platforms from the API or the taxonomy endpoint.

### L3. `PluginResolveResponse` in `plugin_routes.py` lacks a `kind` field

**File:** `server/src/decision_hub/api/plugin_routes.py`

The `ResolveResponse` in `registry_routes.py` was updated with `kind: str = "skill"`, but `PluginResolveResponse` doesn't include a `kind` field. When a client resolves via the dedicated plugin endpoint (`/v1/plugins/{org}/{name}/resolve`), they can infer it's a plugin, but consistency would help.

### L4. `report.summary` vs `report.gauntlet_summary` naming inconsistency

**File:** `server/src/decision_hub/domain/plugin_publish_pipeline.py` (line ~3992)

The `GauntletReport` has a property `gauntlet_summary`, but line 3992 accesses `report.summary` via the `GauntletRejectionError`. This works because `GauntletRejectionError` stores the summary as `self.summary`, but the naming is confusing when reading the code.

### L5. `_SECURITY_SCAN_NAMES` includes `.env` which is a false positive target

**File:** `server/src/decision_hub/domain/plugin_publish_pipeline.py` (line ~3813)

Including `.env` in the scannable names list means if a plugin accidentally includes a `.env` file, its contents will be scanned by the gauntlet (potentially revealing secrets in scan logs). On the flip side, scanning for credential patterns in `.env` files is arguably valuable. Consider whether scanning `.env` files is intentional or if they should just be flagged as a warning.

### L6. Test class uses classes for test grouping instead of plain functions

**Files:** Multiple test files use `class TestXxx:` pattern

Per the CLAUDE.md guidelines ("Prefer pure, stateless functions... Only introduce classes if state management or a protocol/abstraction is absolutely required"), the test files use classes for grouping which is not consistent with the stated preference. However, this is the existing test convention in the codebase so it's acceptable.

---

## Positive Observations

1. **Security**: Zip-slip prevention via `validate_zip_entries` is consistently applied on both server extraction and client install paths. Upload size limits, zip entry count limits, and rate limiters are all properly configured.

2. **Visibility enforcement**: The `_apply_plugin_visibility_filter` and per-endpoint visibility checks are thorough, and the test suite (`test_plugin_visibility.py`) covers unauthenticated, non-member, and member access patterns.

3. **Test coverage**: The PR includes extensive tests -- plugin manifest parsing, E2E pipeline, gauntlet checks, audit log FK correctness, tracker kind updates, pagination, and visibility enforcement. The tracker consecutive-failure threshold change is also well-tested.

4. **Database design**: The migration uses `IF NOT EXISTS`/`IF EXISTS` for idempotency, enables RLS, includes appropriate indexes, and follows the established table structure patterns. The denormalized `latest_*` columns with `_refresh_plugin_latest_version` mirror the existing skills pattern.

5. **Deprecation system**: The auto-deprecation of skills when a plugin is published from the same repo is a thoughtful design choice, with proper UI banners and install command suggestions.
