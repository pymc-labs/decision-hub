# GitHub Skills Crawler — Technical Specification

## Problem

Skills for AI coding agents (Claude Code, Codex, Copilot, etc.) are scattered
across thousands of public GitHub repositories. Decision Hub needs to discover
and index them automatically so users can find and install them via `dhub`.

GitHub's Search API returns at most **1,000 results per query**, so a single
`filename:SKILL.md` search misses the long tail.

## Goals

1. Discover the maximum number of public repos containing valid `SKILL.md`
   files, working around the 1K-result limit.
2. For each repo, create the owner's **organization** in Decision Hub (if it
   doesn't exist) and save the owner's **public email**.
3. **Publish** every valid skill found under that org, with proper versioning and
   S3 storage.
4. Be **resumable** — if the crawler crashes or is killed, it should restart
   from where it left off without reprocessing.
5. Use a dedicated **`dhub-crawler` service account** that can publish into any
   org.

## Non-goals

- Real-time/webhook-based discovery (this is a batch script).
- Running the full Gauntlet safety pipeline (LLM judge) on crawled skills. All
  crawled skills get `eval_status = "pending"`.
- Authenticating as the actual repo owner. The crawler uses a bot account.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                   CLI entry point                                   │
│   python -m decision_hub.scripts.github_crawler                     │
│   --github-token  --max-repos  --env  --strategies  --resume/--fresh│
└───────────────┬─────────────────────────────────────────────────────┘
                │
    ┌───────────▼───────────┐
    │  Phase 1: Discovery   │   ← GitHub Search API (read-only)
    │  (5 strategies)       │
    │                       │
    │  Output: dict of      │
    │  DiscoveredRepo       │
    └───────────┬───────────┘
                │
    ┌───────────▼───────────┐
    │  Checkpoint (JSON)    │   ← Persisted to disk after discovery
    │  crawl_checkpoint.json│      and after each repo is processed
    └───────────┬───────────┘
                │
    ┌───────────▼───────────┐
    │  Phase 2: Processing  │   ← DB + S3 writes
    │  For each repo:       │
    │   1. Fetch owner email│
    │   2. Ensure org + bot │
    │   3. Clone repo       │
    │   4. Discover skills  │
    │   5. Publish to DB+S3 │
    │   6. Flush checkpoint │
    └───────────────────────┘
