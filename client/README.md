# dhub-cli: The Package Manager for AI Agent Skills

**Decision Hub** is a CLI-first registry for publishing, discovering, and installing *Skills* — modular packages of code and prompts that AI coding agents (Claude, Cursor, Codex, Gemini, OpenCode) can use. Think `npm` or `cargo` for agent capabilities.

## Why Decision Hub?

- **🏢 Organization Namespaces:** Publish skills to your GitHub organization's namespace (`acme-corp/deploy-tool`) for your team to use. Zero config—just login and publish.
- **🛡️ Secure by Default:** Every skill runs in an isolated environment (via `uv`) and passes a "Security Gauntlet" scan before publishing. No more running untrusted code on your bare metal.
- **⚡ Agent-Agnostic:** Install a skill once, and it's instantly available to all your AI agents (Claude, Cursor, Gemini).
- **🧪 Automated Evals:** Skills aren't just hosted; they're graded. Automated sandboxed evaluations ensure skills actually work before you install them.
- **🧠 Natural Language Search:** Don't remember the package name? Just `dhub ask "tool to analyze logs"` and let the LLM find it for you.
- **🔓 Open Source & Self-Hostable:** Run the public CLI or deploy your own private registry server. Your skills, your infrastructure.

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