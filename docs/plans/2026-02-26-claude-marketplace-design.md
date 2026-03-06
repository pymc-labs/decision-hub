# Decision Hub as a Claude Plugin Marketplace

**Date**: 2026-02-26
**Status**: Approved

## Problem

Claude Code has a plugin ecosystem with ~40 official plugins. Decision Hub has a growing registry of AI skills with safety guarantees (gauntlet), automated evals, version tracking, and natural language search. These skills use SKILL.md — already Claude's native skill format — but aren't discoverable through Claude's `/plugin` TUI.

## Goal

Make Decision Hub a native Claude plugin marketplace. Users run `claude plugin marketplace add https://hub.decision.ai/marketplace.git` and all top Decision Hub skills appear as installable Claude plugins.

## Value Proposition

1. **Safety + Quality**: Gauntlet grades (A/B/C/F), automated evals, version tracking. The official marketplace has none of this.
2. **Scale + Discovery**: Decision Hub has a crawler, natural language search, categories, and a growing index. Far richer catalog than the official ~40 plugins.
3. **Multi-agent bridge**: Skills published to Decision Hub work with 40+ agents, not just Claude. Authors publish once, reach everywhere.

## Architecture

### Virtual Git Marketplace Endpoint

Claude marketplaces are git-based. Rather than maintaining a physical GitHub repo (which doesn't scale), Decision Hub serves a **virtual git repo** via the Git Smart HTTP protocol. Claude Code thinks it's cloning a repo; it's actually querying Decision Hub's API.

```
Claude Code                        Decision Hub (Modal)
    |                                     |
    | git clone hub.decision.ai/          |
    |         marketplace.git             |
    |------------------------------------>|
    |                                     |  1. Query DB for top 1000 skills
    |                                     |  2. Build dulwich MemoryRepo:
    |                                     |     - marketplace.json
    |                                     |     - plugins/org--skill/
    |                                     |         .claude-plugin/plugin.json
    |                                     |         skills/name/SKILL.md
    |                                     |  3. Serve via dulwich WSGI
    |<------------------------------------|
    |  packfile with all files            |
    |                                     |
    | (auto-update later: git fetch)      |
    |------------------------------------>|
    |                                     |  Same flow, incremental
    |<------------------------------------|
```

### Git Smart HTTP Protocol

Git over HTTP uses two endpoints:

- `GET /marketplace.git/info/refs?service=git-upload-pack` — "What refs do you have?"
- `POST /marketplace.git/git-upload-pack` — "Send me these objects"

Python's **dulwich** library provides `MemoryRepo` + `HTTPGitApplication` that implements this protocol. We build the repo in memory from DB data, dulwich serves it.

### Caching Strategy

1. Build the MemoryRepo once on first request, cache in container memory (~6MB)
2. Store a `marketplace_generation` counter in DB (incremented on every publish/unpublish)
3. On each request, check if counter changed (with 5-minute TTL to avoid DB hits)
4. If changed, rebuild the repo; otherwise serve from cache

### Curation

**Top 1000 skills** by download count. Filters:
- Public visibility only
- Gauntlet grade != F (A, B, C included)
- Sorted by download count descending

This keeps the marketplace at ~6MB (manageable for git clone) and the `/plugin` TUI responsive.

For the full catalog beyond 1000, users use `dhub ask`, `dhub install`, or the web UI.

## Skill-to-Plugin Mapping

Each Decision Hub skill becomes a Claude plugin with this structure:

```
plugins/<org>--<skill>/
  .claude-plugin/
    plugin.json          <- generated from skill metadata
  skills/
    <skill>/
      SKILL.md           <- extracted from S3 ZIP, unchanged
```

No content transformation needed — SKILL.md is already Claude's native skill format.

### Naming Convention

Plugin name: `<org_slug>--<skill_name>` (double dash separates org from skill, since both can contain single hyphens).

In Claude, the skill appears as: `/pymc-labs--bayesian-modeling:bayesian-modeling`

### Generated plugin.json

```json
{
  "name": "pymc-labs--bayesian-modeling",
  "version": "1.2.0",
  "description": "Bayesian statistical modeling with PyMC",
  "author": {"name": "pymc-labs"},
  "repository": "https://github.com/pymc-labs/skills",
  "keywords": ["data-science", "safety-grade-A", "evals-passing"]
}
```

### Generated marketplace.json Entry

```json
{
  "name": "pymc-labs--bayesian-modeling",
  "source": "./plugins/pymc-labs--bayesian-modeling",
  "description": "Bayesian statistical modeling with PyMC",
  "version": "1.2.0",
  "category": "data-science",
  "tags": ["safety-A", "evals-passing", "downloads-1200"]
}
```

## Implementation Components

### 1. New server module: `decision_hub/infra/git_marketplace.py`

Responsibilities:
- Query DB for top 1000 public skills by downloads (grade != F)
- Fetch SKILL.md content from S3 for each skill
- Build a dulwich `MemoryRepo` with marketplace.json + plugin directories
- Cache the repo in memory with TTL-based invalidation

### 2. New API mount: `/marketplace.git/`

Mount dulwich's `HTTPGitApplication` as a WSGI sub-app in FastAPI via `starlette.middleware.wsgi.WSGIMiddleware`. Handles the two git smart HTTP endpoints.

### 3. DB changes: marketplace generation counter

A lightweight table or config row that tracks when the marketplace needs regeneration. Incremented on publish/unpublish/delete.

### 4. Publish pipeline integration

After a successful publish, bump the marketplace generation counter so the next git fetch picks up the new skill.

## End-to-End User Flow

```
1. Setup (one-time):
   claude plugin marketplace add https://hub.decision.ai/marketplace.git

2. Browse:
   /plugin -> Discover tab -> See Decision Hub skills
   -> Each shows name, description, category, safety grade tags

3. Install:
   Click install -> Plugin cached locally
   -> SKILL.md loaded as a slash command

4. Use:
   /pymc-labs--bayesian-modeling:bayesian-modeling "Fit a model to this data"

5. Auto-update:
   Claude Code periodically git-fetches the marketplace
   -> New/updated skills appear automatically
```

## Out of Scope (for now)

- **MCP plugin** with search/install tools — future follow-up
- **Per-org marketplaces** — possible later extension
- **Runtime skills** (Python entrypoint, dependencies) — prompt-only SKILL.md first
- **Private skills** — public only for the marketplace
- **Bidirectional sync** (importing Claude plugins into Decision Hub)

## Dependencies

- **dulwich** Python package (pure Python git implementation)
- **starlette WSGI middleware** (already a FastAPI/Starlette dependency)

## Risks

1. **dulwich MemoryRepo correctness** — need to verify that Claude Code's git client handles the smart HTTP responses correctly. Mitigation: test with `git clone` manually first.
2. **Modal container memory** — 6MB cached repo is fine; if we scale beyond 1000, monitor memory usage.
3. **S3 fetch latency on rebuild** — fetching 1000 SKILL.md files from S3 on cache rebuild. Mitigation: parallelize with ThreadPoolExecutor, cache rebuild is infrequent.
4. **Claude Code marketplace update frequency** — if auto-updates are infrequent, new skills take time to appear. Mitigation: users can manually update via `/plugin` Marketplaces tab.
