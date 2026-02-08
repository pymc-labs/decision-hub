<p align="center">
  <img src="assets/banner.png" alt="Decision Hub — The Package Manager For AI Agent Skills" width="100%">
</p>

**Decision Hub** is a CLI-first registry for publishing, discovering, and installing *Skills* — modular packages of code and prompts that AI coding agents (Claude, Cursor, Codex, Gemini, OpenCode) can use. Think npm for agent capabilities: publish a skill once, install it into any supported agent with one command.

## Why Decision Hub

**Agents that extend themselves.** Decision Hub ships as a skill itself. Install it into Claude Code (or any supported agent), and the agent can search for, install, and use new skills mid-conversation — no human in the loop. The registry becomes a live capability layer that agents draw from on demand.

**Install once, use everywhere.** A single `dhub install` downloads a skill once and symlinks it into every agent's skill directory — Claude, Cursor, Codex, Gemini, OpenCode. No duplication, no per-agent setup.

**Security gauntlet.** Every publish is scanned for shell injection, credential exfiltration, and other dangerous patterns. Skills get a trust grade (A/B/C/F) before they ever reach the registry. Grade F is rejected outright; Grade C requires an explicit `--allow-risky` flag to install.

**Automated evals in sandboxes.** Skills ship with eval cases that run automatically on publish — each case executes in an isolated Modal sandbox with the configured agent, an LLM judge scores the output, and the results are published as a report.

**Natural language search.** `dhub ask "analyze A/B test results"` queries the full skill index with an LLM that ranks results by relevance alongside their trust grade.

