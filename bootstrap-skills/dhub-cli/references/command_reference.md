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
dhub publish [SKILL_REF] [PATH] [--version VER] [--patch] [--minor] [--major] [--private]
```

| Argument/Option | Required | Default | Description |
|----------------|----------|---------|-------------|
| `SKILL_REF` | no | auto-detect from SKILL.md | Org/skill reference (e.g. `myorg/my-skill`) |
| `PATH` | no | `.` | Path to skill directory |
| `--version` | no | auto-bump | Explicit semver (e.g. `1.2.3`) |
| `--patch` | no | true (default bump) | Bump patch version |
| `--minor` | no | false | Bump minor version |
| `--major` | no | false | Bump major version |
| `--private` | no | false | Publish as org-private (visible only to org members) |

**Positional argument disambiguation:**
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

**Output:** Published reference with safety grade (A/B/C). If evals are configured, reports "evaluation running in background."

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

**Symlink naming:** `{org}--{skill}` in the agent's skill directory.

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

## dhub org list

List namespaces you can publish to.

```
dhub org list
```

Shows organization slugs derived from your GitHub account and org memberships.

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
