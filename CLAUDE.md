
## Project Overview

### Workspace Structure

This is a **uv workspace monorepo** with four components:

- **`client/`** — `dhub-cli` package (open-source CLI, published to PyPI) — import path: `dhub.*`
- **`server/`** — `decision-hub-server` package (private backend, deployed on Modal) — import path: `decision_hub.*`
- **`shared/`** — `dhub-core` package (shared domain models and SKILL.md manifest parsing) — import path: `dhub_core.*`
- **`frontend/`** — React + TypeScript web UI (bundled into the server at deploy time, not a uv workspace member)

`shared/` is the single source of truth for data models (`SkillManifest`, `RuntimeConfig`, etc.) and manifest parsing. Both client and server depend on it — never duplicate these definitions.

### Tech Stack

**Backend (Python 3.11+):**
- **FastAPI** for REST API (server)
- **Typer + Rich** for CLI (client)
- **Pydantic** for data validation and settings
- **Gemini** for LLM (search, classification, gauntlet safety analysis)
- **Anthropic** for LLM (eval judging)
- **boto3** for S3 access
- **loguru** for server logging

**Frontend:**
- **React 19** with TypeScript
- **Vite** for bundling and dev server
- **React Router** for routing

**Important**: Always use `uv run` to execute Python code, not `python` directly.

## Development Setup

### Environments (Dev / Prod / Local)

The project has three environments controlled by `DHUB_ENV` (`dev` | `prod` | `local`). The server defaults to `dev` for safety; the CLI defaults to `prod` for end users.

**Always work against dev unless explicitly told to use prod.** Prefix all CLI, server, and deploy commands with `DHUB_ENV=dev`:

```bash
DHUB_ENV=dev dhub list                          # CLI against dev
DHUB_ENV=dev modal deploy modal_app.py          # deploy dev Modal app (from server/)
DHUB_ENV=dev uv run --package decision-hub-server uvicorn ...  # local dev server
```

- **Dev**: `https://hub-dev.decision.ai`, config at `~/.dhub/config.dev.json`, env file `server/.env.dev`
- **Prod**: `https://hub.decision.ai`, config at `~/.dhub/config.prod.json`, env file `server/.env.prod`
- **Local**: `http://localhost:5173`, env file `server/.env.local`, infra via `docker-compose-local.yml` (Postgres + MinIO). Requires Docker Desktop. Evals spawn to the deployed dev Modal app. When asked to deploy locally, run `make deploy-local` in the background (`run_in_background: true`).

**Working directory caveat**: Always run server-package commands from `server/`. The server's `.env.dev` / `.env.prod` files live in `server/` and `pydantic-settings` resolves them relative to the current working directory. Running from the repo root will fail with missing settings errors.

```bash
# Correct
cd server && DHUB_ENV=dev uv run --package decision-hub-server python -c "..."
cd server && DHUB_ENV=dev modal deploy modal_app.py

# Wrong — .env.dev not found
DHUB_ENV=dev uv run --package decision-hub-server python -c "..."
```

Client-package commands (`uv run --package dhub-cli ...`) can run from anywhere.

### Quick Reference

Common commands are available via `make`. Read the `Makefile` to see all targets. **Always read the `Makefile`** for available targets and their exact recipes — do not hardcode or memorize commands that the Makefile already provides.

**Important**: Always run `make` from the **repo root** (where the `Makefile` lives). If your working directory has drifted (e.g. into `server/`), use `make -C /path/to/repo-root <target>` to avoid "No rule to make target" errors.

Install pre-commit hooks once after cloning: `make install-hooks`.

### Crawler

Discovers GitHub repos containing `SKILL.md` files and publishes them through the gauntlet pipeline via Modal. Run from `server/`:

```bash
# Crawl up to 100 skills on dev (use a single fast strategy)
cd server && DHUB_ENV=dev uv run --package decision-hub-server \
  python -m decision_hub.scripts.github_crawler \
  --max-skills 100 --strategies size --github-token "$(gh auth token)"

# Full discovery (all 5 strategies — slow, ~15 min due to rate limits)
cd server && DHUB_ENV=dev uv run --package decision-hub-server \
  python -m decision_hub.scripts.github_crawler \
  --github-token "$(gh auth token)"

# Resume from checkpoint (skip discovery, go straight to processing)
cd server && DHUB_ENV=dev uv run --package decision-hub-server \
  python -m decision_hub.scripts.github_crawler \
  --resume --github-token "$(gh auth token)"

# Process specific repos (skip discovery)
cd server && DHUB_ENV=dev uv run --package decision-hub-server \
  python -m decision_hub.scripts.github_crawler \
  --repos git@github.com:machina-sports/sports-skills.git owner/repo \
  --github-token "$(gh auth token)"

# Dry-run (discovery only, no processing)
cd server && DHUB_ENV=dev uv run --package decision-hub-server \
  python -m decision_hub.scripts.github_crawler --dry-run
```

