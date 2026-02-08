<p align="center">
  <img src="images/banner.png" alt="Decision Hub — The Package Manager For Data Science Agents Skills" width="100%">
</p>

Decision Hub is a CLI-first registry that allows developers to publish, discover, and securely install "Skills" -- modular capabilities (code + prompts) that agents like Claude, Cursor, and Gemini can use.

## Architecture

This repository is a **uv workspace monorepo** with two independent packages:

| Package | Directory | Import path | Description |
|---------|-----------|-------------|-------------|
| `dhub` | `client/` | `dhub.*` | Open-source CLI tool |
| `decision-hub-server` | `server/` | `decision_hub.*` | Private backend API |

- **CLI** (`client/`): Python (Typer + Rich)
- **API** (`server/`): FastAPI deployed on Modal
- **Database**: PostgreSQL (Supabase)
- **Storage**: S3 for skill artifacts
- **Compute**: Modal for sandboxed evaluations
- **Search**: Gemini LLM for natural language discovery

## Installation

```bash
# Via uv
uv tool install dhub

# Via pipx
pipx install dhub
```

## Quick Start

### Authentication

```bash
# Login via GitHub Device Flow
dhub login
```

### Organizations

```bash
# Create an organization
dhub org create my-org

# List your organizations
dhub org list
```

### Publishing Skills

Skills are directories containing a `SKILL.md` manifest:

```bash
# Auto-bump patch version (default: 0.1.0 for first publish, then +0.0.1)
dhub publish --org my-org --name my-skill

# Bump minor version (e.g. 1.2.3 -> 1.3.0)
dhub publish --org my-org --name my-skill --minor

# Bump major version (e.g. 1.2.3 -> 2.0.0)
dhub publish --org my-org --name my-skill --major

# Explicit version (overrides auto-bump)
dhub publish --org my-org --name my-skill --version 1.0.0
```

### Installing Skills

Only skills that have passed evaluation can be installed:

```bash
# Install a skill (downloads to ~/.dhub/skills/org/skill/)
dhub install my-org/my-skill

# Install a specific version
dhub install my-org/my-skill --version 1.0.0

# Install for a specific agent
dhub install my-org/my-skill --agent claude
```

### Deleting Skills

```bash
# Delete a specific version
dhub delete my-org/my-skill --version 1.0.0

# Delete all versions (prompts for confirmation)
dhub delete my-org/my-skill
```

### Running Skills

```bash
# Run a locally installed skill with uv isolation
dhub run my-org/my-skill
```

### Searching Skills

```bash
# Natural language search powered by Gemini
dhub ask "analyze A/B test results"
```

### API Key Management

Store API keys securely for agent evaluations:

```bash
# Add a key (prompts for value securely)
dhub keys add ANTHROPIC_API_KEY

# List stored keys
dhub keys list

# Remove a key
dhub keys remove ANTHROPIC_API_KEY
```

## SKILL.md Format

Decision Hub extends the [Agent Skills specification](https://agentskills.io/specification) with optional `runtime` and `evals` blocks for executable skills and automated evaluation.

```yaml
---
name: my-skill
description: >
  A description of what this skill does and when to use it.

# --- Standard Agent Skills fields (see agentskills.io/specification) ---
license: Apache-2.0
compatibility: Requires access to the internet
metadata:
  author: my-org

# --- Decision Hub extensions ---
runtime:
  language: python
  entrypoint: src/main.py
  version_hint: ">=3.11"
  env: ["OPENAI_API_KEY"]
  capabilities: ["network"]
  dependencies:
    package_manager: uv
    lockfile: uv.lock

evals:
  agent: claude
  judge_model: gpt-4o
---
System prompt for the agent goes here.
```

The `runtime` block declares what the skill needs to run. The `evals` block configures automated agent evaluation — individual eval cases live in `evals/*.yaml` files inside the skill zip.

## Environments

The project uses a `DHUB_ENV` environment variable to separate dev and prod stacks. **Default is `prod`** (for end-users installing from PyPI).

| | Dev | Prod |
|---|---|---|
| `DHUB_ENV` | `dev` | `prod` (default) |
| Server URL | `https://lfiaschi--api-dev.modal.run` | `https://lfiaschi--api.modal.run` |
| Server env file | `server/.env.dev` | `server/.env.prod` |
| CLI config | `~/.dhub/config.dev.json` | `~/.dhub/config.prod.json` |
| Modal app | `decision-hub-dev` | `decision-hub` |
| Modal secrets | `*-dev` suffix | no suffix |

Check the active environment:

```bash
DHUB_ENV=dev dhub env
```

### Switching environments

All CLI and server commands respect `DHUB_ENV`. For development, add to your shell profile:

```bash
export DHUB_ENV=dev
```

Auth tokens are stored per-environment, so you need to login once per environment:

```bash
DHUB_ENV=dev dhub login    # dev token → ~/.dhub/config.dev.json
dhub login                 # prod token → ~/.dhub/config.prod.json
```

`DHUB_API_URL` still overrides the API URL for any environment (e.g. pointing at localhost).

## Development

```bash
# Install all dependencies
uv sync --all-packages --all-extras

# Run client tests
uv run --package dhub pytest client/tests/

# Run server tests
uv run --package decision-hub-server pytest server/tests/

# Start local dev server
DHUB_ENV=dev uv run --package decision-hub-server uvicorn decision_hub.api.app:create_app --factory --reload

# Deploy dev to Modal
cd server && DHUB_ENV=dev modal deploy modal_app.py

# Deploy prod to Modal
cd server && modal deploy modal_app.py
```

### Database setup

Initialize a new database from the migration script:

```bash
cd server
DHUB_ENV=dev uv run --package decision-hub-server python -c "
from decision_hub.settings import create_settings
from decision_hub.infra.database import metadata, create_engine
engine = create_engine(create_settings().database_url)
metadata.create_all(engine)
"
```

## Configuration

Copy `server/.env.example` to `server/.env.dev` (and/or `server/.env.prod`) and fill in your values. See the example file for all available settings.
