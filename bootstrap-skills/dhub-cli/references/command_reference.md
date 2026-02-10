# dhub Command Reference

Complete reference for every dhub command, flag, and option.

## dhub login

Authenticate with Decision Hub via GitHub Device Flow.

```
dhub login [--api-url URL]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--api-url` | string | from config | Override the API URL for this login |

**Flow:**
1. POST `/auth/github/code` → receives device code + user code
2. Display user code and `https://github.com/login/device` URL
3. Poll POST `/auth/github/token` every 5s (HTTP 428 = pending, 200 = done)
4. Save token to `~/.dhub/config.{env}.json`
5. Timeout: 300 seconds

**Config after login:**
```json
{"api_url": "https://lfiaschi--api.modal.run", "token": "<oauth_token>"}
```

---

## dhub logout

Remove stored authentication token.

```
dhub logout
```

No options. Sets token to null in the config file.

---

## dhub env

Show active environment, config file path, and API URL.

```
dhub env
```

No options. Displays the current `DHUB_ENV` value, resolved config path, and API URL.

---

## dhub init

Scaffold a new skill project with SKILL.md and src/ directory.

```
dhub init [PATH]
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `PATH` | no | current directory | Where to create the skill |

Interactive — prompts for skill name and description. Validates name against pattern `^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$`.

**Creates:**
```
skill-name/
  SKILL.md
  src/
```

---

## dhub publish

Publish a skill to the registry.

```
dhub publish [SKILL_REF] [PATH] [--version VER] [--patch] [--minor] [--major] [--private] [--ref REF]
```

| Argument/Option | Required | Default | Description |
|----------------|----------|---------|-------------|
| `SKILL_REF` | no | auto-detect from SKILL.md | Org/skill reference, path, or git URL |
| `PATH` | no | `.` | Path to skill directory |
| `--version` | no | auto-bump | Explicit semver (e.g. `1.2.3`) |
| `--patch` | no | true (default bump) | Bump patch version |
| `--minor` | no | false | Bump minor version |
| `--major` | no | false | Bump major version |
| `--private` | no | false | Publish as org-private (visible only to org members) |
| `--ref` | no | default branch | Branch/tag/commit (git URLs only) |

**Positional argument disambiguation:**
- Git URL (starts with `https://`, `http://`, `git@`, `ssh://`, `git://`, or ends with `.git`) → clone repo and publish all discovered skills
- Starts with `.`, `/`, `~`, or is an existing directory → treated as PATH
- Contains `/` but not a directory → treated as SKILL_REF (org/skill)

**Auto-detection:**
- **Name**: from SKILL.md frontmatter `name` field
- **Org**: auto-detected if user belongs to exactly one org
- **Version**: fetches latest from `/v1/skills/{org}/{name}/latest-version`, bumps patch. First publish → `0.1.0`

**Error codes:**
- HTTP 409 → version already exists
- HTTP 422 → Grade F, safety checks failed
- HTTP 503 → server LLM judge not configured

**Output:** Published reference with safety grade (A/B/C). If evals are configured, the CLI automatically attaches to the eval log stream (see `dhub logs`).

**Git repository mode:**

When the first argument is a git URL, publish clones the repo and discovers all skills:

```bash
dhub publish https://github.com/myorg/skills-repo
dhub publish git@github.com:myorg/repo.git --ref main
dhub publish https://github.com/myorg/repo --minor
```

Steps:
1. Clone the repository (shallow, `--depth 1`) into a temporary directory
2. Recursively find all `SKILL.md` files, skipping hidden dirs, `node_modules`, `__pycache__`
3. Validate each `SKILL.md` — only directories with valid frontmatter are included
4. Publish each discovered skill, reading names from SKILL.md frontmatter
5. Clean up the temporary clone

If one skill fails to publish, the remaining skills still get published. A summary is printed at the end: X published, Y skipped, Z failed.

---

## dhub install

Install a skill from the registry.

```
dhub install ORG/SKILL [--version VER] [--agent AGENT] [--allow-risky]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--version`, `-v` | string | `"latest"` | Version spec |
| `--agent` | string | none | Target agent: `claude`, `cursor`, `codex`, `opencode`, `gemini`, or `all` |
| `--allow-risky` | flag | false | Allow installing Grade C skills |

**Steps:**
1. Resolve version via GET `/v1/resolve/{org}/{skill}?spec={version}`
2. Download zip from signed S3 URL
3. Verify SHA-256 checksum
4. Extract to `~/.dhub/skills/{org}/{skill}/`
5. Create agent symlinks if `--agent` specified

**Symlink naming:** `{skill}` in the agent's skill directory.

---

## dhub uninstall

Remove a locally installed skill and all its agent symlinks.

```
dhub uninstall ORG/SKILL
```