**Key flags:** `--max-skills N` (stop after N published), `--strategies size|path|topic|fork|curated` (pick subset), `--fresh` (delete checkpoint), `--resume` (skip discovery), `--repos REPO [REPO ...]` (process specific repos, accepts `owner/repo`, HTTPS, or SSH URLs). A GitHub token is required — unauthenticated rate limit is only 60 req/hr.

## Code Standards

### Design Principles & Conventions

- **Frozen dataclasses** for immutable data models
- **Pure functions over classes** — use modules to group related functions
- **Single responsibility**: Small, single-purpose functions with one clear reason to change
- **Clear interfaces**: Descriptive names, type hints, explicit signatures — obvious inputs, outputs, and behavior
- **Domain/infrastructure separation**: Keep business logic independent from frameworks, I/O, databases. UI, persistence, and external services are replaceable adapters around a clean core
- **Testing as design**: Design for fast, focused unit tests. Pure functions and small units guide architecture
- **Readability over cleverness**: Straightforward, idiomatic Python over opaque tricks. Follow PEP 8
- **YAGNI**: No abstractions or features "just in case" — add complexity only for concrete needs
- **Continuous refactoring**: Ship the simplest thing that works, refactor as requirements evolve. Routine maintenance, not heroic effort
- **Don't worship backward compatibility**: Don't freeze bad designs to avoid breaking changes. Provide clear migration paths instead of stacking hacks
- **DRY**: Do not repeat yourself — ensure each piece of logic has a single, clear, authoritative implementation instead of being duplicated across the codebase
- **Comments**: Explain business logic, assumptions, and choices — not the code verbatim
- **Isolate side operations**: When a non-critical operation (metadata sync, analytics, notifications) runs alongside a critical path, always (1) wrap it in try/except so failures don't block the main flow, and (2) if it uses a separate DB connection, commit pending writes first so they're visible
- **Reset state on context changes (React)**: When a component holds local state (`useState`, `useRef`) and receives changing inputs (URL params, props), audit which state becomes stale and add `useEffect(() => reset(), [key])` or use a `key=` prop to force remount
- **SQL query correctness**: Every query with `LIMIT` must have an explicit `ORDER BY` with a unique tiebreaker, and every field in `SELECT` must appear in the returned response dict
- **Sanitize subprocess credentials**: Never pass secrets (tokens, keys) in subprocess command arguments; catch `TimeoutExpired` and `CalledProcessError` and raise sanitized errors that strip credentials
- **Use server totals, not local array length**: After introducing pagination, never use `.length` of a local array as a display count — always use the server's `total` field
- **Don't advance state on failure**: For every state-advancing side effect (advancing cursors, clearing errors, updating timestamps), explicitly handle the failure case — do not advance state when the operation it represents has failed
- **Clean up after refactors**: After every refactor, search for all references to the old function/argument and remove dead code — no orphaned functions, unused imports, or selected-but-unmapped fields
- **Mobile-first frontend**: Design and test all UI changes for mobile viewports first (target ~400px, e.g. iPhone 17 Pro). Use CSS Modules media queries at `480px` and `768px` breakpoints. Every new page/component must include responsive styles — never ship desktop-only layouts
- **Consistent font scale**: The site uses CSS custom properties for a fixed typographic scale (base 18px), defined in `frontend/src/index.css` `:root`. Always use these variables — never hardcode `rem` font sizes: `--text-hero` (4rem, hero headline), `--text-display` (2.5rem, large accent), `--text-title` (2rem, detail page titles), `--text-heading` (1.6rem, listing page titles), `--text-lg` (1.3rem, section headings), `--text-body` (1.1rem, body text/descriptions), `--text-sm` (0.9rem, secondary labels/nav), `--text-xs` (0.8rem, metadata/buttons), `--text-xxs` (0.7rem, badges/tiny labels). Mobile (480px) steps down one level (e.g. `--text-title` → `--text-heading`). Never eyeball new sizes — always use the scale variables
- **Batch scripts must be incremental, parallelizable, and resumable**: Backfills and long-running data operations must (1) save results incrementally (flush to DB in batches as work completes, not all at the end), (2) parallelize the expensive work (ThreadPoolExecutor for S3/LLM, single connection for DB writes), and (3) support `--resume` to skip already-processed items after a crash
- **Keep the ask pipeline in sync with skill metadata**: The `_SKILL_SUMMARY_COLUMNS` list in `database.py` is the single source of truth for which columns appear in skill list and search queries. `_row_to_skill_summary()` uses `row._mapping` to automatically capture all selected columns, so adding a column to `_SKILL_SUMMARY_COLUMNS` makes it available in both `fetch_all_skills_for_index` and `search_skills_hybrid` without manual dict updates. However, to surface a new column to the ask LLM and API consumers, you must also update: (1) `SkillIndexEntry` in `models.py`, (2) `build_index_entry()` and `serialize_index()` in `domain/search.py`, (3) `AskSkillRef` in `search_routes.py` + both enrichment paths (main + fallback), (4) frontend `AskSkillRef` in `types/api.ts` and `AskModal.tsx`

