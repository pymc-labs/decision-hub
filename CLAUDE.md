
## Workspace Structure

This is a **uv workspace monorepo** with two independent packages:

- **`client/`** — `dhub` package (open-source CLI) — import path: `dhub.*`
- **`server/`** — `decision-hub-server` package (private backend) — import path: `decision_hub.*`

## Tech Stack

- **Python 3.11+** with type hints
- **FastAPI** for REST API (server)
- **Typer + Rich** for CLI (client)
- **OpenAI** for  LLM
- **Pydantic** for data validation and settings
- **boto3** for S3 access
- **loguru** for server logging (see Logging section below)


**Important**: Always use `uv run` to execute Python code, not `python` directly.

## Environments (Dev / Prod)

The project has two independent stacks controlled by `DHUB_ENV` (`dev` | `prod`, default: `prod`).

**Always work against dev unless explicitly told to use prod.** Prefix all CLI, server, and deploy commands with `DHUB_ENV=dev`:

```bash
DHUB_ENV=dev dhub list                          # CLI against dev
DHUB_ENV=dev modal deploy modal_app.py          # deploy dev Modal app (from server/)
DHUB_ENV=dev uv run --package decision-hub-server uvicorn ...  # local dev server
```

- **Dev**: `https://lfiaschi--api-dev.modal.run`, config at `~/.dhub/config.dev.json`, env file `server/.env.dev`
- **Prod**: `https://lfiaschi--api.modal.run`, config at `~/.dhub/config.prod.json`, env file `server/.env.prod`

**Modal cold starts**: Modal containers spin down after inactivity. The first HTTP request after a cold start can take 30-60 seconds. Always use `timeout=60` (or higher) when making HTTP requests to Modal endpoints. Do NOT use default timeouts — they will fail on cold starts.

## Working Directory

**Always run server-package commands from `server/`**. The server's `.env.dev` / `.env.prod` files live in `server/` and `pydantic-settings` resolves them relative to the current working directory. Running from the repo root will fail with missing settings errors.

```bash
# Correct
cd server && DHUB_ENV=dev uv run --package decision-hub-server python -c "..."
cd server && DHUB_ENV=dev modal deploy modal_app.py

# Wrong — .env.dev not found
DHUB_ENV=dev uv run --package decision-hub-server python -c "..."
```

Client-package commands (`uv run --package dhub-cli ...`) can run from anywhere.

## Makefile

Common commands are available via `make`. Run `make help` to see all targets:

```bash
make test            # run all tests (client + server)
make test-client     # run client tests only
make test-server     # run server tests only
make lint            # check linting + formatting
make typecheck       # run mypy type checks
make fmt             # auto-fix lint issues and format code
make check-migrations # check for duplicate migration sequence numbers
make migrate-dev     # apply migrations to dev database
make deploy-dev      # build frontend + deploy to dev Modal
make install-hooks   # install pre-commit hooks (run once after cloning)
```

## Database Migrations

No `psql` available on this machine. Run migrations via `make migrate-dev` or manually (from `server/`):

```bash
cd server && DHUB_ENV=dev uv run --package decision-hub-server python -c "
from decision_hub.settings import create_settings
from decision_hub.infra.database import create_engine, metadata
settings = create_settings('dev')
engine = create_engine(settings.database_url)
metadata.create_all(engine)
"
```

Migration files live in `server/migrations/` with numeric prefixes (e.g. `008_add_semver_int_columns.sql`). When adding a new migration, check for prefix collisions — `make check-migrations` and the CI pipeline will catch duplicates from parallel branches.

## Linting & Formatting

The project uses **ruff** for linting and formatting, and **mypy** for type checking, both configured in the root `pyproject.toml`. Pre-commit hooks run ruff automatically on every commit (install once with `make install-hooks`). Mypy runs in CI only (not pre-commit).

```bash
make lint       # check only (CI runs this)
make typecheck  # mypy type checks (CI runs this)
make fmt        # auto-fix + format
```

## Running Tests

Use `make test` or run individually:

```bash
make test              # all tests
make test-client       # client only
make test-server       # server only
```

## Coding Conventions

