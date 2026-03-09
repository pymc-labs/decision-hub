<p align="center">
  <img src="assets/banner.png" alt="Decision Hub — The AI Skill Manager" width="100%">
</p>

<p align="center">
  <a href="https://pypi.org/project/dhub-cli/"><img src="https://img.shields.io/pypi/v/dhub-cli" alt="PyPI Version"></a>
  <a href="https://pypi.org/project/dhub-cli/"><img src="https://img.shields.io/pypi/dm/dhub-cli" alt="PyPI Downloads"></a>
  <a href="https://pypi.org/project/dhub-cli/"><img src="https://img.shields.io/pypi/pyversions/dhub-cli" alt="Python Version"></a>
  <a href="https://github.com/pymc-labs/decision-hub/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/pymc-labs/decision-hub/ci.yml?label=CI" alt="CI Status"></a>
  <a href="https://github.com/pymc-labs/decision-hub/blob/main/LICENSE"><img src="https://img.shields.io/github/license/pymc-labs/decision-hub" alt="License"></a>
  <a href="https://github.com/pymc-labs/decision-hub/stargazers"><img src="https://img.shields.io/github/stars/pymc-labs/decision-hub" alt="GitHub Stars"></a>
</p>

## What is Decision Hub?

Decision Hub is an **open-source registry and package manager for AI agent skills**, built by [PyMC Labs](https://www.pymc-labs.com/) with a focus on **data science, statistics, and ML workflows**. Skills are modular packages of prompts and code that any AI coding agent can use — think npm, but for agent capabilities.

Publish a skill once. Install it into Claude Code, Cursor, Codex, Gemini CLI, Windsurf, or any of 40+ supported agents with a single command. Every skill is security-scanned and can ship with **automated eval cases** that run on publish — so you know a skill actually works before you trust your agent with it.

Decision Hub is **fully open-source (MIT)** — the CLI, server, and web UI are all in this repo. You can use the public registry at [hub.decision.ai](https://hub.decision.ai), or **deploy your own instance** on your company's infrastructure for complete control over your skill supply chain.

## Decision Hub is right for you if

- You work in **data science, statistics, or ML** and want AI agents that actually know your tools (PyMC, Stan, scikit-learn, pandas, etc.)
- You want **proven skills, not blind trust** — Decision Hub's eval pipeline tests skills against real tasks before you install them
- You maintain best practices or workflows and want to **share them across your team** as versioned, installable packages
- You build libraries and want to **ship an AI skill** alongside your package so agents know how to use it correctly
- You need a **private skill registry** for your organization — or want to **self-host the entire platform** on your own infrastructure
- You care about **safety** — you want skills security-scanned and graded before your agents run them

## Features

- **40+ agent support** — install once, symlink into Claude Code, Cursor, Codex, Windsurf, Gemini CLI, GitHub Copilot, and [many more](#supported-agents)
- **Publish from anywhere** — point at a local directory or a GitHub URL; every `SKILL.md` inside is discovered and versioned automatically
- **Private skills** — scope skills to your GitHub org with `--private`; grant cross-org access selectively
- **Security gauntlet** — every publish is scanned for shell injection, credential exfiltration, and dangerous patterns; skills receive a trust grade (A/B/C/F)
- **Automated evals** — ship eval cases with your skill; they run in an isolated sandbox, an LLM judge scores the output, and results are published as a report
- **Auto-tracking** — publish from a GitHub URL and a tracker automatically republishes on future commits; no CI setup needed
- **Self-extending agents** — Decision Hub ships as a skill itself; install it into your agent and the agent can discover and install new skills mid-conversation
- **Natural language search** — `dhub ask "I need to do Bayesian statistics"` finds relevant skills instantly

## Problems Decision Hub Solves

| Problem | How Decision Hub solves it |
|---------|---------------------------|
| AI agents hallucinate library APIs — they don't know PyMC, Stan, or your internal tools | Install skills that teach agents your stack with correct, tested patterns |
| No way to know if a skill actually works before installing it | Automated evals run real tasks in sandboxes on every publish — results are public |
| Copy-pasting system prompts between projects and teammates | Publish once, `dhub install` everywhere — versioned and updatable |
| No way to know if a community prompt is safe to run | Security gauntlet scans every publish and assigns a trust grade |
| Skill registries are vendor-locked SaaS you can't audit or self-host | Fully open-source (MIT) — deploy on your own infrastructure |
| Skills work in one agent but not another | One SKILL.md format, 40+ agents supported via `--agent all` |
| Skills drift out of sync with the code they reference | GitHub auto-tracking republishes on every commit |

## Why Decision Hub is special

**Three things set Decision Hub apart from every other skill registry:**

1. **Eval pipeline** — Other registries accept uploads and hope for the best. Decision Hub runs your skill's eval cases in isolated sandboxes on every publish. An LLM judge scores the output. You get a public report showing whether the skill actually works. This is especially critical for data science skills where a wrong statistical method or incorrect API call can silently produce bad results.

2. **Fully open-source and self-hostable** — Decision Hub is the only skill registry where the CLI, server, web UI, eval infrastructure, and security scanner are all open-source (MIT). You can use the public registry, or `make deploy-local` to run the entire platform on your own infrastructure. No vendor lock-in, full auditability, complete control over your skill supply chain.

3. **Built for data science** — Created by [PyMC Labs](https://www.pymc-labs.com/), the team behind PyMC. The registry ships with skills for Bayesian modeling, statistical analysis, and ML workflows. The search, categorization, and eval pipeline are designed for technical skills where correctness matters more than convenience.

## What Decision Hub is not

- **Not an agent framework** — Decision Hub doesn't run agents. It gives agents capabilities. Use it alongside your preferred agent (Claude Code, Cursor, Codex, etc.)
- **Not a prompt marketplace** — there's no payment layer. Skills are published freely under open-source licenses (or kept private within your org)
- **Not a closed SaaS** — the entire platform is MIT-licensed. There's no "enterprise tier" hiding features behind a paywall
- **Not an MCP server registry** — skills are prompt+code packages that agents load directly, not server processes. They complement MCP, not replace it

## Quickstart

### Install

```bash
# Install uv (if needed) and the CLI
curl -LsSf https://astral.sh/uv/install.sh | sh && PATH="$HOME/.local/bin:$PATH" uv tool install dhub-cli
```

Or if you already have `uv` or `pipx`:

```bash
uv tool install dhub-cli    # via uv
pipx install dhub-cli       # via pipx
```

### Use

```bash
# Authenticate via GitHub
dhub login

# Search for skills in plain English
dhub ask "I need to do Bayesian statistics with PyMC"

# Install a skill into your agent
dhub install pymc-labs/pymc-modeling --agent claude-code

# Or install into all detected agents at once
dhub install pymc-labs/pymc-modeling --agent all

# Scaffold and publish your own skill
dhub init my-skill
dhub publish ./my-skill
```

### The SKILL.md format

Each skill is a directory with a `SKILL.md` file. YAML front matter defines metadata; the body is the system prompt injected into the agent.

```yaml
---
name: my-skill                    # 1-64 chars, lowercase alphanumeric + hyphens
description: >
  What this skill does and when
  the agent should activate it.
license: MIT

runtime:                           # optional — makes the skill executable
  language: python
  entrypoint: src/main.py
  env: [OPENAI_API_KEY]
  dependencies:
    package_manager: uv
    lockfile: uv.lock

evals:                             # optional — enables automated evaluation
  agent: claude
  judge_model: claude-sonnet-4-5-20250929
---

System prompt content goes here. This is what the agent sees
when the skill is activated.
```

Builds on the [Agent Skills spec](https://agentskills.io/specification).

## FAQ

<details>
<summary><strong>How is a skill different from a system prompt?</strong></summary>

A skill is a system prompt plus optional code, dependencies, runtime config, and eval cases — packaged, versioned, and distributable. A raw system prompt is just text; a skill is a deployable unit with safety scanning, version history, and automated testing.
</details>

<details>
<summary><strong>Which agents are supported?</strong></summary>

40+ agents including Claude Code, Cursor, Codex, Windsurf, Gemini CLI, GitHub Copilot, Roo Code, OpenCode, Cline, Goose, and many more. See the [full list](#supported-agents) below. Use `--agent all` to install into every detected agent at once.
</details>

<details>
<summary><strong>Are skills safe to install?</strong></summary>

Every published skill goes through a security gauntlet that scans for shell injection, credential exfiltration, and other dangerous patterns. Skills receive a letter grade: **A** (clean), **B** (elevated permissions — warning shown), **C** (risky — requires `--allow-risky`), or **F** (rejected at publish time). Downloads are verified via SHA-256 checksums.
</details>

<details>
<summary><strong>Can I publish private skills for my team?</strong></summary>

Yes. Publish with `dhub publish --private` to scope a skill to your GitHub organization. Grant cross-org access selectively with `dhub access grant`. Visibility can be changed later with `dhub visibility`.
</details>

<details>
<summary><strong>How does auto-tracking work?</strong></summary>

When you publish from a GitHub URL, a tracker monitors the repo for new commits and automatically republishes affected skills. No CI setup or webhooks needed. Disable with `--no-track`.
</details>

<details>
<summary><strong>What are evals?</strong></summary>

Skills can ship with `evals/*.yaml` test cases. On publish, each case runs in an isolated sandbox: the configured agent executes the task, and an LLM judge scores the output. Results are published as a report viewable via `dhub eval-report` or on the web registry.
</details>

<details>
<summary><strong>Do I need a Decision Hub account?</strong></summary>

You need a GitHub account. Run `dhub login` — it uses GitHub Device Flow (OAuth2). Your GitHub username and org memberships automatically become your publishing namespaces.
</details>

<details>
<summary><strong>Can I self-host Decision Hub?</strong></summary>

Yes. The entire platform — CLI, server, web UI, eval infrastructure, security scanner — is MIT-licensed and in this repo. Run `make deploy-local` for a fully isolated local instance with its own database and S3 storage, or deploy to your own cloud infrastructure. See the [Development](#development) section.
</details>

<details>
<summary><strong>Is it free?</strong></summary>

Yes. Decision Hub is open-source (MIT) and the public registry is free to use. Self-hosting is free too — you only pay for your own infrastructure.
</details>

## CLI Reference

Run `dhub <command> --help` for full usage of any command.

### Core Commands

| Command | Description |
|---------|-------------|
| `dhub login` | Authenticate via GitHub Device Flow |
| `dhub logout` | Remove stored token |
| `dhub env` | Show active environment, config path, and API URL |
| `dhub upgrade` | Upgrade the CLI to the latest version |

### Publishing & Versioning

```bash
dhub publish ./path/to/skills                        # from a local directory
dhub publish https://github.com/org/repo             # from a GitHub URL (auto-tracks)
dhub publish https://github.com/org/repo --ref v1.0  # specific branch/tag
dhub publish ./my-skill --minor                      # version bump: --patch (default) | --minor | --major
dhub publish ./my-skill --version 2.0.0              # explicit version
dhub publish ./my-skill --private                    # org-private visibility
dhub publish https://github.com/org/repo --no-track  # skip auto-tracking
```

### Installing & Running

| Command | Description |
|---------|-------------|
| `dhub install ORG/SKILL` | Download a skill to `~/.dhub/skills/` |
| `dhub install ORG/SKILL --agent all` | Download and symlink into all detected agents |
| `dhub install ORG/SKILL --agent claude-code` | Download and symlink into a specific agent |
| `dhub install ORG/SKILL -v VERSION` | Install a specific version |
| `dhub install ORG/SKILL --allow-risky` | Allow installing C-grade skills |
| `dhub uninstall ORG/SKILL` | Remove a skill and its agent symlinks |
| `dhub run ORG/SKILL [ARGS...]` | Run a locally installed skill |

### Discovery

| Command | Description |
|---------|-------------|
| `dhub list` | List all published skills |
| `dhub list --org ORG` | Filter by organization |
| `dhub list --skill NAME` | Filter by skill name |
| `dhub info ORG/SKILL` | Show detailed information about a skill |
| `dhub ask "QUERY"` | Natural language search |
| `dhub init [PATH]` | Scaffold a new skill project |

### Evals

| Command | Description |
|---------|-------------|
| `dhub eval-report ORG/SKILL@VERSION` | View the evaluation report for a version |
| `dhub logs` | List recent eval runs |
| `dhub logs ORG/SKILL --follow` | Tail eval logs for the latest version |
| `dhub logs RUN_ID --follow` | Tail a specific eval run by ID |

### Organizations, Keys & Access Control

| Command | Description |
|---------|-------------|
| `dhub org list` | List namespaces you can publish to |
| `dhub config default-org` | Set the default namespace for publishing |
| `dhub keys add KEY_NAME` | Add an API key (prompts for value securely) |
| `dhub keys list` | List stored API key names |
| `dhub keys remove KEY_NAME` | Remove a stored API key |
| `dhub publish ./skill --private` | Publish as org-private |
| `dhub visibility ORG/SKILL public\|org` | Change visibility |
| `dhub access grant ORG/SKILL OTHER_ORG` | Grant another org access to a private skill |
| `dhub access revoke ORG/SKILL OTHER_ORG` | Revoke access |
| `dhub access list ORG/SKILL` | List access grants |
| `dhub delete ORG/SKILL` | Delete all versions of a skill |

## Supported Agents

Skills are installed as symlinks into each agent's skill directory. Use `--agent NAME` to target one agent or `--agent all` for all detected agents.

<details>
<summary>40+ supported agents (click to expand)</summary>

| Agent | `--agent` | Skill path |
|-------|-----------|-----------|
| AdaL | `adal` | `~/.adal/skills/{skill}` |
| Amp | `amp` | `~/.config/agents/skills/{skill}` |
| Antigravity | `antigravity` | `~/.gemini/antigravity/skills/{skill}` |
| Augment | `augment` | `~/.augment/skills/{skill}` |
| Claude Code | `claude-code` | `~/.claude/skills/{skill}` |
| Cline | `cline` | `~/.cline/skills/{skill}` |
| CodeBuddy | `codebuddy` | `~/.codebuddy/skills/{skill}` |
| Codex | `codex` | `~/.codex/skills/{skill}` |
| Command Code | `command-code` | `~/.commandcode/skills/{skill}` |
| Continue | `continue` | `~/.continue/skills/{skill}` |
| Cortex Code | `cortex` | `~/.snowflake/cortex/skills/{skill}` |
| Crush | `crush` | `~/.config/crush/skills/{skill}` |
| Cursor | `cursor` | `~/.cursor/skills/{skill}` |
| Droid | `droid` | `~/.factory/skills/{skill}` |
| Gemini CLI | `gemini-cli` | `~/.gemini/skills/{skill}` |
| GitHub Copilot | `github-copilot` | `~/.copilot/skills/{skill}` |
| Goose | `goose` | `~/.config/goose/skills/{skill}` |
| iFlow CLI | `iflow-cli` | `~/.iflow/skills/{skill}` |
| Junie | `junie` | `~/.junie/skills/{skill}` |
| Kilo Code | `kilo` | `~/.kilocode/skills/{skill}` |
| Kimi Code CLI | `kimi-cli` | `~/.config/agents/skills/{skill}` |
| Kiro CLI | `kiro-cli` | `~/.kiro/skills/{skill}` |
| Kode | `kode` | `~/.kode/skills/{skill}` |
| MCPJam | `mcpjam` | `~/.mcpjam/skills/{skill}` |
| Mistral Vibe | `mistral-vibe` | `~/.vibe/skills/{skill}` |
| Mux | `mux` | `~/.mux/skills/{skill}` |
| Neovate | `neovate` | `~/.neovate/skills/{skill}` |
| OpenClaw | `openclaw` | `~/.openclaw/skills/{skill}` |
| OpenCode | `opencode` | `~/.config/opencode/skills/{skill}` |
| OpenHands | `openhands` | `~/.openhands/skills/{skill}` |
| Pi | `pi` | `~/.pi/agent/skills/{skill}` |
| Pochi | `pochi` | `~/.pochi/skills/{skill}` |
| Qoder | `qoder` | `~/.qoder/skills/{skill}` |
| Qwen Code | `qwen-code` | `~/.qwen/skills/{skill}` |
| Replit | `replit` | `~/.config/agents/skills/{skill}` |
| Roo Code | `roo` | `~/.roo/skills/{skill}` |
| Trae | `trae` | `~/.trae/skills/{skill}` |
| Trae CN | `trae-cn` | `~/.trae-cn/skills/{skill}` |
| Universal | `universal` | `~/.config/agents/skills/{skill}` |
| Windsurf | `windsurf` | `~/.codeium/windsurf/skills/{skill}` |
| Zencoder | `zencoder` | `~/.zencoder/skills/{skill}` |

</details>

## Architecture

| Component | Directory | Package | Description |
|-----------|-----------|---------|-------------|
| CLI | `client/` | [`dhub-cli`](https://pypi.org/project/dhub-cli/) | Open-source CLI (Typer + Rich) |
| Server | `server/` | `decision-hub-server` | Backend API (FastAPI on Modal) |
| Shared | `shared/` | `dhub-core` | Domain models and SKILL.md parsing |
| Frontend | `frontend/` | — | Web UI at [hub.decision.ai](https://hub.decision.ai) (React + TypeScript) |

**Stack:** Python 3.11+ / PostgreSQL / S3 / Modal / Gemini (search) / Anthropic (eval judging)

## Development

```bash
# Clone and install
git clone https://github.com/pymc-labs/decision-hub.git
cd decision-hub
uv sync --all-packages --all-extras
make install-hooks
```

```bash
make help          # see all available targets
make test          # run all tests (client + server + frontend)
make lint          # ruff check + format + frontend lint
make typecheck     # mypy
make fmt           # auto-fix + format
```

### Local development

For fully isolated local development with its own database and S3:

```bash
make deploy-local    # start Postgres + MinIO + API + frontend
# Open http://localhost:5173

make local-down      # stop (data preserved)
make local-reset     # stop and destroy all data
```

Requires Docker Desktop.

### Configuration

Copy `server/.env.example` to `server/.env.dev` and fill in your values. The project has three environments controlled by `DHUB_ENV` (`dev` | `prod` | `local`). See [`CLAUDE.md`](CLAUDE.md) for detailed development guidelines.

## Security

If you discover a security vulnerability, please report it responsibly via [SECURITY.md](SECURITY.md). **Do not** open a public GitHub issue.

## License

MIT — see [LICENSE](LICENSE).
