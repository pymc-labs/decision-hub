# Senior Code Review -- PR #256: First-Class Agent Plugin Support

## Executive Summary

This is a substantial, well-structured PR that adds a complete "plugins" entity type alongside the existing "skills" system. It touches every layer: database schema, domain logic, API routes, CLI, crawler, tracker, search, and frontend. The overall architecture is sound -- the author clearly understands the codebase patterns and replicated them consistently for plugins.

The junior review identified 19 findings. After thorough examination, I am keeping 2 as Critical (both are real ship-blockers), upgrading 1 finding to Critical, removing 4 findings as invalid or negligible, downgrading several others, and adding 3 new findings the junior missed. The PR is not mergeable until the 3 Critical issues are resolved.

**Overall PR Quality: 7/10.** Impressive scope, good pattern adherence, solid test coverage for visibility. The three Critical bugs are the kind that slip through large PRs because they require cross-module reasoning. Fix those and this is mergeable.

---

## Severity Summary (revised)

| Severity | Count | Changed from Junior |
|----------|-------|---------------------|
| Critical | 3     | +1 (upgraded cross-tenant deprecation) |
| High     | 2     | -2 (removed path validation, downgraded resolve precedence) |
| Medium   | 6     | -2 (removed DRY/redundant lookup; those are acceptable) |
| Low      | 3     | -2 (removed negligible findings) |
| **Total** | **14** | **-5 net removed, +3 added** |

---

## Critical Findings

### C1. Missing `search_vector` trigger for `plugins` table [CONFIRMED]

**File:** `server/migrations/20260305_223006_add_plugin_tables.sql`
**Junior rating:** Critical -- **Agree.**

The migration creates the `search_vector TSVECTOR` column (line 29) and a GIN index on it (line 43), but never creates the trigger function to populate it. The skills table has a `skills_search_vector_update()` function and a `BEFORE INSERT OR UPDATE` trigger. Plugins have nothing equivalent.

**Impact:** Both `fetch_paginated_plugins` (line 3742) and `search_plugins_hybrid` (line 2232) query `plugins.search_vector`. Since the column is always NULL, every full-text search query returns zero results. The entire plugin search pipeline is dead on arrival.

**Fix:** Create a new migration that adds the trigger function and trigger, plus backfills existing rows:

```sql
CREATE OR REPLACE FUNCTION plugins_search_vector_update()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE org_slug TEXT;
BEGIN
    SELECT slug INTO org_slug FROM public.organizations WHERE id = NEW.org_id;
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(org_slug, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.category, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'C');
    RETURN NEW;
END;
$$;

DO $$ BEGIN
    CREATE TRIGGER trg_plugins_search_vector
        BEFORE INSERT OR UPDATE OF name, description, category, org_id
        ON plugins FOR EACH ROW
        EXECUTE FUNCTION plugins_search_vector_update();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Backfill existing rows
ALTER TABLE plugins DISABLE TRIGGER set_plugins_updated_at;
UPDATE plugins SET name = name WHERE search_vector IS NULL;
ALTER TABLE plugins ENABLE TRIGGER set_plugins_updated_at;
```

**Elegance:** This mirrors the existing pattern exactly. No shortcuts.

---

### C2. Server-side `create_zip` strips `.claude-plugin/` directories [CONFIRMED]

**File:** `server/src/decision_hub/domain/repo_utils.py`, lines 94-108
**Junior rating:** Critical -- **Agree.**

The server-side `create_zip()` unconditionally skips all path components starting with `.` (line 106). Plugin manifests live under `.claude-plugin/`. The client-side `_create_zip` was correctly updated with a `preserve_dot_dirs` parameter, but the server-side equivalent was not.

Both the tracker (`_publish_plugin_from_tracker`, line 826) and the crawler (`_publish_plugin` in `processing.py`) call `create_zip(repo_root)` without any dot-dir preservation.

**Impact:** All automated plugin publishes (tracker and crawler) are broken. Only CLI publishes work.

**Fix:** Add `preserve_dot_dirs` parameter to server-side `create_zip`:

```python
def create_zip(path: Path, *, preserve_dot_dirs: frozenset[str] | None = None) -> bytes:
    _preserve = preserve_dot_dirs or frozenset()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(path.rglob("*")):
            if not file.is_file():
                continue
            relative = file.relative_to(path)
            parts = relative.parts
            if any(
                (part.startswith(".") and part not in _preserve) or part == "__pycache__"
                for part in parts
            ):
                continue
            zf.write(file, relative)
    return buf.getvalue()
```

