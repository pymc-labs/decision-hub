# PR #256 Code Review: feat: first-class agent plugin support (Codex)

**Verdict:** The patch introduces multiple functional regressions in new plugin flows: automated plugin publishing packages invalid archives, plugin text search cannot return results, and visibility/deprecation logic can expose or mutate data incorrectly. These are correctness issues in core API and automation paths, so the patch should not be considered correct.

**Full review comments:**

- **[P1] Keep plugin dot-directories in tracker publish archives** -- `server/src/decision_hub/domain/tracker_service.py:826`
  `_publish_plugin_from_tracker` packages the repo with `create_zip()`, but that helper excludes any path component starting with `.`. Plugin manifests live under directories like `.claude-plugin/`, so the archive passed to `execute_plugin_publish()` is missing `plugin.json` and `parse_plugin_manifest()` fails, which breaks tracker-driven plugin republishes (the crawler plugin path has the same packaging pattern).

- **[P1] Restrict plugin-driven deprecations to the publishing org** -- `server/src/decision_hub/infra/database.py:3673-3675`
  This update targets all skills with the same `source_repo_url` regardless of organization. If multiple orgs publish skills from one repo (or a caller supplies a forged repo URL), publishing a plugin in one org will deprecate other orgs' skills and point them at this plugin, causing cross-tenant data mutation.

- **[P2] Exclude org-private plugins from public org profile discovery** -- `server/src/decision_hub/infra/database.py:985`
  `list_all_org_profiles()` includes org IDs from all published plugins but does not filter `visibility='public'`. That makes `/v1/orgs/profiles` expose organizations that only have org-private plugins, leaking private metadata and producing inconsistent public org discovery behavior.

- **[P1] Populate plugin search vectors before applying FTS filters** -- `server/src/decision_hub/infra/database.py:3742`
  Plugin list search applies `search_vector @@ plainto_tsquery(...)`, but plugin writes never populate `plugins.search_vector` (there is no trigger/backfill or explicit write path for it). With NULL vectors, any non-empty `search` query filters out all plugins, so text search on `/v1/plugins` is effectively broken.

- **[P2] Add a unique tiebreaker to plugin list pagination order** -- `server/src/decision_hub/infra/database.py:3761`
  Pagination uses `LIMIT/OFFSET` with `ORDER BY <sort_col>, plugins.name`, but that ordering is not unique across rows (e.g., same name in different orgs with equal sort values). This can make page boundaries unstable and produce duplicate/missing items between pages; include a unique tiebreaker such as org slug/id.
