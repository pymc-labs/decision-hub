<p align="center">
  <img src="assets/banner.png" alt="Decision Hub — The AI Skill Manager for Data Science Agents" width="100%">
</p>

**Decision Hub** is a CLI-first registry for publishing, discovering, and installing *Skills* — modular packages of code and prompts that AI coding agents (Claude, Cursor, Codex, Gemini, OpenCode) can use. Publish a skill once, install it into any supported agent with one command.

## Installation

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && . $HOME/.local/bin/env && uv tool install dhub-cli
```

This installs [uv](https://docs.astral.sh/uv/) (if not already present), updates your `PATH`, and installs the CLI. If you already have `uv` or `pipx`:

```bash
uv tool install dhub-cli    # via uv
pipx install dhub-cli       # via pipx
```

## Quick Start

```bash
# Search for skills in plain English
dhub ask "I need to do Bayesian statistics with PyMC"

# Install to Claude, Cursor, Codex, Gemini, OpenCode...
dhub install pymc-labs/pymc-modeling

# Scaffold and publish your own skill
dhub init my-skill
dhub publish ./my-skill
```

## Why Decision Hub

**Agents that extend themselves.** Decision Hub ships as a skill itself. Install it into Claude Code (or any supported agent), and the agent can discover new skills mid-conversation — `dhub ask "analyze A/B test results"` — then install and use them without human intervention.

**Publish from anywhere.** Point `dhub publish` at a local directory or a GitHub repo URL and every `SKILL.md` inside is discovered, versioned, and published automatically.

**Private skills for your team.** Skills scoped to your GitHub organization are only visible to members — proprietary tooling stays internal while using the same registry workflow.

**Install once, use everywhere.** A single `dhub install` downloads a skill and symlinks it into every detected agent's skill directory. No duplication, no per-agent setup.

**Security gauntlet.** Every publish is scanned for shell injection, credential exfiltration, and other dangerous patterns. Skills receive a trust grade (A/B/C/F). Grade F is rejected; Grade C requires `--allow-risky` to install.

**Automated evals.** Skills ship with eval cases that run on publish — each executes in an isolated sandbox, an LLM judge scores the output, and results are published as a report.

**Zero-config namespaces.** Your GitHub username and org memberships become publishing namespaces on login. No accounts to create, no orgs to manage.

## SKILL.md Format

Each skill is a directory containing a `SKILL.md` manifest. The YAML front matter defines metadata; the body is the system prompt injected into the agent. Builds on the [Agent Skills spec](https://agentskills.io/specification).

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

## CLI Reference

### Authentication

| Command | Description |
|---------|-------------|
| `dhub login` | Authenticate via GitHub Device Flow |
| `dhub logout` | Remove stored token |
| `dhub env` | Show active environment, config path, and API URL |

### Publishing

```bash
# Publish all skills found under a directory
# Org is auto-detected from login; skill name comes from SKILL.md
dhub publish ./path/to/skills

# Publish from a GitHub repo URL
dhub publish https://github.com/org/repo

# Version control (default: auto-bump patch from 0.1.0)
dhub publish ./my-skill --patch          # 1.2.3 → 1.2.4 (default)
dhub publish ./my-skill --minor          # 1.2.3 → 1.3.0
dhub publish ./my-skill --major          # 1.2.3 → 2.0.0
dhub publish ./my-skill --version 2.0.0  # explicit version

# Publish a specific branch/tag from a git repo
dhub publish https://github.com/org/repo --ref v1.0
```

### Installing & Running

| Command | Description |
|---------|-------------|
| `dhub install ORG/SKILL` | Install a skill and symlink into all detected agents |
| `dhub install ORG/SKILL -v VERSION` | Install a specific version |
| `dhub install ORG/SKILL --agent claude` | Install for a specific agent only |
| `dhub install ORG/SKILL --allow-risky` | Allow installing C-grade skills |
| `dhub uninstall ORG/SKILL` | Remove a skill and its agent symlinks |
| `dhub run ORG/SKILL [ARGS...]` | Run a locally installed skill |

### Discovery

| Command | Description |
|---------|-------------|
| `dhub list` | List all published skills (sorted by downloads) |
| `dhub list --org ORG` | Filter by organization |
| `dhub list --skill NAME` | Filter by skill name (substring match) |
| `dhub ask "QUERY"` | Search for skills using natural language |
| `dhub init [PATH]` | Scaffold a new skill project |

### Evals

| Command | Description |
|---------|-------------|
| `dhub eval-report ORG/SKILL@VERSION` | View the evaluation report for a version |
| `dhub logs` | List recent eval runs |
| `dhub logs ORG/SKILL [--follow]` | Tail eval logs for the latest version |
| `dhub logs ORG/SKILL@VERSION --follow` | Tail eval logs for a specific version |
| `dhub logs RUN_ID --follow` | Tail a specific eval run by ID |

### Auto-Tracking

When you publish from a GitHub URL, a tracker is automatically created to republish skills on future commits:

```bash
# Publish + auto-track (default)
dhub publish https://github.com/org/skills-repo