### Logging

The server uses **loguru** (`from loguru import logger`). The client does not — it uses Rich console output directly. Logging is configured once at startup via `setup_logging()` in `decision_hub.logging`. Log level is controlled by `LOG_LEVEL` in `server/.env.dev` / `.env.prod` (default: `INFO`). All output goes to **stderr** — no log files. A `RequestLoggingMiddleware` assigns an 8-char request ID to every HTTP request for correlation.

**Use `{}` placeholders, not f-strings** — loguru defers evaluation so arguments are only computed when the level is active:

```python
logger.info("Publishing {}/{} version={}", org_slug, skill_name, version_id)
```

**Use `logger.opt(exception=True)`** to attach tracebacks — don't format exceptions into the message string.

**Log in API/infra layers, not in domain functions.** Domain functions return values or raise — the caller decides what to log.

**Include greppable identifiers** (org, skill, case name, status code) — not just human prose.

### Rate Limiting & DOS Protection

Public endpoints use in-memory per-IP sliding-window rate limiters (see `rate_limit.py`). Limiters are lazily initialized on `app.state` from settings. Limits are per-container (not shared across Modal replicas). Defaults and setting names are defined in `server/src/decision_hub/settings.py` (`*_rate_limit` / `*_rate_window` fields). Enforcement functions (`_enforce_*_rate_limit`) live alongside their routes in `server/src/decision_hub/api/registry_routes.py` and `search_routes.py`.

All DB queries have a 30s `statement_timeout` (set in engine `connect_args` in `database.py`). Query parameters on public endpoints have `max_length` constraints to prevent oversized payloads reaching the DB or LLM APIs.

When adding new public endpoints, always add a rate limiter following the existing pattern: define a `_enforce_*_rate_limit` dependency, add settings in `settings.py`, and wire it via `dependencies=[Depends(...)]`.

## Quality Gates

### Linting & Formatting

The project uses **ruff** for linting and formatting, and **mypy** for type checking, both configured in the root `pyproject.toml`. Pre-commit hooks run ruff automatically on every commit (install once with `make install-hooks`). Mypy runs in CI only (not pre-commit). See `make help` for lint, format, and typecheck targets.

### Testing

Use `pytest` with fixtures in `conftest.py`. Mock external services (S3, Gemini, Anthropic, Database) in tests. See `make help` for test targets (all, client, server, frontend).

### CI

GitHub Actions runs on every PR to `main`:
- **lint**: ruff check + format
- **typecheck**: mypy type checks
- **test-client**: client pytest suite
- **test-server**: server pytest suite
- **test-frontend**: frontend vitest suite
- **lint-frontend**: TypeScript type check + ESLint
- **check-migrations**: validates migration filename formats and detects duplicates
- **migrate-check**: replays all SQL migrations from scratch against a fresh Postgres (CI only)
- **schema-drift**: detects differences between SQL migrations and SQLAlchemy metadata (CI only)

## Database Migrations

Migrations are tracked SQL files in `server/migrations/`. The runner (`scripts/run_migrations.py`) records each applied file in a `schema_migrations` table so migrations are never re-applied.

### Running migrations

Use the migrate targets from the `Makefile`. Migrations are also applied automatically during deploys (`scripts/deploy.sh`).

### Creating a new migration

