# Decision Hub

The package manager & runtime for AI agent skills.

Decision Hub is a CLI-first registry that allows developers to publish, discover, and securely install "Skills" — modular capabilities (code + prompts) that agents like Claude, Cursor, Codex, and Gemini can use.

## Architecture

This is a **uv workspace monorepo** with two packages:

| Package | Directory | Import path | Description |
|---------|-----------|-------------|-------------|
| `dhub-cli` | `client/` | `dhub.*` | Open-source CLI tool |
| `decision-hub-server` | `server/` | `decision_hub.*` | Private backend API |

**Tech stack**: Python 3.11+, FastAPI (server), Typer + Rich (CLI), PostgreSQL via Supabase, S3 for artifact storage, Modal for sandboxed evals, Gemini for natural language search.

## CLI Usage

### Install

```bash
uv tool install dhub-cli     # recommended
pipx install dhub-cli         # alternative
```

### Core commands

```bash
dhub login                              # authenticate via GitHub
dhub publish myorg/my-skill             # publish (auto-bumps patch)
dhub publish myorg/my-skill --private   # publish as org-private
dhub install myorg/my-skill             # install latest version
dhub install myorg/my-skill --agent claude  # install + link to Claude
dhub run myorg/my-skill                 # run a locally installed skill
dhub ask "analyze A/B test results"     # natural language search
dhub list                               # list all published skills
```

### Publishing

```bash
dhub publish myorg/my-skill                   # auto-bump patch (0.1.0 for first publish)
dhub publish myorg/my-skill --minor           # bump minor
dhub publish myorg/my-skill --major           # bump major
dhub publish myorg/my-skill --version 2.0.0   # explicit version
dhub publish myorg/my-skill ./path            # specify skill directory
dhub publish myorg/my-skill --private         # org-private visibility
```

All published skills pass through a safety pipeline (Gauntlet) and receive a grade (A/B/C/F). Grade F skills are rejected.

### Skill visibility & access grants

Skills default to `public`. Org-private skills are only visible to org members and explicitly granted orgs/users.

```bash
dhub visibility myorg/my-skill org      # make org-private
dhub visibility myorg/my-skill public   # make public

# Share private skills with other orgs or users (org admins only)
dhub access grant myorg/my-skill partner-org
dhub access revoke myorg/my-skill partner-org
dhub access list myorg/my-skill
```

Since every user has a personal org (their username), granting to a user is the same as granting to their personal org.

### Other commands

```bash
dhub init                               # scaffold a new skill project
dhub uninstall myorg/my-skill           # remove a locally installed skill
dhub delete myorg/my-skill --version 1.0.0  # delete a version
dhub delete myorg/my-skill              # delete all versions (with confirmation)
dhub eval-report myorg/my-skill@1.0.0   # view eval results
dhub org list                           # list your namespaces
dhub keys add OPENAI_API_KEY            # store an API key for evals
dhub keys list                          # list stored key names
dhub keys remove OPENAI_API_KEY         # remove a stored key
dhub env                                # show active environment
dhub --version                          # show CLI version
```

## SKILL.md Format

Skills are directories containing a `SKILL.md` manifest. Decision Hub extends the [Agent Skills specification](https://agentskills.io/specification) with optional `runtime` and `evals` blocks:

```yaml
---
name: my-skill
description: What this skill does and when to use it.
license: Apache-2.0
runtime:
  language: python
  entrypoint: src/main.py
  env: [OPENAI_API_KEY]
  dependencies:
    package_manager: uv
    lockfile: uv.lock
evals:
  agent: claude
  judge_model: claude-sonnet-4-5-20250929
---
System prompt for the agent goes here.
```

The `runtime` block declares what the skill needs to run. The `evals` block triggers automated agent evaluation after publishing — cases are defined in `evals/*.yaml` inside the skill directory.

## Environments

`DHUB_ENV` controls dev/prod. **Default is `prod`.**

| | Dev | Prod |
|---|---|---|
| `DHUB_ENV` | `dev` | `prod` (default) |
| API URL | `https://lfiaschi--api-dev.modal.run` | `https://lfiaschi--api.modal.run` |
| Server env | `server/.env.dev` | `server/.env.prod` |
| CLI config | `~/.dhub/config.dev.json` | `~/.dhub/config.prod.json` |
| Modal app | `decision-hub-dev` | `decision-hub` |

```bash
DHUB_ENV=dev dhub login     # login to dev
DHUB_ENV=dev dhub list      # list skills on dev
DHUB_ENV=dev dhub env       # verify active environment
```

`DHUB_API_URL` overrides the API URL for any environment (e.g. pointing at localhost).

## Development

### Setup

```bash
uv sync --all-packages --all-extras
```

### Tests

```bash
uv run --package dhub-cli python -m pytest client/tests/ -q        # client
uv run --package decision-hub-server python -m pytest server/tests/ -q  # server
```

### Local dev server

```bash
cd server
DHUB_ENV=dev uv run --package decision-hub-server uvicorn decision_hub.api.app:create_app --factory --reload
```

### Deploy

```bash
cd server && DHUB_ENV=dev modal deploy modal_app.py   # dev
cd server && modal deploy modal_app.py                 # prod
```

### Database

Initialize tables from the SQLAlchemy schema:

```bash
cd server
DHUB_ENV=dev uv run --package decision-hub-server python -c "
from decision_hub.settings import create_settings
from decision_hub.infra.database import metadata, create_engine
engine = create_engine(create_settings().database_url)
metadata.create_all(engine)
"
```

Run incremental migrations via scripts in `server/scripts/`:

```bash
cd server
DHUB_ENV=dev uv run --package decision-hub-server python scripts/migrate_access_grants.py
```

### Release

Publish the CLI to PyPI:

```bash
./scripts/publish.sh           # build + publish to PyPI
./scripts/publish.sh --test    # publish to TestPyPI first
```

## Repository layout

```
client/                     CLI package (dhub-cli)
  src/dhub/                 Source code
  tests/                    Client tests
server/                     Server package (decision-hub-server)
  src/decision_hub/         Source code
    api/                    FastAPI routes
    domain/                 Business logic (gauntlet, search, publish)
    infra/                  Database, S3, Modal, Gemini clients
  tests/                    Server tests
  scripts/                  Migration and maintenance scripts
  modal_app.py              Modal deployment entrypoint
scripts/                    Repo-wide scripts (publish, CI)
bootstrap-skills/           Built-in skills shipped with the platform
```

## Configuration

Copy `server/.env.example` to `server/.env.dev` (and/or `server/.env.prod`) and fill in your values. Required settings: `DATABASE_URL`, `JWT_SECRET`, `FERNET_KEY`, `S3_BUCKET`, `GOOGLE_API_KEY`.
