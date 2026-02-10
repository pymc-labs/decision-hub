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
3. **Publish** every valid skill found under that org — including the full
   **Gauntlet safety pipeline** (static checks + LLM analysis). Grade-F skills
   are quarantined, not published.
4. Be **resumable** — if the crawler crashes or is killed, it should restart
   from where it left off without reprocessing.
5. Use a dedicated **`dhub-crawler` service account** that can publish into any
   org.
6. Process repos **in parallel** on Modal (configurable workers, default 5).
7. Show a **Rich progress bar** on the CLI.
8. Be **resilient** to stuck git clones and transient failures — per-repo
   timeouts, individual failures don't block other repos.

## Non-goals

- Real-time/webhook-based discovery (this is a batch script).
- Authenticating as the actual repo owner. The crawler uses a bot account.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                 LOCAL: CLI orchestrator                               │
│  python -m decision_hub.scripts.github_crawler                       │
│  --github-token --max-repos --env --workers 5 --resume/--fresh       │
│                                                                      │
│  Phase 1: Discovery (runs locally — just HTTP calls, no disk)        │
│  ┌────────────────────────────────────────────────────────────┐      │
│  │  5 strategies → deduplicated dict[full_name, DiscoveredRepo] │      │
│  │  Saved to crawl_checkpoint.json                             │      │
│  └────────────────────────────┬───────────────────────────────┘      │
│                               │                                      │
│  Phase 2: Parallel dispatch (Rich progress bar)                      │
│  ┌────────────────────────────▼───────────────────────────────┐      │
│  │  For each batch of N repos:                                 │      │
│  │    modal fn.map(batch) → stream results back                │      │
│  │    Update progress bar + checkpoint after each result       │      │
│  └────────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │  MODAL: Worker pool   │
                    │  N containers (=workers)│
                    │  timeout=300s each     │
                    │                        │
                    │  Each worker:          │
                    │  1. Clone repo (git)   │
                    │  2. Discover SKILL.md  │
                    │  3. For each skill:    │
                    │     a. Parse manifest  │
                    │     b. Create zip      │
                    │     c. Run Gauntlet    │
                    │     d. Publish or      │
                    │        quarantine      │
                    │  4. Return result dict │
                    └───────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │  Shared infrastructure │
                    │  PostgreSQL (Supabase) │
                    │  S3 (AWS)             │
                    │  Gemini (Gauntlet LLM)│
                    └───────────────────────┘
```

### Why this split?

| Concern              | Runs where | Why                                    |
|---------------------|------------|----------------------------------------|
| GitHub API discovery | Local      | Lightweight HTTP calls, needs GH token |
| Progress bar + UX    | Local      | User's terminal                        |
| Checkpoint file      | Local      | Simple JSON, user can inspect/edit     |
| Git clone + disk     | Modal      | Ephemeral disk, user has no space      |
| Gauntlet (Gemini)    | Modal      | Secrets already configured there       |
| DB + S3 writes       | Modal      | Secrets already configured there       |

---

## Discovery strategies

(Unchanged from previous spec — 5 strategies: file-size partitioning,
path-based search, topic-based discovery, fork scanning, curated list parsing.
All run locally using the `GitHubClient` class.)

### Strategy 1: File-size partitioning

Split `filename:SKILL.md` into non-overlapping byte-size ranges (7 queries,
up to 7K unique repos).

### Strategy 2: Path-based search

Target common skill paths: `skills/`, `.claude/`, `.codex/`, `.github/`,
`agent-skills/`.

### Strategy 3: Topic-based discovery

Search repos by GitHub topics (`agent-skills`, `claude-skills`, etc.).

### Strategy 4: Fork scanning

Enumerate forks of the top-10 most-starred discovered repos.

### Strategy 5: Curated list parsing

Parse READMEs from known awesome-lists for GitHub repo links.

### Deduplication

All strategies return `dict[str, DiscoveredRepo]` keyed by `full_name`.
The orchestrator merges with `dict.update()`.

---

## Modal worker function

### Definition (in `modal_app.py`)

```python
@app.function(
    image=crawler_image,      # base image + git
    secrets=secrets,          # DB, S3, Gemini credentials
    timeout=300,              # 5-minute hard kill per repo
)
def crawl_process_repo(repo_dict: dict, github_token: str | None = None) -> dict:
    ...
