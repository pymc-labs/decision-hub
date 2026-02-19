
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
- **OpenAI** for LLM
- **boto3** for S3 access
- **loguru** for server logging

**Frontend:**
- **React 19** with TypeScript
- **Vite** for bundling and dev server
- **React Router** for routing

**Important**: Always use `uv run` to execute Python code, not `python` directly.

## Development Setup

### Environments (Dev / Prod)

The project has two independent stacks controlled by `DHUB_ENV` (`dev` | `prod`). The server defaults to `dev` for safety; the CLI defaults to `prod` for end users.

**Always work against dev unless explicitly told to use prod.** Prefix all CLI, server, and deploy commands with `DHUB_ENV=dev`:

```bash
DHUB_ENV=dev dhub list                          # CLI against dev
DHUB_ENV=dev modal deploy modal_app.py          # deploy dev Modal app (from server/)
DHUB_ENV=dev uv run --package decision-hub-server uvicorn ...  # local dev server
```

- **Dev**: `https://pymc-labs--api-dev.modal.run`, config at `~/.dhub/config.dev.json`, env file `server/.env.dev`
- **Prod**: `https://pymc-labs--api.modal.run`, config at `~/.dhub/config.prod.json`, env file `server/.env.prod`

**Working directory caveat**: Always run server-package commands from `server/`. The server's `.env.dev` / `.env.prod` files live in `server/` and `pydantic-settings` resolves them relative to the current working directory. Running from the repo root will fail with missing settings errors.

```bash
# Correct
cd server && DHUB_ENV=dev uv run --package decision-hub-server python -c "..."
cd server && DHUB_ENV=dev modal deploy modal_app.py

# Wrong — .env.dev not found
DHUB_ENV=dev uv run --package decision-hub-server python -c "..."
```

Client-package commands (`uv run --package dhub-cli ...`) can run from anywhere.

### Security Prompts Config

Security-sensitive LLM prompts (gauntlet judges, topicality guard) live outside of source code so they won't be exposed when the repo is open-sourced. Two files in `server/src/decision_hub/infra/`:

| File | Committed? | Purpose |
|------|-----------|---------|
| `security_prompts.yaml` | No (`.gitignore`d) | Plaintext config loaded at runtime by `load_security_prompts()` |
| `security_prompts.example.yaml` | Yes | Simplified example so contributors can run tests without the real prompts |

- **pymc-labs devs**: Get the production config from 1Password ("Decision Hub Security Prompts") and place it at the path above.
- **Open-source contributors**: `make test-server` auto-copies the example config. No production file needed.
- **Deploys**: `make deploy-dev/prod` requires the plaintext `.yaml` — the deploy script checks and fails with a clear error if missing.

### Quick Reference

Common commands are available via `make`. Run `make help` to see all targets.

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
- **Consistent font scale**: The site uses a fixed typographic scale (base 17px). When creating or editing pages, match the established sizes from HomePage: page titles `2rem` (detail) / `1.6rem` (listing), section headings `1.3rem`, body/descriptions `1.05rem`, secondary labels `0.9rem`, small metadata `0.8rem`. Mobile (480px) reduces by ~15–20%. Never eyeball new sizes — always reference existing pages for consistency
- **Security-sensitive LLM prompts** must be defined in `security_prompts.yaml` (`server/src/decision_hub/infra/`), never inline in source code. This includes any prompt that serves as a security guardrail, safety judge, or abuse filter (gauntlet checks, topicality guard, future defenses). Use `load_security_prompts()` from `security_prompts.py` to load them. When adding new LLM calls with a security/defense purpose, always add their prompts to this config.

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

Public endpoints use in-memory per-IP sliding-window rate limiters (see `rate_limit.py`). Limiters are lazily initialized on `app.state` from settings. Limits are per-container (not shared across Modal replicas).

| Endpoint | Setting prefix | Default |
|---|---|---|
| `GET /v1/search` | `search_rate_*` | 20 req/60s |
| `GET /v1/skills` | `list_skills_rate_*` | 120 req/60s |
| `GET /v1/resolve/{org}/{skill}` | `resolve_rate_*` | 60 req/60s |
| `GET /v1/skills/{org}/{skill}/download` | `download_rate_*` | 20 req/60s |

All DB queries have a 30s `statement_timeout` (set in engine `connect_args` in `database.py`). Query parameters on public endpoints have `max_length` constraints to prevent oversized payloads reaching the DB or LLM APIs.

When adding new public endpoints, always add a rate limiter following the existing pattern: define a `_enforce_*_rate_limit` dependency, add settings in `settings.py`, and wire it via `dependencies=[Depends(...)]`.

## Quality Gates

### Linting & Formatting

The project uses **ruff** for linting and formatting, and **mypy** for type checking, both configured in the root `pyproject.toml`. Pre-commit hooks run ruff automatically on every commit (install once with `make install-hooks`). Mypy runs in CI only (not pre-commit).