Removes:
1. Agent symlinks from all agent directories (claude, cursor, codex, opencode, gemini)
2. The canonical directory at `~/.dhub/skills/{org}/{skill}/`
3. Empty org directory if no other skills remain

---

## dhub list

List all published skills on the registry.

```
dhub list
```

No options. Displays a table with columns: Org, Skill, Version, Updated, Safety (grade), Author, Description.

**Visibility:** Unauthenticated users see only public skills. Authenticated users also see org-private skills from their orgs.

---

## dhub visibility

Change the visibility of a published skill.

```
dhub visibility ORG/SKILL VISIBILITY
```

| Argument | Required | Description |
|----------|----------|-------------|
| `ORG/SKILL` | yes | Skill reference (e.g. `myorg/my-skill`) |
| `VISIBILITY` | yes | `public` or `org` |

Only org admins can change visibility. Set to `org` to make a skill visible only to org members. Set to `public` to make it visible to everyone.

**API:** PUT `/v1/skills/{org}/{skill}/visibility`

**Error codes:**
- HTTP 403 → only org admins can change visibility
- HTTP 404 → skill not found

---

## dhub delete

Delete a skill version (or all versions) from the registry.

```
dhub delete ORG/SKILL [--version VER]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--version`, `-v` | string | none | Specific version to delete. Omit to delete ALL versions (with confirmation prompt). |

**Error codes:**
- HTTP 404 → skill or version not found
- HTTP 403 → no permission to delete

---

## dhub run

Run a locally installed skill using its configured runtime.

```
dhub run ORG/SKILL [-- EXTRA_ARGS...]
```

| Argument | Required | Description |
|----------|----------|-------------|
| `ORG/SKILL` | yes | Installed skill reference |
| `EXTRA_ARGS` | no | Extra arguments passed to the entrypoint script |

**Requirements:**
- Skill must be installed locally
- SKILL.md must have a `runtime` block with `language: python`
- `uv` must be on PATH
- Lockfile must exist (if declared in runtime config)
- Entrypoint file must exist
- Required env vars (from `runtime.env`) must be set

**Execution:**
1. `uv sync --directory {skill_dir}` — install/sync dependencies
2. `uv run --directory {skill_dir} python {entrypoint} [extra_args]` — run the skill
3. Exit code from the entrypoint is propagated

---

## dhub ask

Natural language skill search.

```
dhub ask "QUERY"
```

Searches across all published skills. Returns markdown-formatted results in a Rich panel.

**Visibility:** Unauthenticated users search only public skills. Authenticated users also search org-private skills from their orgs.

**API:** GET `/v1/search?q={query}`

---

## dhub eval-report

View the agent evaluation report for a skill version.

```
dhub eval-report ORG/SKILL@VERSION
```

The `@VERSION` is required. Format: `myorg/my-skill@1.0.0`.

**Output:**
- Agent and judge model used
- Overall status: passed / failed / error / pending
- Pass/fail count
- Per-case results with verdicts and reasoning

**Verdict values:** `pass`, `fail`, `error`
**Stages:** `sandbox` (execution failed), `agent` (non-zero exit), `judge` (LLM evaluation)

---

## dhub logs

View or tail eval run logs in real-time.