- Use **frozen dataclasses** for immutable data models
- Prefer **pure functions** over classes - use modules to group related functions
- Use comments to explain what the business logic and document assumptions and choices not to explain the code verbatim

## Design Principles

- **Single responsibility**: Small, single-purpose functions with one clear reason to change
- **Clear interfaces**: Descriptive names, type hints, explicit signatures - obvious inputs, outputs, and behavior
- **Domain/infrastructure separation**: Keep business logic independent from frameworks, I/O, databases. UI, persistence, and external services are replaceable adapters around a clean core - **Testing as design**: Design for fast, focused unit tests. Pure functions and small units guide architecture
-**Readability over cleverness**: Straightforward, idiomatic Python over opaque tricks. Follow PEP 8
- **YAGNI**: No abstractions or features "just in case" - add complexity only for concrete needs
- **Continuous refactoring**: Ship the simplest thing that works, refactor as requirements evolve. Routine maintenance, not heroic effort
- **Don't worship backward compatibility**: Don't freeze bad designs to avoid breaking changes. Provide clear migration paths instead of stacking hacks
- **DRY** do not repetat yourself, refactor the code and ensure each piece of logic has a single, clear, authoritative implementation instead of being duplicated across the codebase

## Logging

The server uses **loguru** (`from loguru import logger`). The client does not — it uses Rich console output directly. Logging is configured once at startup via `setup_logging()` in `decision_hub.logging`. Log level is controlled by `LOG_LEVEL` in `server/.env.dev` / `.env.prod` (default: `INFO`). All output goes to **stderr** — no log files. A `RequestLoggingMiddleware` assigns an 8-char request ID to every HTTP request for correlation.

**Use `{}` placeholders, not f-strings** — loguru defers evaluation so arguments are only computed when the level is active:

```python
logger.info("Publishing {}/{} version={}", org_slug, skill_name, version_id)
```

**Use `logger.opt(exception=True)`** to attach tracebacks — don't format exceptions into the message string.

**Log in API/infra layers, not in domain functions.** Domain functions return values or raise — the caller decides what to log.

**Include greppable identifiers** (org, skill, case name, status code) — not just human prose.

### Inspecting Logs

```bash
# Stream live logs from Modal
modal app logs decision-hub          # prod
modal app logs decision-hub-dev      # dev

# Filter by request ID to trace a single request
modal app logs decision-hub-dev 2>&1 | grep "a1b2c3d4"
```

## Client / Server Version Sync

The server enforces a minimum CLI version via the `MIN_CLI_VERSION` setting in `server/.env.dev` and `server/.env.prod`. When making breaking changes that require the client and server to stay in sync (new request/response fields, changed CLI argument signatures, new required headers, removed or renamed endpoints), you **must**:

1. Bump the version in `client/pyproject.toml`
2. Update `MIN_CLI_VERSION` in both `server/.env.dev` and `server/.env.prod` to match
3. Redeploy the server so the middleware rejects stale clients with a clear upgrade message

## Debugging Modal Sandboxes

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

## CI

GitHub Actions runs on every PR to `main`:
- **lint**: ruff check + format
- **typecheck**: mypy type checks
- **test-client**: client pytest suite
- **test-server**: server pytest suite
- **lint-frontend**: TypeScript type check + ESLint
- **check-migrations**: detects duplicate migration sequence numbers

## Testing

- Use `pytest` with fixtures in `conftest.py`
- Mock external services (S3, OpenAI, Database) in tests

## Documentation

After implementing significant changes, always check if the README.md needs updating. Update it for:
- New CLI commands or changed command behavior
- New API endpoints or changed API behavior
- New features or capabilities
- Changes to setup/configuration requirements
- Architectural changes that affect how the system works


## dhub CLI Skill

The `bootstrap-skills/dhub-cli/` skill is a reference guide for the dhub CLI. When making significant changes to CLI commands (adding, removing, renaming commands or flags, changing behavior), update this skill to match:
- `bootstrap-skills/dhub-cli/SKILL.md` — command overview, workflows, troubleshooting
- `bootstrap-skills/dhub-cli/references/command_reference.md` — detailed per-command reference