```

---

## Discovery strategies

### Why multiple strategies?

GitHub Code Search caps at 1,000 results per query. A single
`filename:SKILL.md` query saturates this limit. By splitting the search space
along orthogonal dimensions, each sub-query stays under 1K and the union
covers far more of the corpus.

### Strategy 1: File-size partitioning

Split `filename:SKILL.md` into non-overlapping byte-size ranges:

| Range        | Query suffix         |
|-------------|----------------------|
| 0–500 B     | `size:0..500`        |
| 501–1000 B  | `size:501..1000`     |
| 1001–2000 B | `size:1001..2000`    |
| 2001–5000 B | `size:2001..5000`    |
| 5001–10 KB  | `size:5001..10000`   |
| 10–50 KB    | `size:10001..50000`  |
| >50 KB      | `size:>50001`        |

7 queries × up to 1,000 results each = up to 7,000 unique repos.

### Strategy 2: Path-based search

Skills follow predictable directory conventions. Search each path separately:

- `filename:SKILL.md path:skills`
- `filename:SKILL.md path:.claude`
- `filename:SKILL.md path:.codex`
- `filename:SKILL.md path:.github`
- `filename:SKILL.md path:agent-skills`

5 queries, overlaps with Strategy 1 (deduplicated by `full_name`).

### Strategy 3: Topic-based discovery

Search for repos tagged with skill-related GitHub topics:

```
topic:agent-skills, topic:claude-skills, topic:ai-agent-skills,
topic:claude-code-skills, topic:codex-skills, topic:copilot-skills,
topic:cursor-skills, topic:windsurf-skills
```

Uses `/search/repositories` (not code search), capped at 5 pages × 100 per
topic. These repos are discovered even if their SKILL.md is in a non-standard
path.

### Strategy 4: Fork scanning

After discovery, take the 10 highest-starred repos and enumerate their forks
via `GET /repos/{owner}/{repo}/forks`. Forks often contain additional or
modified skills.

Capped at 3 pages (300 forks) per source repo.

### Strategy 5: Curated list parsing

Fetch the README from well-known awesome-lists:

- `skillmatic-ai/awesome-agent-skills`
- `hoodini/ai-agents-skills`
- `CommandCodeAI/agent-skills`
- `heilcheng/awesome-agent-skills`

Extract all `github.com/{owner}/{repo}` links via regex, then fetch each
repo's metadata via `GET /repos/{owner}/{repo}`.

### Deduplication

All strategies return `dict[str, DiscoveredRepo]` keyed by `full_name`
(e.g. `"owner/repo"`). The orchestrator merges them with `dict.update()`, so
repos discovered by multiple strategies appear only once.

---

## The `dhub-crawler` bot user

### Why a dedicated bot?

The server's permission model requires a `user_id` to:
- Own organizations (`organizations.owner_id`)
- Be an org member (`org_members.user_id + role`)
- Be recorded as publisher (`versions.published_by`)

The crawler doesn't run on behalf of any real GitHub user. Instead it uses a
synthetic bot account:

| Field       | Value          |
|------------|----------------|
| `github_id` | `"0"`          |
| `username`  | `"dhub-crawler"` |

### How it gets publish rights

For **new orgs** the crawler creates: the bot is inserted as `role="owner"`.

For **pre-existing orgs** (created by a real user via `dhub login`): the bot
is inserted as `role="admin"` if it's not already a member. This ensures it
can publish via the normal `require_org_membership()` auth path if needed in
the future.

The current implementation bypasses the HTTP API and writes directly to DB + S3,
so membership is technically not checked. But adding the bot as a member keeps
the data model consistent and future-proofs against switching to API-based
publishing later.

---

## Checkpoint / resume design

### Problem

A full crawl can take hours (rate limits, cloning, etc.). If the process dies
at repo 450 of 2,000, we don't want to redo discovery or reprocess the first
449 repos.

### Solution: JSON checkpoint file

```json
{
  "discovered_repos": {
    "owner/repo1": {"full_name": "...", "owner_login": "...", ...},
    "owner/repo2": {...}
  },
  "processed_repos": ["owner/repo1", "owner/repo2", ...]
}
```

**Write points:**
1. After discovery phase completes → saves all `discovered_repos`.
2. After each repo is successfully processed → appends to `processed_repos`
   and flushes to disk.

**On `--resume`:**
1. Load checkpoint from disk.
2. Skip discovery entirely — use cached `discovered_repos`.
3. Build a set of `processed_repos` and filter them out of the work queue.
4. Process only the remaining repos.

**On `--fresh`:**
1. Delete the checkpoint file if it exists.
2. Run full discovery + processing from scratch.

**Default (no flag):**
1. Run full discovery (overwrites `discovered_repos` in checkpoint).
2. Process all repos (no filtering), updating `processed_repos` as we go.

### Crash safety

After each repo is processed, we:
1. `conn.commit()` — the DB writes are durable.
2. `checkpoint.mark_processed(repo, path)` — flushes to disk.

If the process crashes between these two, at worst we reprocess one repo on
resume — but `publish_skill_to_db` is idempotent (skips if checksum matches),
so no duplicates.

---

## Publishing pipeline

For each skill directory found in a cloned repo:

1. **Parse manifest**: `parse_skill_md(skill_dir / "SKILL.md")` → `SkillManifest`
2. **Validate name**: `validate_skill_name(manifest.name)` — rejects invalid names
3. **Create zip**: In-memory zip of the skill directory (excluding dotfiles, `__pycache__`)
4. **Compute checksum**: SHA-256 of the zip bytes
5. **Upsert skill record**: `find_skill()` → `insert_skill()` or `update_skill_description()`
6. **Determine version**:
   - If no previous version exists → `0.1.0`
   - If latest version has same checksum → **skip** (idempotent)
   - Otherwise → bump patch (e.g. `0.1.0` → `0.1.1`)
7. **Upload to S3**: `skills/{org}/{name}/{version}.zip`
8. **Insert version record**: With `eval_status="pending"`, `published_by="dhub-crawler"`

### Why bypass the HTTP API?

- No JWT needed (the bot has no GitHub OAuth token).
- No Gauntlet overhead (we intentionally skip LLM safety analysis for
  crawled skills — they get `eval_status="pending"` and can be evaluated
  separately).
- Direct DB+S3 access is simpler and faster for batch operations.

---

## Organization + email handling

For each discovered repo:

1. Convert `owner_login` to lowercase → org `slug`.
2. Validate against slug regex (`^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$`).
3. `find_org_by_slug()`:
   - **Not found** → `insert_organization(slug, bot_user_id, is_personal=False)` + add bot as owner.
   - **Found** → check if bot is a member; if not, add as admin.
4. Fetch public email via `GET /users/{login}` or `GET /orgs/{login}` → `data["email"]`.
5. If email is non-empty and org has no email yet → `update_org_email()`.

The email is stored on the `organizations.email` column (nullable `TEXT`,
added by migration).

---

## Rate limiting

### GitHub API rate limits

| Endpoint type     | Unauthenticated | Authenticated (PAT) |
|-------------------|----------------:|---------------------:|
| REST API          | 60/hour         | 5,000/hour           |
| Code Search       | 10/min          | 30/min               |
| Repo Search       | 10/min          | 30/min               |

### Handling

The `GitHubClient` class:
1. Reads `x-ratelimit-remaining` and `x-ratelimit-reset` from every response.
2. If `remaining < 3` → sleeps until reset time before the next request.
3. If a 403 with "rate limit" in the body is received → sleeps and retries once.
4. Code search pages have a `time.sleep(2)` between them.
5. Topic search pages have a `time.sleep(1)`.

A GitHub PAT is strongly recommended (`--github-token`).

---

## Database changes

### New column: `organizations.email`

```sql
ALTER TABLE organizations ADD COLUMN email TEXT;
```

- Nullable — most orgs won't have a public email.
- Migration script: `python -m decision_hub.scripts.migrate_add_org_email`
- Model updated: `Organization.email: str | None = None`
- New query: `update_org_email(conn, org_id, email)`

---

## CLI interface

```
python -m decision_hub.scripts.github_crawler [OPTIONS]