```bash
make lint       # check only (CI runs this)
make typecheck  # mypy type checks (CI runs this)
make fmt        # auto-fix + format
```

### Testing

Use `pytest` with fixtures in `conftest.py`. Mock external services (S3, OpenAI, Database) in tests.

```bash
make test              # all tests
make test-client       # client only
make test-server       # server only
make test-frontend     # frontend only
```

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

```bash
make migrate-dev     # apply pending migrations to dev
make migrate-prod    # apply pending migrations to prod (use with care)
```

Migrations are also applied automatically during deploys (`scripts/deploy.sh`).

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
- **Test locally** before pushing: `make check-migrations` validates filenames, `make migrate-dev` applies to dev.
- **`created_at` and `updated_at` are managed by PostgreSQL.** `created_at` uses a `DEFAULT now()` server default on insert. `updated_at` is set by a `BEFORE UPDATE` trigger (`set_updated_at()`). Never set either in application code. New mutable tables must include both columns and a `BEFORE UPDATE` trigger for `updated_at`.
- **Always enable RLS on new tables.** Every `CREATE TABLE` migration must include `ALTER TABLE <name> ENABLE ROW LEVEL SECURITY;`. This blocks Supabase PostgREST (anon/authenticated roles) from querying tables directly — all data access must go through the FastAPI API layer. The backend connects as the table owner, which bypasses RLS automatically.

## Rules for AI Agents

### Dev deploy
You **may** deploy to dev when asked. Always use `make deploy-dev` — never bare `modal deploy` (it skips the frontend build).

### Forbidden file modifications
- Never modify `.env.prod` or `.env.dev` — these contain production configuration
- Never modify `.github/workflows/` without explicit instructions

### Before starting work
- **Search for existing implementations** before writing new code (`grep`, `glob`, check `shared/src/`)
- **Check open PRs** for overlapping work: `gh pr list --state open`
- **Link to a GitHub issue.** If no issue exists, create one first.

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

```bash
make publish-cli                          # patch bump, publish to PyPI
make publish-cli BUMP=minor               # minor bump, publish to PyPI
make publish-cli BUMP=major BREAKING=1    # major bump + update MIN_CLI_VERSION + redeploy servers
```

#### How it works

The server enforces a minimum CLI version via `MIN_CLI_VERSION` in `server/.env.dev` and `server/.env.prod`. The `modal_app.py` reads this value at deploy time and injects it into the container, so a server redeploy is all that's needed — no manual Modal secret updates required. When `BREAKING=1` is passed, the script updates MIN_CLI_VERSION in both env files and redeploys both servers.

Every CLI publish automatically creates a `cli/vX.Y.Z` git tag, and every prod deploy creates a `prod/YYYYMMDD-HHMMSS` tag. GitHub Actions generates release notes from merged PRs when these tags are pushed.

### Deployment

```bash
make deploy-dev    # build frontend + deploy to dev Modal
make deploy-prod   # build frontend + deploy to prod Modal
```

The deploy script builds the React frontend (`frontend/dist/`) and bundles it into the Modal container alongside the server.

#### Dev auto-deploy

Merging to `main` auto-deploys dev via `.github/workflows/deploy-dev.yml` — no manual step needed. The workflow uses the `dev` GitHub Environment (secrets: `DATABASE_URL`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`; variable: `MIN_CLI_VERSION_DEV`).

`modal_app.py:_read_env_value()` checks `os.environ` before the local `.env` file. This is how the CI workflow passes `MIN_CLI_VERSION` without a `.env` file present. If you add new deploy-time config that the workflow needs, pass it as an env var in `deploy-dev.yml` and read it via `_read_env_value()`.

#### Prod deploys are manual-only

`make deploy-prod` auto-tags `prod/YYYYMMDD-HHMMSS` and pushes the tag, which triggers `release-notes.yml` to create a GitHub Release with auto-generated notes from merged PRs. To see what's in prod: `git tag --list 'prod/*' --sort=-version:refname | head -5`.

## Keeping Docs in Sync

After implementing significant changes, check whether these need updating:
- **`README.md`** — new/changed CLI commands, API endpoints, features, setup requirements, or architecture
- **`bootstrap-skills/dhub-cli/SKILL.md`** and **`bootstrap-skills/dhub-cli/references/command_reference.md`** — new/changed CLI commands, flags, or behavior

## Data Maintenance

Run all backfills (categories, embeddings, org metadata) in one command:

```bash
make backfill                    # against dev (default)
DHUB_ENV=prod make backfill      # against prod
```

Individual backfill scripts can also be run directly from `server/` — see `server/scripts/backfill_categories.py` and `server/src/decision_hub/scripts/backfill_embeddings.py`.

## Monitoring Trackers

Trackers (`skill_trackers` table) poll GitHub repos for new commits and republish changed skills. The `check_trackers` Modal cron runs every 5 minutes. Crawled skills are **not** auto-tracked — trackers are opt-in via `dhub track add`.

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