Then update all callers to detect and pass plugin dot dirs:

```python
from dhub_core.plugin_manifest import PLUGIN_DIR_PATTERN

plugin_dot_dirs = frozenset(
    d.name for d in repo_root.iterdir()
    if d.is_dir() and PLUGIN_DIR_PATTERN.match(d.name)
)
zip_bytes = create_zip(repo_root, preserve_dot_dirs=plugin_dot_dirs)
```

**Elegance:** Single function with opt-in allowlist, matching the client-side pattern.

---

### C3. `deprecate_skills_by_repo_url` is not scoped to the publishing org [UPGRADED from High]

**File:** `server/src/decision_hub/infra/database.py`, lines 3669-3675
**Junior rating:** High -- **Upgrading to Critical.**

The `WHERE` clause filters only on `source_repo_url` with no `org_id` constraint. If two different organizations publish skills from the same GitHub repo, publishing a plugin from Org A will deprecate Org B's skills. This is a cross-tenant data mutation.

**Why Critical:**
1. Data integrity violation across tenant boundaries
2. Happens automatically on every plugin publish with a `source_repo_url`
3. The damage is silent -- Org B's skills disappear with no notification
4. Cannot be undone without manual DB intervention

**Fix:** Add an `org_id` filter:

```python
def deprecate_skills_by_repo_url(
    conn: Connection,
    source_repo_url: str,
    plugin_id: UUID,
    message: str,
    org_id: UUID,
) -> int:
    stmt = (
        sa.update(skills_table)
        .where(
            sa.and_(
                skills_table.c.source_repo_url == source_repo_url,
                skills_table.c.org_id == org_id,
                skills_table.c.deprecated == False,
            )
        )
        .values(
            deprecated=True,
            deprecated_by_plugin_id=plugin_id,
            deprecation_message=message,
        )
    )
    result = conn.execute(stmt)
    return result.rowcount
```

---

## High Findings

### H1. `list_all_org_profiles` exposes orgs with only private plugins [CONFIRMED]

**File:** `server/src/decision_hub/infra/database.py`, line 985

The `plugin_org_ids` subquery does not filter on `visibility = 'public'`, while the skill subquery correctly does. An org with only private plugins will appear in the public `/v1/orgs` endpoint.

**Fix:**

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

### H2. `fetch_paginated_plugins` sort lacks `NULLS LAST` and proper tiebreaker [CONFIRMED, consolidated]

**File:** `server/src/decision_hub/infra/database.py`, lines 3759-3761

The skill sort implementation uses `.nulls_last()` on nullable columns and a two-column tiebreaker `(org_slug, name)`. The plugin version has a partial tiebreaker and no null handling.

**Fix:** Mirror the skills pattern with `NULLS LAST` for `github_stars` and a two-column tiebreaker `(org_slug, name)`.

---

## Medium Findings

### M1. `deprecated_by_plugin_id` FK lacks `ON DELETE SET NULL` in migration [CONFIRMED]

**File:** `server/migrations/20260305_223006_add_plugin_tables.sql`, line 90

Default `NO ACTION` means deleting a plugin will fail if any skill references it. Also, the SQLAlchemy Column definition lacks the `ForeignKey` declaration, which will trigger CI schema-drift.

**Fix:** New migration adding `ON DELETE SET NULL`, plus update SQLAlchemy model.

### M2. `_PLUGIN_SUMMARY_COLUMNS` omits `source_repo_removed` and `github_is_archived` [CONFIRMED]

**File:** `server/src/decision_hub/infra/database.py`, lines 761-781

These fields exist on the `plugins` table but are never fetched in plugin list/search queries. They will silently default to `False`.

### M3. `list_plugin_versions` has no LIMIT clause [CONFIRMED]

**File:** `server/src/decision_hub/infra/database.py`, lines 3814-3826

Unbounded query on a public endpoint. Add `.limit(100)` or accept a `limit` parameter.

### M4. Search `candidate_map` overwrites entries when skill and plugin share a name [CONFIRMED]

**File:** `server/src/decision_hub/api/search_routes.py`, lines 397-398

Dict keyed by `(org_slug, name)` will silently overwrite when both a skill and plugin exist with the same org+name. Include `kind` in the key.