```
dhub logs [SKILL_REF] [--follow|-f]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `SKILL_REF` | string | None | Skill ref (org/skill[@version]) or eval run ID |
| `--follow` / `-f` | flag | False | Tail logs in real-time |

**Usage patterns:**
- `dhub logs` — list recent eval runs (table with ID, status, agent, cases, stage)
- `dhub logs org/skill --follow` — tail latest run for the latest version
- `dhub logs org/skill@1.0.0 --follow` — tail latest run for a specific version
- `dhub logs <run-id> --follow` — tail a specific eval run by its UUID

**Log events:**
- `setup` — sandbox provisioning
- `case_start` — case N/M starting
- `log` — agent stdout/stderr (truncated to 200 chars for display)
- `judge_start` — LLM judge invoked
- `case_result` — PASS/FAIL/ERROR with reasoning
- `report` — final summary (passed/total, duration)

**Publish auto-attach:** When publishing a skill with evals, the CLI automatically starts tailing the eval run logs. Press Ctrl-C to detach; re-attach later with `dhub logs <run-id> --follow`.

---

## dhub access grant

Grant an org (or user) access to a private skill.

```
dhub access grant ORG/SKILL GRANTEE
```

| Argument | Required | Description |
|----------|----------|-------------|
| `ORG/SKILL` | yes | Skill reference (e.g. `myorg/my-skill`) |
| `GRANTEE` | yes | Org or user slug to grant access to |

Since every user has a personal org (their username), granting to a user is the same as granting to their personal org.

Only org admins of the owning org can grant access.

**API:** POST `/v1/skills/{org}/{skill}/access`

**Error codes:**
- HTTP 403 → only org admins can manage access
- HTTP 404 → skill or grantee org not found
- HTTP 409 → access already granted

---

## dhub access revoke

Revoke an org's access to a private skill.

```
dhub access revoke ORG/SKILL GRANTEE
```

| Argument | Required | Description |
|----------|----------|-------------|
| `ORG/SKILL` | yes | Skill reference (e.g. `myorg/my-skill`) |
| `GRANTEE` | yes | Org or user slug to revoke access from |

Only org admins of the owning org can revoke access.

**API:** DELETE `/v1/skills/{org}/{skill}/access/{grantee}`

**Error codes:**
- HTTP 403 → only org admins can manage access
- HTTP 404 → skill, grantee org, or grant not found

---

## dhub access list

List all access grants for a private skill.

```
dhub access list ORG/SKILL
```

| Argument | Required | Description |
|----------|----------|-------------|
| `ORG/SKILL` | yes | Skill reference (e.g. `myorg/my-skill`) |

Displays a table with grantee org slug, granted-by username, and date. Only org admins of the owning org can list grants.

**API:** GET `/v1/skills/{org}/{skill}/access`

**Error codes:**
- HTTP 403 → only org admins can view access grants
- HTTP 404 → skill not found

---

## dhub org list

List namespaces you can publish to.

```
dhub org list
```

Shows organization slugs derived from your GitHub account and org memberships.

---

## dhub config default-org

Set the default namespace for publishing so you don't have to specify it each time.

```
dhub config default-org
```

Interactive — prompts you to choose from your available namespaces. The selection is saved to `~/.dhub/config.{env}.json`.

---

## dhub keys add

Store an API key for agent evaluations.

```
dhub keys add KEY_NAME
```

Prompts securely for the key value (hidden input). Keys are stored server-side (encrypted) and injected into eval sandbox environments.

**Error:** HTTP 409 if key name already exists. Remove it first with `dhub keys remove`.

---

## dhub keys list

List stored API key names.

```
dhub keys list
```

Displays a table with key names and creation dates. Does not show key values.

---

## dhub keys remove

Remove a stored API key.

```
dhub keys remove KEY_NAME
```

**Error:** HTTP 404 if key name not found.

---

## dhub track add

Track a GitHub repo for automatic skill updates.

```
dhub track add REPO_URL [--branch BRANCH] [--interval MINUTES]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `REPO_URL` | string | required | GitHub repo URL (HTTPS or SSH) |
| `--branch`, `-b` | string | `main` | Branch to track |
| `--interval`, `-i` | int | `60` | Poll interval in minutes (minimum 5) |

Creates a server-side tracker that polls the GitHub API for new commits. When changes are detected, all skills in the repo are automatically republished through the full pipeline (gauntlet + version bump + upload).

**Private repos:** To track a private repo, first store a GitHub personal access token via `dhub keys add GITHUB_TOKEN`. The tracker uses it for both API calls and cloning. Falls back to a system-wide token if configured, or unauthenticated access for public repos.

**Version resolution:** If a tracked skill's SKILL.md declares `version: X.Y.Z` and it's higher than the latest published version, that version is used. Otherwise, the latest version is patch-bumped automatically.

**Error codes:**
- HTTP 409 → tracker for this repo/branch already exists
- HTTP 422 → invalid GitHub URL or interval < 5 minutes

---

## dhub track list

List all active skill trackers.

```
dhub track list
```

Displays a table with: ID, repo URL, branch, org, interval, enabled status, last checked/published times, and errors.

---

## dhub track status

Show detailed status of a tracker.

```
dhub track status ID
```

| Argument | Required | Description |
|----------|----------|-------------|
| `ID` | yes | Tracker ID or prefix (minimum unique prefix) |

---

## dhub track pause

Pause a tracker (stop checking for updates).

```
dhub track pause ID
```

---

## dhub track resume

Resume a paused tracker.

```
dhub track resume ID
```

---

## dhub track remove

Remove a tracker.

```
dhub track remove ID
```

---

## dhub --version

Show the installed CLI version.

```
dhub --version
dhub -V
```

---

## Global Behavior

**Timeouts:** All HTTP requests use 60-second timeouts to handle Modal cold starts.

**Headers:** Every request includes:
- `X-DHub-Client-Version: {version}` — CLI version for compatibility checking
- `Authorization: Bearer {token}` — when authenticated

**Environment:** `DHUB_ENV` controls dev/prod. `DHUB_API_URL` overrides the API URL entirely.

**Config priority:**
1. `DHUB_API_URL` env var (highest)
2. Saved config file (`~/.dhub/config.{env}.json`)
3. Default URL for environment
