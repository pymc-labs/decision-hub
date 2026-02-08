# dhub

The CLI package manager for AI agent skills.

`dhub` lets you publish, discover, and install **Skills** — modular capabilities (code + prompts) that agents like Claude, Cursor, and Gemini can use.

## Installation

```bash
# Via uv
uv tool install dhub-cli

# Via pipx
pipx install dhub-cli
```

## Quick Start

```bash
# Authenticate via GitHub
dhub login

# Publish a skill
dhub publish --org my-org --name my-skill --version 1.0.0

# Install a skill
dhub install my-org/my-skill

# Search for skills
dhub ask "analyze A/B test results"

# Run a skill locally
dhub run my-org/my-skill
```

## Commands

| Command | Description |
|---------|-------------|
| `dhub login` | Authenticate via GitHub Device Flow |
| `dhub publish` | Publish a skill to the registry |
| `dhub publish-repo` | Publish all skills from a git repository |
| `dhub install` | Install a skill |
| `dhub list` | List installed skills |
| `dhub delete` | Delete a skill from the registry |
| `dhub run` | Run a locally installed skill |
| `dhub ask` | Natural language skill search |
| `dhub org` | Manage organizations |
| `dhub keys` | Manage API keys for evaluations |

## Documentation

See the [main repository](https://github.com/lfiaschi/decision-hub) for full documentation.