**Naming**: Use timestamp-based filenames to avoid collisions between parallel branches. **Always generate the timestamp from the actual current time** — never invent a round number like `120000`:

```bash
# Generate the filename prefix:
date +%Y%m%d_%H%M%S
# Example output: 20260212_163047
```

```
YYYYMMDD_HHMMSS_description.sql
```

Example: `20260212_163047_add_user_email.sql`

Legacy files use 3-digit numeric prefixes (`001_` through `011_`). Do not add new files with numeric prefixes.

### Hard rules for AI agents

- **Never use `metadata.create_all()`** to apply schema changes. Always write a SQL migration file.
- **Never edit or delete existing migration files.** They represent immutable history. Fix mistakes with a new migration.
- **Always update both** the SQL migration file and the SQLAlchemy table definition in `database.py` when changing the schema. CI will catch drift.
- **Use `IF NOT EXISTS` / `IF EXISTS`** in DDL when possible for idempotency (especially for `CREATE TABLE`, `ADD COLUMN`).
- **Keep migration PRs focused.** Prefer multiple small PRs over one large one.
- **Test locally** before pushing: use the migration-related targets from the `Makefile` to validate filenames and apply to dev.
- **`created_at` and `updated_at` are managed by PostgreSQL.** `created_at` uses a `DEFAULT now()` server default on insert. `updated_at` is set by a `BEFORE UPDATE` trigger (`set_updated_at()`). Never set either in application code. New mutable tables must include both columns and a `BEFORE UPDATE` trigger for `updated_at`.
- **Always enable RLS on new tables.** Every `CREATE TABLE` migration must include `ALTER TABLE <name> ENABLE ROW LEVEL SECURITY;`. This blocks Supabase PostgREST (anon/authenticated roles) from querying tables directly — all data access must go through the FastAPI API layer. The backend connects as the table owner, which bypasses RLS automatically.

## Rules for AI Agents

### Dev deploy
You **may** deploy to dev when asked. Always use `make deploy-dev` — never bare `modal deploy` (it skips the frontend build).

### Forbidden file modifications
- Never modify `.env.prod` or `.env.dev` — these contain production configuration. The only exception is `MIN_CLI_VERSION`, which you may bump when removing or breaking CLI-facing endpoints.
- Never modify `.github/workflows/` without explicit instructions

### Before starting work
- **Search for existing implementations** before writing new code (`grep`, `glob`, check `shared/src/`)
- **Check open PRs** for overlapping work: `gh pr list --state open`
- **Link to a GitHub issue.** If no issue exists, create one first.

### Never block the conversation on long waits
When monitoring long-running processes (crawlers, deploys, Modal logs), **never use `sleep` inside a tool call**. A `sleep 900` blocks the entire conversation for 15 minutes and makes the agent appear stuck. Instead:

- **Run long commands in background** (`run_in_background: true`) and check output with `tail` in a separate non-blocking call
- **Poll with short timeouts** — use quick DB count queries or `ps` checks, not embedded sleeps
- **Let the user drive timing** — report current status and let them decide when to check again, rather than silently waiting
- **For periodic monitoring**, write a small background script that appends status to a file, then read that file on demand

### Resolving PR review comments
When fixing PR review comments, always complete **all three steps**:
1. **Fix the code** and push the commit
2. **Reply** to each comment explaining the fix
3. **Resolve the thread** via GraphQL: `gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "THREAD_ID"}) { thread { isResolved } } }'`

To get unresolved thread IDs: `gh api graphql -f query='{ repository(owner: "pymc-labs", name: "decision-hub") { pullRequest(number: PR_NUM) { reviewThreads(first: 50) { nodes { id isResolved comments(first: 1) { nodes { body author { login } } } } } } } }' --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false) | {id, body: .comments.nodes[0].body[:80]}'`

### Code review workflow

When reviewing code (PRs, refactors, or when explicitly asked), evaluate these four dimensions:

1. **Architecture** — Component boundaries, coupling, data flow, scaling characteristics, security boundaries (auth, data access, API surface).
2. **Code quality** — DRY violations (flag aggressively), error handling gaps and missing edge cases, over- or under-engineering relative to the task, technical debt hotspots.
3. **Test coverage** — Unit/integration/e2e gaps, weak assertions, untested error paths and failure modes, missing edge case coverage.
4. **Performance** — N+1 queries and DB access patterns, memory concerns, caching opportunities, high-complexity code paths.