# Publish without tracking
dhub publish https://github.com/org/repo --no-track

# Re-enable tracking on a previously paused tracker
dhub publish https://github.com/org/repo --track
```

**Private repos** require a GitHub personal access token with `repo` scope:

```bash
dhub keys add GITHUB_TOKEN
dhub publish https://github.com/org/private-repo
```

Without a token, private repos will not sync and the tracker will report an error. Public repos work without any token.

### Organizations & Config

| Command | Description |
|---------|-------------|
| `dhub org list` | List namespaces you can publish to |
| `dhub config default-org` | Set the default namespace for publishing |
| `dhub keys add KEY_NAME` | Add an API key (prompts for value securely) |
| `dhub keys list` | List stored API key names |
| `dhub keys remove KEY_NAME` | Remove a stored API key |

## Supported Agents

Skills are installed as symlinks into each agent's skill directory:

| Agent | Skill path |
|-------|-----------|
| Claude | `~/.claude/skills/{skill}` |
| Cursor | `~/.cursor/skills/{skill}` |
| Codex | `~/.codex/skills/{skill}` |
| OpenCode | `~/.config/opencode/skills/{skill}` |
| Gemini | `~/.gemini/skills/{skill}` |

By default, `dhub install` symlinks into all detected agents. Use `--agent NAME` to target a specific one.

## Safety & Evals

Every published skill goes through a two-stage pipeline:

### Security Gauntlet

An automated scan for dangerous patterns (shell injection, file exfiltration, credential access). Skills receive a letter grade:

| Grade | Meaning | Behavior |
|-------|---------|----------|
| **A** | Clean | Installs normally |
| **B** | Elevated permissions detected | Warning shown on install |
| **C** | Risky patterns | Requires `--allow-risky` flag |
| **F** | Fails safety checks | Rejected at publish time |

### Agent Evaluation

If the skill includes an `evals` block and `evals/*.yaml` cases, an evaluation pipeline runs after publishing:

1. Each eval case runs in an isolated Modal sandbox with the configured agent
2. An LLM judge scores the agent's output against expected criteria
3. Results are published as a report

The CLI auto-attaches to the live log stream after publish. View results anytime with `dhub eval-report` or `dhub logs --follow`.

## Architecture

This is a **uv workspace monorepo** with four components:

| Component | Directory | Import path | Description |
|-----------|-----------|-------------|-------------|
| `dhub-cli` | `client/` | `dhub.*` | Open-source CLI (published to PyPI) |
| `decision-hub-server` | `server/` | `decision_hub.*` | Backend API (deployed on Modal) |
| `dhub-core` | `shared/` | `dhub_core.*` | Shared domain models and validation |
| Frontend | `frontend/` | — | React + TypeScript web UI |

**Tech stack:** Python 3.11+ / Typer + Rich (CLI) / FastAPI (API) / PostgreSQL (database) / S3 (artifact storage) / Modal (sandboxed evals) / Gemini (natural language search)

## Development

```bash
# Install all dependencies
uv sync --all-packages --all-extras

# Run tests
make test              # all tests
make test-client       # client only
make test-server       # server only
make test-frontend     # frontend only

# Lint and type check
make lint              # ruff check + format
make typecheck         # mypy
make fmt               # auto-fix + format

# Start local dev server (must run from server/)
cd server && DHUB_ENV=dev uv run --package decision-hub-server \
  uvicorn decision_hub.api.app:create_app --factory --reload
```

### Configuration

Copy `server/.env.example` to `server/.env.dev` and fill in your values. Schema changes are managed through SQL migration files in `server/migrations/` — see CLAUDE.md for details.

### Environments

The project has two independent stacks controlled by `DHUB_ENV` (`dev` | `prod`):

| | Dev | Prod |
|---|---|---|
| `DHUB_ENV` | `dev` | `prod` (CLI default) |
| Server env file | `server/.env.dev` | `server/.env.prod` |
| CLI config | `~/.dhub/config.dev.json` | `~/.dhub/config.prod.json` |

```bash
DHUB_ENV=dev dhub login    # dev token
dhub login                 # prod token (default)
```

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