```

### Why a separate image?

The base `image` doesn't have `git` installed (only Python packages). The
crawler image extends it with `apt_install("git")` so `git clone` works
inside the container.

### Input: `repo_dict`

```python
{
    "full_name": "owner/repo",
    "owner_login": "owner",
    "owner_type": "Organization",
    "clone_url": "https://github.com/owner/repo.git",
    "stars": 42,
    "description": "...",
}
```

### Output: result dict

```python
{
    "repo": "owner/repo",
    "status": "ok" | "error" | "no_skills" | "skipped",
    "skills_published": 3,
    "skills_skipped": 1,
    "skills_failed": 0,
    "org_created": True,
    "email_saved": True,
    "error": None,              # or error message string
}
```

### Processing pipeline per repo

```
1. Validate owner_login → org slug
2. Fetch owner email (GitHub API, using github_token if provided)
3. Ensure org exists in DB + bot is admin
4. git clone --depth 1 (with 120s subprocess timeout)
5. Walk directory tree → find SKILL.md files
6. For each skill directory:
   a. parse_skill_md() → manifest
   b. validate_skill_name()
   c. Create zip + compute checksum
   d. Check if latest version has same checksum → skip if unchanged
   e. extract_for_evaluation() → skill_md_content, source_files, lockfile
   f. Run Gauntlet (static checks + Gemini LLM analysis)
   g. If Grade F: quarantine to rejected/ S3, insert audit log, skip
   h. Otherwise: upload to skills/ S3, insert version with eval_status=grade
   i. Insert audit log
7. Cleanup temp directory
8. Return result dict
```

### Resilience

| Failure                      | Handling                                        |
|------------------------------|-------------------------------------------------|
| `git clone` hangs >120s     | `subprocess.TimeoutExpired` → caught, error     |
| `git clone` network error   | Exception caught, repo status = "error"         |
| SKILL.md parse failure       | Caught per-skill, other skills still processed  |
| Gauntlet Gemini API failure  | Falls back to regex-only static checks          |
| S3 upload failure            | Exception propagates, repo status = "error"     |
| DB write failure             | Exception propagates, repo status = "error"     |
| Modal 300s timeout           | Container killed, fn.map returns exception      |
| Any unhandled exception      | `return_exceptions=True` in fn.map catches it   |

---

## Gauntlet integration

Crawled skills go through the **same safety pipeline** as manually published
skills. This is the `run_gauntlet_pipeline()` function from
`registry_service.py`:

1. **Static checks** — regex-based detection of dangerous patterns (shell
   injection, credential exfiltration, etc.)
2. **LLM analysis** — Gemini reviews code snippets and prompt text for safety
   (requires `google_api_key` in settings; skipped if not configured)
3. **Grading** — A (clean) / B (minor issues) / C (risky) / F (rejected)

### Grade handling

| Grade | Action                                                         |
|-------|----------------------------------------------------------------|
| A / B | Publish to `skills/{org}/{name}/{version}.zip`, `eval_status=grade` |
| C     | Publish to `skills/{org}/{name}/{version}.zip`, `eval_status="C"` |
| F     | Quarantine to `rejected/{org}/{name}/{version}.zip`, skip publish |

All grades get an audit log entry via `insert_audit_log()`.

### Why run Gauntlet on crawled skills?

Without it, any malicious skill discovered on GitHub would be immediately
installable via `dhub install`. The Gauntlet is the safety gate — it's the
same bar as manually published skills.

---

## Parallel processing with Modal

### Dispatch pattern

```python
fn = modal.Function.from_name(settings.modal_app_name, "crawl_process_repo")

for batch_start in range(0, len(pending_repos), workers):
    batch = pending_repos[batch_start:batch_start + workers]
    batch_dicts = [repo_to_dict(r) for r in batch]

    for result in fn.map(batch_dicts, return_exceptions=True):
        # Update progress bar
        # Update checkpoint
        # Accumulate stats