### M5. Permanently failed trackers do not mark plugins as removed [CONFIRMED]

**File:** `server/src/decision_hub/domain/tracker_service.py`, lines 192-204

`mark_skills_source_removed` is called but there is no `mark_plugins_source_removed`. Plugin records will never have `source_repo_removed` set to `true`.

### M6. `PluginResolveResponse` lacks `kind` field [CONFIRMED]

**File:** `server/src/decision_hub/api/plugin_routes.py`, lines 90-95

The CLI uses `kind` to decide whether to install as a skill or plugin. If someone resolves through the plugin-specific endpoint, `kind` won't be present.

---

## Low Findings

### L1. `_publish_plugin_from_tracker` missing `VersionConflictError` handler [CONFIRMED]

**File:** `server/src/decision_hub/domain/tracker_service.py`, lines 834-886

Catches `GauntletRejectionError` but not `VersionConflictError`. Low risk because `auto_bump_version=True` covers the normal case.

### L2. S3 upload failure leaves deprecation uncommitted [CONFIRMED, acceptable]

**File:** `server/src/decision_hub/domain/plugin_publish_pipeline.py`, lines 352-375

Known limitation, matches skill pipeline behavior. Code has explicit comment acknowledging this.

### L3. `useInfiniteScroll` stale items flash [CONFIRMED, cosmetic]

**File:** `frontend/src/hooks/useInfiniteScroll.ts`, line 42

Old items remain visible during filter change. Most consumers check `loading` first and show a skeleton.

---

## Findings Removed from Junior Review

1. **"No input validation on path parameters" (was High):** Existing skill endpoints have the same pattern. Consistent with codebase.
2. **"Visibility check code repeated (DRY)" (was Medium):** 2 lines of code. Extracting adds more complexity than it saves.
3. **"`resolve_plugin` does redundant DB lookup" (was Medium):** The second call retrieves `Plugin` for `increment_plugin_downloads`, not the same data as `PluginVersion`.
4. **"Plugin precedence in `resolve_skill` is a silent behavioral change" (was High):** Deliberate design. `kind` field was added to `ResolveResponse`, CLI already handles it.

---

## New Findings (Missed by Junior)

### NEW-1 (Medium): Crawler `_publish_plugin` also needs dot-dir preservation

**File:** `server/src/decision_hub/scripts/crawler/processing.py`, line 5851

Specific instance of C2 in the crawler code path. Needs the same `preserve_dot_dirs` treatment.

### NEW-2 (Medium): Plugin visibility not propagated on re-publish

**File:** `server/src/decision_hub/domain/plugin_publish_pipeline.py`, lines 276-286

When a plugin already exists, the update does NOT update `visibility`, `source_repo_url`, `author_name`, `homepage`, `license`, `keywords`, or `platforms`. Commit `50fc32e` claims to "propagate visibility from metadata on plugin publish" but this may not be fully implemented.

### NEW-3 (Low): CLI sends `visibility: "private"` but server only accepts `"public"` or `"org"`

**File:** `client/src/dhub/cli/registry.py`, line 81

The CLI maps `--private` to `"private"` for plugins, but the server only accepts `"public"` or `"org"`. The skill path correctly maps `--private` to `"org"`.

---

## Summary of Required Actions

**Must fix before merge (Critical):**
1. Add `search_vector` trigger + backfill migration for `plugins` table
2. Add `preserve_dot_dirs` parameter to server-side `create_zip` and update all callers
3. Scope `deprecate_skills_by_repo_url` to the publishing org's `org_id`

**Should fix before merge (High):**
4. Add `visibility = 'public'` filter to `plugin_org_ids` in `list_all_org_profiles`
5. Add `NULLS LAST` and proper two-column tiebreaker to `fetch_paginated_plugins` sort

**Fix soon after merge (Medium):**
6. Add `ON DELETE SET NULL` to `deprecated_by_plugin_id` FK
7. Add missing columns to `_PLUGIN_SUMMARY_COLUMNS`
8. Add LIMIT to `list_plugin_versions`
9. Fix `candidate_map` key collision in search
10. Add `mark_plugins_source_removed` for permanently failed trackers
11. Add `kind` field to `PluginResolveResponse`

**Fix at convenience (Low):**
12. Map `--private` to `"org"` in CLI plugin publish
13. Handle `VersionConflictError` in `_publish_plugin_from_tracker`
14. `useInfiniteScroll` stale items flash