**Executable skills with the SKILL.md format.** Builds on the [Agent Skills spec](https://agentskills.io/specification) with `runtime` (language, entrypoint, dependencies, env vars) and `evals` (agent, judge model) blocks — so skills can be runnable programs with reproducible environments, not just static prompts.

**Zero-config namespaces.** Your GitHub username and org memberships become your publishing namespaces automatically on login. No accounts to create, no orgs to manage.

**Private skills with access grants.** Publish org-private skills visible only to your team, then selectively share them with other orgs or users via access grants.

## Installation

```bash
# Via uv (recommended)
uv tool install dhub-cli

# Via pipx
pipx install dhub-cli
```

## Quick Start

```bash
# 1. Authenticate via GitHub
dhub login

# 2. Scaffold a new skill
dhub init my-skill

# 3. Publish it under your namespace
dhub publish myuser/my-skill ./my-skill

# 4. Install it for your agents
dhub install myuser/my-skill

# 5. Run it (if it has a runtime)
dhub run myuser/my-skill
```

## Namespaces

Decision Hub mirrors your GitHub identity — there are no separate accounts or manual org creation.

- **Personal namespace**: When you `dhub login`, your GitHub username becomes your personal namespace. Publish skills as `username/skill-name`.
- **Organization namespaces**: Your GitHub organization memberships are automatically synced on each login. If you belong to `acme-corp` on GitHub, you can publish as `acme-corp/skill-name`.
- **No manual creation**: Namespaces are derived from GitHub. There is no `org create` command.

```bash
# See all namespaces you can publish to
dhub org list

# Set a default namespace so you don't have to type it every time
dhub config default-org
```

## CLI Reference

### Authentication

| Command | Description |
|---------|-------------|
| `dhub login [--api-url URL]` | Authenticate via GitHub Device Flow |
| `dhub logout` | Remove stored token |
| `dhub env` | Show active environment, config path, and API URL |

### Skills

| Command | Description |
|---------|-------------|
| `dhub init [PATH]` | Scaffold a new skill project with `SKILL.md` and `src/` |
| `dhub publish [ORG/SKILL] [PATH] [--private]` | Publish a skill to the registry |
| `dhub install ORG/SKILL [-v VERSION] [--agent AGENT] [--allow-risky]` | Install a skill from the registry |
| `dhub uninstall ORG/SKILL` | Remove a locally installed skill and its agent symlinks |
| `dhub list` | List all published skills on the registry |
| `dhub delete ORG/SKILL [-v VERSION]` | Delete a skill version (or all versions) |
| `dhub run ORG/SKILL [ARGS...]` | Run a locally installed skill using its configured runtime |
| `dhub ask QUERY` | Search for skills using natural language |
| `dhub eval-report ORG/SKILL@VERSION` | View the agent evaluation report for a skill version |

### Publish options

```bash
# First publish defaults to 0.1.0, subsequent publishes auto-bump patch
dhub publish myorg/my-skill ./path/to/skill

# Explicit version bumps
dhub publish myorg/my-skill --patch     # 1.2.3 → 1.2.4
dhub publish myorg/my-skill --minor     # 1.2.3 → 1.3.0
dhub publish myorg/my-skill --major     # 1.2.3 → 2.0.0
dhub publish myorg/my-skill --version 2.0.0  # exact version

# Publish as org-private
dhub publish myorg/my-skill --private
```

Both arguments are positional and optional. If only one is given, Decision Hub infers whether it's a skill reference or a path. If omitted, defaults to the current directory and requires a default org to be set.

### Visibility & Access Grants

Skills default to `public`. Org-private skills are only visible to org members and explicitly granted orgs/users.

| Command | Description |
|---------|-------------|
| `dhub visibility ORG/SKILL {public\|org}` | Change skill visibility (org admins only) |
| `dhub access grant ORG/SKILL GRANTEE` | Grant access to a private skill |
| `dhub access revoke ORG/SKILL GRANTEE` | Revoke access to a private skill |
| `dhub access list ORG/SKILL` | List access grants for a private skill |

Since every user has a personal org (their username), granting to a user is the same as granting to their personal org.

### Organizations & Config

| Command | Description |
|---------|-------------|
| `dhub org list` | List namespaces you can publish to |
| `dhub config default-org` | Set the default namespace for publishing |
| `dhub keys add KEY_NAME` | Add an API key (prompts for value securely) |
| `dhub keys list` | List stored API key names |
| `dhub keys remove KEY_NAME` | Remove a stored API key |

## SKILL.md Format

Each skill is a directory containing a `SKILL.md` manifest file. The front matter defines metadata; the body is the system prompt injected into the agent.

```yaml
---
name: my-skill                    # 1-64 chars, lowercase alphanumeric + hyphens
description: >
  What this skill does and when
  the agent should activate it.   # 1-1024 chars
license: MIT                      # optional

runtime:                           # optional — makes the skill executable
  language: python
  entrypoint: src/main.py
  env: [OPENAI_API_KEY]            # required env vars
  dependencies:
    package_manager: uv
    lockfile: uv.lock

evals:                             # optional — enables automated evaluation
  agent: claude                    # agent to test with
  judge_model: claude-sonnet-4-5-20250929  # LLM judge model
---

System prompt content goes here. This is what the agent sees
when the skill is activated.
```

Eval cases live in `evals/*.yaml` files inside the skill directory and are included in the published artifact.

## Supported Agents

Skills are installed as symlinks into each agent's skill directory:

| Agent | Skill path |
|-------|-----------|
| Claude | `~/.claude/skills/{org}--{skill}` |
| Cursor | `~/.cursor/skills/{org}--{skill}` |
| Codex | `~/.codex/skills/{org}--{skill}` |
| OpenCode | `~/.config/opencode/skills/{org}--{skill}` |
| Gemini | `~/.gemini/skills/{org}--{skill}` |

Use `--agent claude` (or `cursor`, `codex`, `opencode`, `gemini`, `all`) with `dhub install` to target specific agents. By default, all detected agents are linked.

## Safety & Evals

Every published skill goes through a two-stage safety pipeline:

### Security Gauntlet

A static analysis pass that scans for dangerous patterns (shell injection, file exfiltration, credential access). Skills receive a letter grade:

| Grade | Meaning | Install behavior |
|-------|---------|-----------------|
| **A** | Clean — no elevated permissions or risky patterns | Installs normally |
| **B** | Elevated permissions detected | Warning shown on install |
| **C** | Ambiguous or risky patterns | Requires `--allow-risky` flag |
| **F** | Fails safety checks | Rejected at publish time (HTTP 422) |

### Agent Evaluation

If the skill includes an `evals` block and `evals/*.yaml` cases, an automated evaluation pipeline runs after publishing:

1. **Sandbox execution** — each eval case runs in an isolated Modal sandbox with the configured agent
2. **Exit code check** — non-zero exits are recorded as errors
3. **LLM judge** — an LLM evaluates the agent's output against the expected criteria

View results with `dhub eval-report org/skill@version`.

## Architecture

This is a **uv workspace monorepo** with two packages:

| Package | Directory | Import path | Description |
|---------|-----------|-------------|-------------|
| `dhub-cli` | `client/` | `dhub.*` | Open-source CLI tool |
| `decision-hub-server` | `server/` | `decision_hub.*` | Private backend API |

**Tech stack:**

- **CLI**: Python — Typer + Rich
- **API**: FastAPI on Modal
- **Database**: PostgreSQL (Supabase)
- **Storage**: S3 for skill artifacts
- **Compute**: Modal for sandboxed evaluations
- **Search**: Gemini LLM for natural language discovery

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
cd server && DHUB_ENV=dev uv run --package decision-hub-server python -c "
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

### Configuration

Copy `server/.env.example` to `server/.env.dev` (and/or `server/.env.prod`) and fill in your values.

## Environments

| | Dev | Prod |
|---|---|---|
| `DHUB_ENV` | `dev` | `prod` (default) |
| Server URL | `https://lfiaschi--api-dev.modal.run` | `https://lfiaschi--api.modal.run` |
| Server env file | `server/.env.dev` | `server/.env.prod` |
| CLI config | `~/.dhub/config.dev.json` | `~/.dhub/config.prod.json` |

Auth tokens are stored per-environment — login once per environment:

```bash
DHUB_ENV=dev dhub login    # dev token
dhub login                 # prod token (default)
```

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