```

### Why batch-of-N instead of one giant `.map()` call?

- **Controllable parallelism**: the user sets `--workers N` and we process
  exactly N repos concurrently at any time.
- **Checkpoint granularity**: after each batch, we flush processed repos to
  the checkpoint file. A giant `.map()` would only update after ALL repos
  complete.
- **Backpressure**: if Modal hits container limits, we wait for the current
  batch before starting the next.

### Worker timeout

Each Modal function invocation has `timeout=300` (5 minutes). This is the
hard kill. Inside the function, `git clone` has a 120s subprocess timeout
for early detection. A repo with 10+ skills might need the full 5 minutes
for gauntlet runs.

---

## The `dhub-crawler` bot user

### Identity

| Field       | Value          |
|------------|----------------|
| `github_id` | `"0"`          |
| `username`  | `"dhub-crawler"` |

### Permissions

- **Owner** of every org the crawler creates.
- **Admin** of every pre-existing org the crawler touches (added idempotently).
- Recorded as `published_by="dhub-crawler"` on all versions.

The bot user is created in the DB during Phase 2 setup (before dispatching
to Modal). Its `user_id` is passed to Modal workers as a string argument.

---

## Checkpoint / resume design

### JSON checkpoint file (local)

```json
{
  "discovered_repos": {
    "owner/repo1": {"full_name": "...", "owner_login": "...", ...},
    "owner/repo2": {...}
  },
  "processed_repos": ["owner/repo1", "owner/repo2", ...]
}
```

### Write points

1. After discovery phase → saves all `discovered_repos`.
2. After each Modal batch completes → appends processed repos and flushes.

### On `--resume`

1. Load checkpoint, skip discovery.
2. Filter out already-processed repos.
3. Process only remaining repos.

### Crash safety

Publishing is idempotent (checksum comparison). Reprocessing a repo on resume
at worst re-runs the gauntlet and gets the same result.

---

## Progress bar (Rich)

```
Discovering repos...  ━━━━━━━━━━━━━━━━━━━━━━━━ 100% (5/5 strategies)
Processing repos      ━━━━━━━━━━━━╸━━━━━━━━━━━  47% 235/500 • 12 published • 3 failed
```

Uses `rich.progress.Progress` with:
- A task for discovery (indeterminate spinner → completes with repo count)
- A task for processing (determinate bar, advances by 1 per repo)
- Status columns showing published/failed/skipped counts

---

## CLI interface

```
python -m decision_hub.scripts.github_crawler [OPTIONS]

Options:
  --github-token TEXT       GitHub PAT (recommended for rate limits)
  --max-repos INT           Cap on repos to process
  --env {dev,prod}          Decision Hub environment (default: dev)
  --workers INT             Max parallel Modal workers (default: 5)
  --strategies STR [...]    size, path, topic, fork, curated (default: all)
  --checkpoint PATH         Checkpoint file (default: crawl_checkpoint.json)
  --resume                  Resume from checkpoint
  --fresh                   Delete checkpoint, start over
```

---

## Client package dependency

The Modal worker image does NOT include the `dhub-cli` client package. The
two functions we need from it (`clone_repo`, `discover_skills`) are trivial
(~20 lines each) and are **inlined** in the crawler module to avoid pulling
in typer/rich/CLI dependencies.

`parse_skill_md` is imported from `dhub_core.manifest` (the shared package),
which IS available in the Modal image.

---

## Database changes

### New column: `organizations.email`

```sql
ALTER TABLE organizations ADD COLUMN email TEXT;
```

- Nullable — most orgs won't have a public email.
- Migration: `python -m decision_hub.scripts.migrate_add_org_email`
- Model: `Organization.email: str | None = None`
- Query: `update_org_email(conn, org_id, email)`

---

## Files changed

| File | Change |
|------|--------|
| `server/modal_app.py` | Add `crawl_process_repo` function + `crawler_image` |
| `server/src/decision_hub/scripts/github_crawler.py` | Rewrite: Modal dispatch, Rich progress, inline git ops, Gauntlet |
| `server/src/decision_hub/models.py` | Add `email` to `Organization` |
| `server/src/decision_hub/infra/database.py` | Add `email` column + `update_org_email()` |
| `server/src/decision_hub/scripts/migrate_add_org_email.py` | Migration script |

---

## Future enhancements (not in scope)

- **Incremental re-crawls**: Track `pushed_at` per repo, only re-process changed repos.
- **Token rotation**: Multiple GitHub PATs for higher throughput.
- **Webhook-triggered crawl**: Listen for GitHub events instead of polling.
