# dhub-cli: The AI Skill Manager for Data Science Agents

**Decision Hub** is a CLI-first registry for publishing, discovering, and installing *Skills* — modular packages of code and prompts that AI coding agents (Claude, Cursor, Codex, Gemini, OpenCode) can use.

## Why Decision Hub?

**Agents that extend themselves.** Install Decision Hub as a skill into any supported agent, and the agent can discover new skills in natural language — then install and use them mid-conversation without human intervention.

**Publish from anywhere.** Point `dhub publish` at a local directory or a GitHub repo URL and every valid `SKILL.md` inside is discovered, versioned, and published.

**Private skills for your team.** Skills can be scoped to your GitHub organization so proprietary tooling stays internal.

**Install once, use everywhere.** A single `dhub install` symlinks a skill into every agent's skill directory — Claude, Cursor, Codex, Gemini, OpenCode. No duplication, no per-agent setup.

**Security gauntlet.** Every publish is scanned for dangerous patterns. Skills get a trust grade (A/B/C/F) before they reach the registry.

**Automated evals in sandboxes.** Skills ship with eval cases that run on publish in isolated sandboxes, scored by an LLM judge.

**Executable skills with SKILL.md.** Builds on the [Agent Skills spec](https://agentskills.io/specification) with `runtime` and `evals` blocks — skills are runnable programs, not just static prompts.

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

# 2. Search for skills using natural language
dhub ask "analyze A/B test results"

# 3. Install a skill for all your agents
dhub install pymc-labs/causalpy

# 4. Scaffold a new skill
dhub init my-new-skill

# 5. Publish it under your namespace
# (Run this inside the skill directory)
dhub publish .
```

## Supported Agents

Skills are installed as symlinks into each agent's skill directory, making them immediately available:

- **Claude:** `~/.claude/skills`
- **Cursor:** `~/.cursor/skills`
- **Gemini:** `~/.gemini/skills`
- **OpenCode:** `~/.config/opencode/skills`

## Documentation

For full documentation on creating skills, the `SKILL.md` format, and running your own registry server, see the [main repository](https://github.com/lfiaschi/decision-hub).