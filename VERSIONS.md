# Plan: Smart Version Bumping + Delete All Versions

## Context

Currently `dhub publish` requires the user to manually specify `--version 1.2.3` every time. This is tedious and error-prone. The user wants semver auto-bumping similar to npm/cargo: first publish defaults to `0.1.0`, subsequent publishes auto-bump patch (`0.1.0` → `0.1.1`), with `--major`/`--minor`/`--patch` flags to control the bump level. Explicit `--version X.Y.Z` still works as an override.

Also, `dhub delete` currently requires `--version` — the user wants it optional so omitting it deletes all versions of the skill.

**What already works (no changes needed):**
- `dhub install org/skill --version 1.0.0` — installs specific version (resolve_version handles both "latest" and exact match)
- `dhub list` — already shows only the latest version per skill

## Changes

### 1. Add `bump_version()` to client validation module
**File:** `client/src/dhub/core/validation.py`
- Add `bump_version(current: str, bump: str = "patch") -> str` — pure function
- Parses `major.minor.patch`, increments the specified component, resets lower components
- `bump_version("1.2.3", "patch")` → `"1.2.4"`
- `bump_version("1.2.3", "minor")` → `"1.3.0"`
- `bump_version("1.2.3", "major")` → `"2.0.0"`

### 2. Add server endpoint to get latest version of a skill
**File:** `server/src/decision_hub/api/registry_routes.py`
- `GET /v1/skills/{org_slug}/{skill_name}/latest-version` — public, no auth
- Returns `{"version": "1.2.3"}` or 404 if skill has no versions
- Reuses existing `resolve_version(conn, org_slug, skill_name, "latest")` from `database.py:660`

### 3. Update `publish_command` for auto-bumping
**File:** `client/src/dhub/cli/registry.py`
- Change `--version` from required to optional (default `None`)
- Add `--patch`/`--minor`/`--major` boolean flags (mutually exclusive with `--version`)
- Default behavior when nothing specified: `--patch`
- Flow:
  1. If `--version` given → use it directly (current behavior)
  2. Otherwise → call `GET /v1/skills/{org}/{name}/latest-version`
     - If 404 (first publish) → use `"0.1.0"`
     - If found → `bump_version(latest, bump_level)`
  3. Print the resolved version before uploading

### 4. Add server endpoint to delete all versions
**File:** `server/src/decision_hub/api/registry_routes.py`
- `DELETE /v1/skills/{org_slug}/{skill_name}` — requires auth (owner/admin)
- Fetches all versions for the skill, deletes each from S3, deletes all version rows, deletes the skill row
- Returns `{"org_slug": ..., "skill_name": ..., "versions_deleted": N}`

### 5. Add `delete_all_versions()` and `delete_skill()` to database.py
**File:** `server/src/decision_hub/infra/database.py`
- `delete_all_versions(conn, skill_id) -> list[str]` — deletes all version rows, returns list of s3_keys for S3 cleanup
- `delete_skill(conn, skill_id) -> None` — deletes the skill row itself (after versions are gone)

### 6. Update `delete_command` for optional version
**File:** `client/src/dhub/cli/registry.py`
- Change `--version` from required to optional (default `None`)
- If `--version` given → delete single version (current behavior, calls `DELETE /v1/skills/{org}/{name}/{version}`)
- If `--version` omitted → prompt for confirmation via `typer.confirm("Delete ALL versions of org/skill?", abort=True)`, then call `DELETE /v1/skills/{org}/{name}` to delete all versions

### 7. Tests
- **Client:** `test_bump_version_patch`, `test_bump_version_minor`, `test_bump_version_major` in `client/tests/test_core/test_validation.py`
- **Client:** Update `test_publish_command` in `test_registry_cli.py` for auto-bump flow (mock the latest-version call)
- **Client:** Update `test_delete_command` in `test_registry_cli.py` for delete-all flow
- **Server:** `test_get_latest_version`, `test_get_latest_version_not_found` in `test_registry_routes.py`
- **Server:** `test_delete_all_versions`, `test_delete_all_versions_auth` in `test_registry_routes.py`

### 8. Deploy + migrate
- No DB schema changes needed (all new logic uses existing tables)
- `modal deploy modal_app.py`

## Files to modify
- `client/src/dhub/core/validation.py` — bump_version()
- `client/src/dhub/cli/registry.py` — publish auto-bump + delete-all
- `server/src/decision_hub/api/registry_routes.py` — latest-version + delete-all endpoints
- `server/src/decision_hub/infra/database.py` — delete_all_versions(), delete_skill()
- `client/tests/test_core/test_validation.py` — bump tests
- `client/tests/test_cli/test_registry_cli.py` — publish + delete tests
- `server/tests/test_api/test_registry_routes.py` — new endpoint tests

## Verification
1. `uv run --package dhub pytest client/tests/`
2. `uv run --package decision-hub-server pytest server/tests/`
3. `modal deploy modal_app.py`
4. End-to-end:
   - `dhub publish . --org pymc-labs --name test-skill` → publishes as 0.1.0
   - `dhub publish . --org pymc-labs --name test-skill` → auto-bumps to 0.1.1
   - `dhub publish . --org pymc-labs --name test-skill --minor` → bumps to 0.2.0
   - `dhub publish . --org pymc-labs --name test-skill --version 1.0.0` → explicit
   - `dhub delete pymc-labs/test-skill --version 0.1.0` → deletes one version
   - `dhub delete pymc-labs/test-skill` → prompts confirmation, deletes all remaining versions