**Decision-making protocol for non-trivial changes:** When a review finding or implementation choice has multiple valid approaches, do not assume a direction. Instead: (1) describe the problem concretely with file and line references, (2) present 2-3 options including "do nothing" where reasonable, with effort/risk/maintenance tradeoffs for each, (3) give an opinionated recommendation with rationale, and (4) ask for input before proceeding.

## Releases & Deployment

### CLI Versioning & Release

#### Semver guidelines

- **Patch** (`0.5.0` → `0.5.1`): Bug fixes, internal refactors. Nothing new for the user, nothing breaks.
- **Minor** (`0.5.0` → `0.6.0`): New features — new commands, new flags, new output. Old CLI still works with the server.
- **Major** (`0.5.0` → `1.0.0`): Breaking changes — old CLI **can't talk to the server anymore** (changed URLs, new required fields, removed endpoints). Requires server redeploy.

#### Release commands

Use the `publish-cli` target from the `Makefile`. Supports `BUMP=patch|minor|major` and `BREAKING=1` to sync servers.

#### How it works

The server enforces a minimum CLI version via `MIN_CLI_VERSION` in `server/.env.dev` and `server/.env.prod`. The `.env` file is baked into the Modal image at deploy time, so a server redeploy is all that's needed. When `BREAKING=1` is passed, the script updates MIN_CLI_VERSION in both env files and redeploys both servers.

Every CLI publish automatically creates a `cli/vX.Y.Z` git tag, and every prod deploy creates a `prod/YYYYMMDD-HHMMSS` tag. GitHub Actions generates release notes from merged PRs when these tags are pushed.

### Deployment

Use the deploy targets from the `Makefile`. The deploy script builds the React frontend (`frontend/dist/`) and bundles it into the Modal container alongside the server.

#### Dev deploys

Dev deploys are manual via `make deploy-dev`. The `.env.dev` file is baked into the Modal image at deploy time, so all secrets live in that single file — no Modal secrets or GitHub Environment needed.

#### Prod deploys

Both dev and prod deploys require the corresponding `.env` file on the deployer's machine (`server/.env.dev` or `server/.env.prod`). Rotating secrets requires updating the `.env` file and redeploying.