Options:
  --github-token TEXT       GitHub PAT (recommended)
  --max-repos INT           Cap on repos to process
  --env {dev,prod}          Decision Hub environment (default: dev)
  --strategies {size,path,topic,fork,curated} [...]
                            Which strategies to run (default: all)
  --checkpoint PATH         Checkpoint file path (default: crawl_checkpoint.json)
  --resume                  Resume from checkpoint
  --fresh                   Delete checkpoint and start over
```

`--resume` and `--fresh` are mutually exclusive.

---

## Error handling

| Failure                          | Behaviour                                    |
|----------------------------------|----------------------------------------------|
| GitHub API 422 on search query   | Log warning, skip that query, continue       |
| GitHub API 403 (rate limit)      | Sleep until reset, retry once                |
| Invalid org slug                 | Log warning, skip repo                       |
| `clone_repo()` fails             | Log error, record in `stats.errors`, continue|
| `parse_skill_md()` fails         | Log warning, skip that skill, continue       |
| `validate_skill_name()` fails    | Log warning, count as `skills_failed`        |
| S3 upload fails                  | Exception propagates, repo marked as error   |
| DB write fails                   | Exception propagates, repo marked as error   |
| Process killed                   | Resume from checkpoint on next run           |

---

## Future enhancements (not in scope)

- **Incremental re-crawls**: Track `pushed_at` timestamps per repo and only
  re-process repos that changed since the last crawl.
- **Gauntlet evaluation**: Run the safety pipeline on crawled skills in a
  separate batch job.
- **Token rotation**: Support multiple GitHub PATs for higher throughput.
- **Webhook-triggered crawl**: Listen for GitHub events instead of polling.
- **Parallel processing**: Clone and publish multiple repos concurrently.