`make deploy-prod` auto-tags `prod/YYYYMMDD-HHMMSS` and pushes the tag, which triggers `release-notes.yml` to create a GitHub Release with auto-generated notes from merged PRs. To see what's in prod: `git tag --list 'prod/*' --sort=-version:refname | head -5`.

## Keeping Docs in Sync

After implementing significant changes, check whether these need updating:
- **`README.md`** — new/changed CLI commands, API endpoints, features, setup requirements, or architecture
- **`bootstrap-skills/dhub-cli/SKILL.md`** and **`bootstrap-skills/dhub-cli/references/command_reference.md`** — new/changed CLI commands, flags, or behavior

## Data Maintenance

Use the `backfill` target from the `Makefile` to run all backfills (categories, embeddings, org metadata). Defaults to dev; override with `DHUB_ENV=prod`. Individual backfill scripts can also be run directly from `server/` — see `server/scripts/backfill_categories.py` and `server/src/decision_hub/scripts/backfill_embeddings.py`.

## Monitoring Trackers

Trackers (`skill_trackers` table) poll GitHub repos for new commits and republish changed skills. Trackers are created automatically when publishing from a GitHub URL (`dhub publish --track`, enabled by default) or via the API (`POST /v1/trackers`).

**Key source files:**
- Cron schedule & fan-out: `server/modal_app.py` (`check_trackers`, `tracker_process_repo`)
- Orchestration & republish logic: `server/src/decision_hub/domain/tracker_service.py`
- CRUD routes: `server/src/decision_hub/api/tracker_routes.py`
- DB table & queries: `server/src/decision_hub/infra/database.py` (search `skill_trackers`)
- Settings (batch size, jitter, rate-limit floor): `server/src/decision_hub/settings.py` (search `tracker_`)

### GitHub App Authentication

Trackers authenticate to GitHub using **GitHub App installation tokens** instead of a personal access token (PAT). Each cron tick / Modal container mints its own short-lived token (~1 hr) from the App's private key. This gives dev and prod independent 12,500 req/hr rate-limit budgets.

**Apps:** App IDs, Installation IDs, and PEM keys are stored inline in `server/.env.dev` and `server/.env.prod` (git-ignored). The PEM is embedded as a multi-line quoted value (`GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA..."`). Original PEM files are also kept at `server/decision-hub-dev.*.pem` / `server/decision-hub.*.pem` (git-ignored).

**Note:** The crawler and backfill scripts still use a PAT passed via `--github-token`. Only the tracker cron uses App tokens.

**Quick health check:** Use the `tracker-health` target from the `Makefile`. Defaults to dev; override with `DHUB_ENV=prod`.

**Check Modal logs for failures:**
```bash
modal app logs decision-hub 2>&1 | grep -i "tracker\|check_trackers"     # prod
modal app logs decision-hub-dev 2>&1 | grep -i "tracker\|check_trackers"  # dev
```

**Query tracker health in DB:**
```sql
-- Failed trackers
SELECT repo_url, last_checked_at, last_error
FROM skill_trackers WHERE last_error IS NOT NULL AND enabled = true;
```

### Tracker Metrics

The `tracker_metrics` table records one row per `check_trackers` cron tick with key counters for historical observability. Metrics are written at the end of each cron invocation.

**Useful queries:**
```sql
-- Recent cron ticks (last 24h)
SELECT recorded_at, total_checked, trackers_changed, trackers_failed,
       github_rate_remaining, batch_duration_seconds
FROM tracker_metrics
WHERE recorded_at > now() - interval '24 hours'
ORDER BY recorded_at DESC;

-- Average duration and failure rate over last 7 days
SELECT date_trunc('day', recorded_at) AS day,
       count(*) AS ticks,
       avg(batch_duration_seconds)::numeric(5,1) AS avg_dur_s,
       sum(trackers_failed) AS total_failed
FROM tracker_metrics
WHERE recorded_at > now() - interval '7 days'
GROUP BY 1 ORDER BY 1 DESC;
```

## Troubleshooting

### Modal Cold Starts

Modal containers spin down after inactivity. The first HTTP request after a cold start can take 30-60 seconds. Always use `timeout=60` (or higher) when making HTTP requests to Modal endpoints. Do NOT use default timeouts — they will fail on cold starts.

### Inspecting Logs

```bash
# Stream live logs from Modal
modal app logs decision-hub          # prod
modal app logs decision-hub-dev      # dev

# Filter by request ID to trace a single request
modal app logs decision-hub-dev 2>&1 | grep "a1b2c3d4"
```

### Debugging Modal Sandboxes

When eval pipelines fail or hang, **do not** blindly poll the eval-report endpoint. Spin up a sandbox interactively and test each step in isolation:

```python
# From server/ directory:
# DHUB_ENV=dev uv run --package decision-hub-server python3 -c "..."

import modal
from decision_hub.infra.modal_client import build_eval_image, AGENT_CONFIGS

config = AGENT_CONFIGS['claude']
image = build_eval_image(config)
app = modal.App.lookup('decision-hub-eval', create_if_missing=True)
sb = modal.Sandbox.create(image=image, app=app, timeout=120)

# 1. Verify the agent binary
proc = sb.exec('which', 'claude'); proc.wait()
print(proc.stdout.read())

# 2. Run agent with output to file (avoids I/O blocking)
proc = sb.exec('bash', '-c',
    'nohup claude -p --dangerously-skip-permissions "Say hi" '
    '> /tmp/out.txt 2>/tmp/err.txt &')
proc.wait()

import time; time.sleep(15)

# 3. Read stdout AND stderr
proc = sb.exec('bash', '-c',
    'echo STDOUT: && cat /tmp/out.txt '
    '&& echo STDERR: && cat /tmp/err.txt')
proc.wait()
print(proc.stdout.read())

sb.terminate()
```

**Common issues:**
- **Exit 137 near the timeout duration** = sandbox timeout kill, not OOM. Correlate duration with the configured timeout.
- **Exit 137 well before timeout** = actual OOM. Increase `memory` in `Sandbox.create`.
- **`Invalid API key`** = stored `ANTHROPIC_API_KEY` expired/revoked. Claude Code hangs waiting for user input. Verify the key directly: `httpx.post('https://api.anthropic.com/v1/messages', headers={'x-api-key': key, 'anthropic-version': '2023-06-01'}, ...)`
- **`--dangerously-skip-permissions cannot be used with root`** = the sandbox image creates a `sandbox` user; agent commands must run via `sudo -E -u sandbox`.
- **Zero stdout from agent** = always check stderr. Use `nohup` + file redirect and inspect after a few seconds instead of waiting for the full timeout.
