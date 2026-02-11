# PR #16 — GitHub Skills Crawler

## Overview

The GitHub Skills Crawler discovers public repositories containing `SKILL.md` files across GitHub and publishes them into Decision Hub through the full Gauntlet safety pipeline. It must handle **~170k potential repos** — discovery runs locally (lightweight GitHub API calls), while the heavy work (git clone, Gauntlet, publish) fans out across Modal containers that scale horizontally.

Five complementary discovery strategies work around GitHub's Search API 1,000-result-per-query limit. Processing uses Modal's `.map()` with a configurable `concurrency_limit` to saturate as many containers as needed. A local checkpoint file makes the process crash-safe and resumable at any point. A `--max-skills` CLI flag caps the number of skills published (useful for test runs), but the architecture assumes unbounded scale by default.

This feature is **experimental** and designed for easy removal (see Notes).

## Archived Branch

- Branch: `claude/github-skills-crawler-3ukIQ`
- Renamed to: `REIMPLEMENTED/claude/github-skills-crawler-3ukIQ`
- Original PR: #16

## Schema Changes

### SQL Migration

The `email` column on `organizations` is independently useful (not crawler-specific). Implement it as a standalone migration, ideally during PR #14 or earlier. If it hasn't landed yet, include it here.

```sql
-- YYYYMMDD_HHMMSS_add_org_email.sql
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS email TEXT;
```

- Nullable (`TEXT` without `NOT NULL`) — most orgs will not have a public email.
- Idempotent via `IF NOT EXISTS`.

### SQLAlchemy Model Updates

**`server/src/decision_hub/infra/database.py`** — add column to `organizations_table`:

```python
organizations_table = Table(
    "organizations",
    metadata,
    # ... existing columns ...
    Column("is_personal", Boolean, nullable=False, server_default="false"),
    Column("email", Text, nullable=True),  # NEW
)
```

**`server/src/decision_hub/models.py`** — add field to `Organization` dataclass:

```python
@dataclass(frozen=True)
class Organization:
    id: UUID
    slug: str
    owner_id: UUID
    is_personal: bool = False
    email: str | None = None  # NEW
```

**`_row_to_organization` mapper** — pass the new field:

```python
def _row_to_organization(row: sa.Row) -> Organization:
    return Organization(
        id=row.id, slug=row.slug, owner_id=row.owner_id,
        is_personal=row.is_personal, email=row.email,
    )
```

**New query function** — `update_org_email`:

```python
def update_org_email(conn: Connection, org_id: UUID, email: str) -> None:
    """Update the public email for an organization."""
    stmt = (
        sa.update(organizations_table)
        .where(organizations_table.c.id == org_id)
        .values(email=email)
    )
    conn.execute(stmt)
```

## API Changes

None. This is a background batch script, not a REST API feature.

## CLI Changes

The crawler is invoked as a Python module from the `server/` directory:

```
DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler [OPTIONS]
```

### Arguments and Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--github-token TEXT` | `str` | `$GITHUB_TOKEN` env var | GitHub PAT (reads from env by default; forwarded to Modal containers for email lookups) |
| `--max-skills INT` | `int` | `None` (unlimited) | Stop after publishing this many skills (for testing on a small batch) |
| `--env {dev,prod}` | `str` | `dev` | Decision Hub environment |
| `--concurrency INT` | `int` | `50` | Max parallel Modal containers (sets `concurrency_limit` on the Modal function) |
| `--strategies STR [...]` | `list[str]` | all 5 | Subset of: `size`, `path`, `topic`, `fork`, `curated` |
| `--checkpoint PATH` | `Path` | `crawl_checkpoint.json` | Checkpoint file path |
| `--resume` | `bool` | `False` | Resume from existing checkpoint (skip discovery) |
| `--fresh` | `bool` | `False` | Delete checkpoint and start over |
| `--dry-run` | `bool` | `False` | Run discovery only, print stats, do not process |

`--resume` and `--fresh` are mutually exclusive.

### Example Usage

```bash
# Full crawl, 50 concurrent Modal containers (default)
# Reads $GITHUB_TOKEN from env automatically
DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler

# Test run: publish only 50 skills then stop
DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler \
    --max-skills 50

# High throughput: 200 concurrent containers
DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler \
    --concurrency 200

# Discovery only — see how many repos exist without processing
DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler \
    --github-token ghp_... --dry-run

# Resume after crash
DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler \
    --resume

# Only run specific strategies
DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler \
    --strategies size path

# Explicit token override (if $GITHUB_TOKEN is not set)
DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler \
    --github-token ghp_...
```

## Architecture

### Design Principles

1. **Modal is the scaling lever.** Discovery is local (cheap HTTP), processing fans out to Modal. At 170k repos with `--concurrency 200` and ~2 min/repo, the full run takes ~28 hours wall-clock. With `--concurrency 50`, ~110 hours. The user controls this tradeoff.
2. **Checkpoint per result.** Every completed repo is written to the checkpoint immediately. A crash at repo 85,000 resumes from 85,001.
3. **Each Modal container is self-contained.** It clones one repo, opens its own DB connection, processes all skills in that repo, and dies. No shared state between containers.
4. **Idempotent everywhere.** Checksum-based skip means reprocessing a repo that was already published is a no-op. Safe to re-run, safe to resume.

### Split Architecture

```
LOCAL: CLI orchestrator (your laptop / a CI runner)
  Phase 1: Discovery (runs locally — just HTTP calls to GitHub API)
    5 strategies -> deduplicated dict[full_name, DiscoveredRepo]
    Saved to checkpoint file

  Phase 2: Fan-out to Modal
    fn.map(all_pending_repos) -> streams results back as iterator
    For each result:
      Write to checkpoint immediately
      Update Rich progress bar
      Accumulate stats

MODAL: Elastic container pool (concurrency_limit controls max parallelism)
  Each container (one per repo):
    1. Clone repo (git, 120s timeout)
    2. Discover SKILL.md files
    3. For each skill:
       a. Parse manifest, create zip, compute checksum
       b. Skip if checksum matches latest version
       c. Run Gauntlet (static + LLM)
       d. Publish or quarantine
    4. Return result dict
    5. Container dies (ephemeral disk cleaned up)

Shared infrastructure:
  - PostgreSQL (Supabase) — each container opens its own connection
  - S3 (AWS) — each container creates its own client
  - Gemini (Gauntlet LLM) — called from within each container
```

**Why this split:**

| Concern | Runs where | Why |
|---------|-----------|-----|
| GitHub API discovery | Local | Lightweight HTTP, needs GH token, rate-limit aware |
| Progress bar + UX | Local | User's terminal |
| Checkpoint file | Local | Simple JSON, user can inspect/edit |
| Git clone + disk | Modal | Ephemeral disk, no local disk pressure at 170k repos |
| Gauntlet (Gemini) | Modal | Secrets already configured, parallelizes across containers |
| DB + S3 writes | Modal | Secrets already configured, each container handles its own repos |

### Scaling Considerations

**GitHub API rate limits (discovery phase):**
- Authenticated: 5,000 requests/hr, 30 requests/min for search. A full discovery across all 5 strategies uses ~500-2,000 API calls. Fits in a single PAT's budget.
- The `GitHubClient` class tracks `x-ratelimit-remaining` and sleeps proactively when low.

**Modal container concurrency (processing phase):**
- `concurrency_limit` on the `@app.function` decorator controls max parallel containers. This is the primary throughput knob.
- Each container runs for ~1-5 min (clone + gauntlet per skill). At 170k repos, plan for 170k container invocations.
- Modal handles container scheduling, cold starts, and cleanup. No manual pool management.

**Database connection pressure:**
- Each Modal container opens its own Postgres connection via `create_engine()`. At `--concurrency 200`, that's up to 200 concurrent DB connections.
- Supabase free tier: 60 connections. Supabase Pro: 200+. The `--concurrency` flag must respect this.
- Use `NullPool` (already the default in the codebase) so each container uses exactly 1 connection.

**Checkpoint efficiency at scale:**
- The checkpoint JSON contains `discovered_repos` (170k entries, ~50MB) and `processed_repos` (a growing list of full_names).
- Writing the full checkpoint after every single result is too slow at 170k. Flush every N results (e.g. 100) or use an append-only processed log file alongside the main checkpoint.

## Implementation Details

### Discovery Strategies

All five strategies run locally using a `GitHubClient` class with built-in rate-limit handling. Each strategy returns `dict[str, DiscoveredRepo]` keyed by `full_name`. The orchestrator merges with `dict.update()`.

#### Strategy 1: File-size Partitioning

Split `filename:SKILL.md` into non-overlapping byte-size ranges (7 queries, up to 7K unique repos). This works around the 1K limit because each range is a separate query.

```python
SIZE_RANGES = [
    (0, 500),
    (501, 1000),
    (1001, 2000),
    (2001, 5000),
    (5001, 10000),
    (10001, 50000),
    (50001, None),  # unbounded upper end
]

def search_by_file_size(gh: GitHubClient, stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    repos: dict[str, DiscoveredRepo] = {}
    for lo, hi in SIZE_RANGES:
        size_q = f"size:>{lo}" if hi is None else f"size:{lo}..{hi}"
        query = f"filename:SKILL.md {size_q}"
        found = _run_code_search(gh, query, stats)
        repos.update(found)
        logger.info("Size {}: +{} (total {})", size_q, len(found), len(repos))
    return repos
```

#### Strategy 2: Path-based Search

Target common skill paths where `SKILL.md` files are typically found:

```python
SKILL_PATHS = ["skills", ".claude", ".codex", ".github", "agent-skills"]

def search_by_path(gh: GitHubClient, stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    repos: dict[str, DiscoveredRepo] = {}
    for skill_path in SKILL_PATHS:
        query = f"filename:SKILL.md path:{skill_path}"
        found = _run_code_search(gh, query, stats)
        repos.update(found)
        logger.info("Path '{}': +{} (total {})", skill_path, len(found), len(repos))
    return repos
```

#### Strategy 3: Topic-based Discovery

Search repos by GitHub topics, paginating up to 5 pages per topic (500 repos per topic max):

```python
SKILL_TOPICS = [
    "agent-skills",
    "claude-skills",
    "ai-agent-skills",
    "claude-code-skills",
    "codex-skills",
    "copilot-skills",
    "cursor-skills",
    "windsurf-skills",
]

def search_by_topic(gh: GitHubClient, stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    repos: dict[str, DiscoveredRepo] = {}
    for topic in SKILL_TOPICS:
        page = 1
        while page <= 5:
            resp = gh.get("/search/repositories", params={
                "q": f"topic:{topic}", "sort": "stars", "order": "desc",
                "per_page": 100, "page": page,
            })
            stats.queries_made += 1
            if resp.status_code != 200:
                break
            items = resp.json().get("items", [])
            if not items:
                break
            for item in items:
                fn = item["full_name"]
                if fn not in repos:
                    repos[fn] = DiscoveredRepo(
                        full_name=fn, owner_login=item["owner"]["login"],
                        owner_type=item["owner"]["type"], clone_url=item["clone_url"],
                        stars=item.get("stargazers_count", 0),
                        description=item.get("description") or "",
                    )
            if len(items) < 100:
                break
            page += 1
            time.sleep(1)
        logger.info("Topic '{}': total {}", topic, len(repos))
    return repos
```

#### Strategy 4: Fork Scanning

Enumerate forks of the top-10 most-starred discovered repos (up to 3 pages per parent repo):

```python
def scan_forks(gh: GitHubClient, popular_repos: list[str], stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    repos: dict[str, DiscoveredRepo] = {}
    for repo_name in popular_repos:
        page = 1
        while page <= 3:
            resp = gh.get(f"/repos/{repo_name}/forks", params={
                "sort": "stargazers", "per_page": 100, "page": page,
            })
            stats.queries_made += 1
            if resp.status_code != 200:
                break
            forks = resp.json()
            if not forks:
                break
            for fork in forks:
                fn = fork["full_name"]
                if fn not in repos:
                    repos[fn] = DiscoveredRepo(
                        full_name=fn, owner_login=fork["owner"]["login"],
                        owner_type=fork["owner"]["type"], clone_url=fork["clone_url"],
                        stars=fork.get("stargazers_count", 0),
                        description=fork.get("description") or "",
                    )
            if len(forks) < 100:
                break
            page += 1
        logger.info("Forks of '{}': {} total", repo_name, len(repos))
    return repos
```

**Note:** Fork scanning runs last because it depends on the set of already-discovered repos (takes the top 10 by stars).

#### Strategy 5: Curated List Parsing

Parse READMEs from known awesome-lists for GitHub repo links:

```python
CURATED_LIST_REPOS = [
    "skillmatic-ai/awesome-agent-skills",
    "hoodini/ai-agents-skills",
    "CommandCodeAI/agent-skills",
    "heilcheng/awesome-agent-skills",
]

def parse_curated_lists(gh: GitHubClient, stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    repos: dict[str, DiscoveredRepo] = {}
    link_re = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)")
    for list_repo in CURATED_LIST_REPOS:
        resp = gh.get(f"/repos/{list_repo}/readme")
        stats.queries_made += 1
        if resp.status_code != 200:
            continue
        try:
            content = base64.b64decode(resp.json().get("content", "")).decode()
        except Exception:
            continue
        refs = {m.rstrip("/").removesuffix(".git") for m in link_re.findall(content)
                if m.rstrip("/").removesuffix(".git").count("/") == 1}
        for ref in refs:
            if ref in repos:
                continue
            dr = gh.get(f"/repos/{ref}")
            stats.queries_made += 1
            if dr.status_code != 200:
                continue
            d = dr.json()
            repos[ref] = DiscoveredRepo(
                full_name=ref, owner_login=d["owner"]["login"],
                owner_type=d["owner"]["type"], clone_url=d["clone_url"],
                stars=d.get("stargazers_count", 0), description=d.get("description") or "",
            )
        logger.info("Curated '{}': {} refs", list_repo, len(refs))
    return repos
```

#### Shared Code Search Helper

Both file-size and path-based strategies use `_run_code_search()`, which handles pagination (up to 10 pages, 100 items each) with rate-limit-aware sleeping:

```python
def _run_code_search(gh: GitHubClient, query: str, stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    repos: dict[str, DiscoveredRepo] = {}
    page = 1
    while page <= 10:
        resp = gh.get("/search/code", params={"q": query, "per_page": 100, "page": page})
        stats.queries_made += 1
        if resp.status_code in (422, 403):
            break
        if resp.status_code != 200:
            break
        items = resp.json().get("items", [])
        if not items:
            break
        for item in items:
            repo = item.get("repository", {})
            fn = repo.get("full_name", "")
            if fn and fn not in repos:
                repos[fn] = DiscoveredRepo(
                    full_name=fn, owner_login=repo["owner"]["login"],
                    owner_type=repo["owner"].get("type", "User"),
                    clone_url=repo.get("clone_url", f"https://github.com/{fn}.git"),
                    stars=repo.get("stargazers_count", 0),
                    description=repo.get("description") or "",
                )
        if len(items) < 100:
            break
        page += 1
        time.sleep(2)
    return repos
```

### GitHub API Client

Rate-limit-aware HTTP client using `httpx`. Tracks `x-ratelimit-remaining` and `x-ratelimit-reset` headers and proactively sleeps when the limit is low:

```python
class GitHubClient:
    def __init__(self, token: str | None = None):
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=GITHUB_API, headers=headers, timeout=30,
        )
        self._rate_limit_remaining = 999
        self._rate_limit_reset = 0.0

    def close(self):
        self._client.close()

    def get(self, path: str, params: dict | None = None) -> httpx.Response:
        self._wait_for_rate_limit()
        resp = self._client.get(path, params=params)
        self._update_rate_limit(resp)
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            wait = max(self._rate_limit_reset - time.time(), 5)
            logger.warning("Rate limited. Waiting {:.0f}s...", wait)
            time.sleep(wait + 1)
            resp = self._client.get(path, params=params)
            self._update_rate_limit(resp)
        return resp

    def _wait_for_rate_limit(self):
        if self._rate_limit_remaining < 3:
            wait = max(self._rate_limit_reset - time.time(), 1)
            logger.info("Rate limit low ({}). Waiting {:.0f}s...",
                        self._rate_limit_remaining, wait)
            time.sleep(wait + 1)

    def _update_rate_limit(self, resp: httpx.Response):
        remaining = resp.headers.get("x-ratelimit-remaining")
        reset = resp.headers.get("x-ratelimit-reset")
        if remaining is not None:
            self._rate_limit_remaining = int(remaining)
        if reset is not None:
            self._rate_limit_reset = float(reset)
```

### Modal Worker Function

#### Definition in `modal_app.py`

The crawler needs `git` installed in the container, so it uses an extended image. The `concurrency_limit` controls how many containers run in parallel — this is the primary throughput knob.

```python
# Extended image for the crawler — adds git for cloning repos
crawler_image = image.apt_install("git")

@app.function(image=crawler_image, secrets=secrets, timeout=300, concurrency_limit=50)
def crawl_process_repo(
    repo_dict: dict,
    bot_user_id: str,
    github_token: str | None = None,
) -> dict:
    """Process a single discovered repo: clone, discover skills, gauntlet, publish.

    Runs on Modal with ephemeral disk and access to DB/S3/Gemini secrets.
    Returns a result dict with status and counts.
    """
    from decision_hub.scripts.crawler.processing import process_repo_on_modal

    return process_repo_on_modal(repo_dict, bot_user_id, github_token)
```

The `concurrency_limit` default (50) should be tunable. Options:
- Pass it as a Modal secret / env var read at deploy time
- Or the CLI `--concurrency` flag overrides it at call time via `fn.map(..., kwargs={"concurrency_limit": N})` — check if Modal supports runtime override, otherwise the deploy-time value is the ceiling

#### Input: `repo_dict`

```python
{
    "full_name": "owner/repo",
    "owner_login": "owner",
    "owner_type": "Organization",  # or "User"
    "clone_url": "https://github.com/owner/repo.git",
    "stars": 42,
    "description": "...",
}
```

#### Output: result dict

```python
{
    "repo": "owner/repo",
    "status": "ok" | "error" | "no_skills" | "skipped",
    "skills_published": 3,
    "skills_skipped": 1,
    "skills_failed": 0,
    "skills_quarantined": 0,
    "org_created": True,
    "email_saved": True,
    "error": None,  # or error message string
}
```

#### Processing Pipeline (per container)

Each Modal container handles exactly one repo:

```
1. Validate owner_login -> org slug (must match [a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)
2. Fetch owner email (GitHub API, using github_token if provided)
3. Open DB connection (NullPool — 1 connection per container)
4. Ensure org exists in DB + bot user is admin
5. git clone --depth 1 (with 120s subprocess timeout)
6. Walk directory tree -> find SKILL.md files
7. For each skill directory:
   a. parse_skill_md() -> manifest
   b. validate_skill_name()
   c. Create zip + compute checksum
   d. Check if latest version has same checksum -> skip if unchanged
   e. extract_for_evaluation() -> skill_md_content, source_files, lockfile
   f. Run Gauntlet (static checks + Gemini LLM analysis)
   g. If Grade F: quarantine to rejected/ S3, insert audit log, skip
   h. Otherwise: upload to skills/ S3, insert version with eval_status=grade
   i. Insert audit log
8. Close DB connection
9. Cleanup temp directory (container dies anyway, but be explicit)
10. Return result dict
```

#### Key Implementation Code

```python
def process_repo_on_modal(repo_dict: dict, bot_user_id_str: str, github_token: str | None) -> dict:
    """Process a single repo inside a Modal container."""
    from dhub_core.manifest import parse_skill_md
    from decision_hub.api.registry_service import run_gauntlet_pipeline
    from decision_hub.domain.publish import build_quarantine_s3_key, build_s3_key, validate_skill_name
    from decision_hub.domain.skill_manifest import extract_body, extract_description
    from decision_hub.infra.database import (
        create_engine, find_org_by_slug, find_org_member, find_skill, find_version,
        insert_audit_log, insert_org_member, insert_organization, insert_skill,
        insert_version, resolve_latest_version, update_org_email,
        update_skill_description, upsert_user,
    )
    from decision_hub.infra.storage import compute_checksum, create_s3_client, upload_skill_zip
    from decision_hub.settings import create_settings

    result = {
        "repo": repo_dict["full_name"],
        "status": "ok",
        "skills_published": 0, "skills_skipped": 0,
        "skills_failed": 0, "skills_quarantined": 0,
        "org_created": False, "email_saved": False, "error": None,
    }

    try:
        settings = create_settings()
        engine = create_engine(settings.database_url)
        s3_client = create_s3_client(
            region=settings.aws_region,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
        )

        slug = repo_dict["owner_login"].lower()
        if not _SLUG_PATTERN.match(slug):
            result["status"] = "skipped"
            result["error"] = f"Invalid org slug: {slug}"
            return result

        bot_user_id = UUID(bot_user_id_str)

        # Fetch owner email
        email = fetch_owner_email(
            repo_dict["owner_login"], repo_dict["owner_type"], github_token,
        )

        with engine.connect() as conn:
            # Ensure bot user exists
            upsert_user(conn, github_id=BOT_GITHUB_ID, username=BOT_USERNAME)

            # Ensure org exists and bot is a member
            org = find_org_by_slug(conn, slug)
            if org is None:
                org = insert_organization(conn, slug, bot_user_id, is_personal=False)
                insert_org_member(conn, org.id, bot_user_id, "owner")
                result["org_created"] = True
            else:
                existing = find_org_member(conn, org.id, bot_user_id)
                if existing is None:
                    insert_org_member(conn, org.id, bot_user_id, "admin")

            if email and not org.email:
                update_org_email(conn, org.id, email)
                result["email_saved"] = True

            conn.commit()

            # Clone and discover (reuse from domain/repo_utils.py — shared with PR #14)
            repo_root = clone_repo(repo_dict["clone_url"])
            tmp_dir = repo_root.parent

            try:
                skill_dirs = discover_skills(repo_root)
                if not skill_dirs:
                    result["status"] = "no_skills"
                    return result

                for skill_dir in skill_dirs:
                    try:
                        _publish_one_skill(conn, s3_client, settings, org, skill_dir, result)
                        conn.commit()
                    except Exception as exc:
                        result["skills_failed"] += 1
                        conn.rollback()
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    except subprocess.TimeoutExpired:
        result["status"] = "error"
        result["error"] = f"git clone timed out after {CLONE_TIMEOUT_SECONDS}s"
    except subprocess.CalledProcessError as exc:
        result["status"] = "error"
        result["error"] = f"git clone failed: {exc.stderr[:200] if exc.stderr else str(exc)}"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)[:500]

    return result
```

### Publish-one-skill Logic

The `_publish_one_skill()` function handles parsing, zipping, gauntlet, and DB writes for a single skill directory:

```python
def _publish_one_skill(conn, s3_client, settings, org, skill_dir: Path, result: dict):
    """Parse, gauntlet-check, and publish a single skill. Mutates result counts."""
    manifest = parse_skill_md(skill_dir / "SKILL.md")
    name = manifest.name
    description = manifest.description
    validate_skill_name(name)

    # Create zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(skill_dir.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(skill_dir)
            if any(p.startswith(".") or p == "__pycache__" for p in rel.parts):
                continue
            zf.write(f, rel)
    zip_data = buf.getvalue()
    checksum = compute_checksum(zip_data)

    # Upsert skill record
    skill = find_skill(conn, org.id, name)
    if skill is None:
        skill = insert_skill(conn, org.id, name, description)
    else:
        update_skill_description(conn, skill.id, description)

    # Determine version (auto-bump patch or start at 0.1.0)
    latest = resolve_latest_version(conn, org.slug, name)
    if latest is not None:
        if latest.checksum == checksum:
            result["skills_skipped"] += 1
            return  # identical content — skip
        parts = latest.semver.split(".")
        parts[2] = str(int(parts[2]) + 1)
        version = ".".join(parts)
    else:
        version = "0.1.0"

    if find_version(conn, skill.id, version) is not None:
        result["skills_skipped"] += 1
        return

    # Extract content for gauntlet evaluation
    skill_md_content = (skill_dir / "SKILL.md").read_text()
    skill_md_body = extract_body(skill_md_content)
    desc = extract_description(skill_md_content)
    try:
        _, source_files, lockfile_content = extract_for_evaluation(zip_data)
    except ValueError:
        source_files = []
        lockfile_content = None

    # Run Gauntlet
    report, check_results, llm_reasoning = run_gauntlet_pipeline(
        skill_md_content, lockfile_content, source_files,
        name, desc, skill_md_body, settings,
    )

    if not report.passed:
        # Grade F — quarantine
        q_key = build_quarantine_s3_key(org.slug, name, version)
        insert_audit_log(
            conn, org_slug=org.slug, skill_name=name, semver=version,
            grade=report.grade, check_results=check_results,
            publisher=BOT_USERNAME, version_id=None,
            llm_reasoning=llm_reasoning, quarantine_s3_key=q_key,
        )
        conn.commit()
        upload_skill_zip(s3_client, settings.s3_bucket, q_key, zip_data)
        result["skills_quarantined"] += 1
        return

    # Grade A/B/C — publish
    s3_key = build_s3_key(org.slug, name, version)
    upload_skill_zip(s3_client, settings.s3_bucket, s3_key, zip_data)
    version_record = insert_version(
        conn, skill_id=skill.id, semver=version, s3_key=s3_key,
        checksum=checksum, runtime_config=None,
        published_by=BOT_USERNAME, eval_status=report.grade,
    )
    insert_audit_log(
        conn, org_slug=org.slug, skill_name=name, semver=version,
        grade=report.grade, check_results=check_results,
        publisher=BOT_USERNAME, version_id=version_record.id,
        llm_reasoning=llm_reasoning, quarantine_s3_key=None,
    )
    result["skills_published"] += 1
```

### Orchestrator Dispatch — Modal `.map()`

The local orchestrator dispatches **all** pending repos to Modal in a single `.map()` call. Modal manages container scheduling and parallelism via `concurrency_limit`.

```python
def run_processing_phase(
    pending_repos: list[DiscoveredRepo],
    bot_user_id: str,
    github_token: str | None,
    checkpoint: Checkpoint,
    checkpoint_path: Path,
    max_skills: int | None,
) -> CrawlStats:
    stats = CrawlStats()
    fn = modal.Function.from_name(settings.modal_app_name, "crawl_process_repo")

    repo_dicts = [_repo_to_dict(r) for r in pending_repos]

    with Progress(...) as progress:
        task = progress.add_task("Processing repos", total=len(repo_dicts))

        # Single .map() call — Modal handles parallelism via concurrency_limit
        for result in fn.map(
            repo_dicts,
            kwargs={"bot_user_id": bot_user_id, "github_token": github_token},
            return_exceptions=True,
        ):
            if isinstance(result, Exception):
                stats.errors.append(str(result)[:500])
            else:
                stats.accumulate(result)

            # Checkpoint after every result
            checkpoint.mark_processed(result["repo"] if isinstance(result, dict) else "unknown", checkpoint_path)
            progress.advance(task)

            # Stop early if --max-skills cap reached
            if max_skills is not None and stats.skills_published >= max_skills:
                logger.info("Reached --max-skills cap ({}), stopping", max_skills)
                break

    return stats
```

**Why a single `.map()` instead of batch-of-N:**
- Modal's `concurrency_limit` already controls parallelism — no need to manually batch.
- `.map()` returns an iterator that yields results as they complete — natural streaming.
- Simpler code, fewer edge cases.
- The `--concurrency` CLI flag sets `concurrency_limit` at deploy time (or pass as a Modal secret).

### Checkpoint System

#### JSON Structure

```json
{
  "discovered_repos": {
    "owner/repo1": {
      "full_name": "owner/repo1",
      "owner_login": "owner",
      "owner_type": "User",
      "clone_url": "https://github.com/owner/repo1.git",
      "stars": 42,
      "description": "Some description"
    }
  },
  "processed_repos": ["owner/repo1", "owner/repo2"]
}
```

#### Checkpoint Data Class

```python
@dataclass
class Checkpoint:
    discovered_repos: dict[str, dict] = field(default_factory=dict)
    processed_repos: list[str] = field(default_factory=list)
    _flush_counter: int = field(default=0, repr=False)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> Checkpoint:
        data = json.loads(path.read_text())
        return cls(
            discovered_repos=data.get("discovered_repos", {}),
            processed_repos=data.get("processed_repos", []),
        )

    def mark_processed(self, full_name: str, path: Path, flush_every: int = 100) -> None:
        """Append a processed repo. Flush to disk every N results for efficiency at scale."""
        self.processed_repos.append(full_name)
        self._flush_counter += 1
        if self._flush_counter >= flush_every:
            self.save(path)
            self._flush_counter = 0
```

**At 170k repos:**
- The `discovered_repos` dict (~50MB JSON) is written once after discovery.
- The `processed_repos` list grows incrementally. Flushing every 100 results balances durability vs. I/O. On crash, at most 100 repos are reprocessed (and reprocessing is idempotent via checksum skip).

#### Resume Logic

1. Load checkpoint, skip discovery.
2. Filter out already-processed repos: `pending = [r for r in discovered if r.full_name not in processed_set]`.
3. Use a `set` for the lookup (O(1) membership check at 170k).
4. Process only remaining repos.

### Gauntlet Integration

Crawled skills go through the **same safety pipeline** as manually published skills via `run_gauntlet_pipeline()`:

1. **Static checks** — regex-based detection of dangerous patterns
2. **LLM analysis** — Gemini reviews code snippets and prompt text
3. **Grading** — A (clean) / B (minor) / C (risky) / F (rejected)

| Grade | Action |
|-------|--------|
| A / B | Publish to `skills/{org}/{name}/{version}.zip`, `eval_status=grade` |
| C | Publish to `skills/{org}/{name}/{version}.zip`, `eval_status="C"` |
| F | Quarantine to `rejected/{org}/{name}/{version}.zip`, skip publish |

All grades get an audit log entry via `insert_audit_log()`.

### Bot User

| Field | Value |
|-------|-------|
| `github_id` | `"0"` |
| `username` | `"dhub-crawler"` |

- **Owner** of every org the crawler creates.
- **Admin** of every pre-existing org the crawler touches.
- Recorded as `published_by="dhub-crawler"` on all versions.
- Created/upserted during Phase 2 setup. Its `user_id` UUID is passed to Modal workers as a string argument.

### Resilience

| Failure | Handling |
|---------|----------|
| `git clone` hangs >120s | `subprocess.TimeoutExpired` caught, error result |
| `git clone` network error | `CalledProcessError` caught, repo status = "error" |
| SKILL.md parse failure | Caught per-skill, other skills still processed |
| Gauntlet Gemini API failure | Falls back to regex-only static checks |
| S3 upload failure | Exception propagates, repo status = "error" |
| DB write failure | Exception propagates, repo status = "error" |
| Modal 300s timeout | Container killed, `.map` returns exception |
| Any unhandled exception | `return_exceptions=True` in `.map` catches it |
| Per-skill failure | `conn.rollback()` per skill, next skill proceeds |
| Orchestrator crash | Resume from checkpoint, reprocess is idempotent |

### Progress Bar (Rich)

```
Discovering repos...  ==================== 100% (5/5 strategies)
Processing repos      ==========           47% 79,900/170,000 | pub:12,340 fail:89 skip:67,000 quarantined:471
```

Uses `rich.progress.Progress` with:
- A task for discovery (indeterminate spinner, advances per strategy)
- A task for processing (determinate bar, advances by 1 per result from `.map()`)
- Status columns showing published/failed/skipped/quarantined counts

### GitHub Email Lookup

```python
def fetch_owner_email(login: str, owner_type: str, token: str | None = None) -> str | None:
    """Fetch public email for a GitHub user/org. Works inside Modal containers."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    endpoint = f"https://api.github.com/orgs/{login}" if owner_type == "Organization" \
        else f"https://api.github.com/users/{login}"
    try:
        resp = httpx.get(endpoint, headers=headers, timeout=15)
        if resp.status_code == 200:
            email = resp.json().get("email")
            return email if email else None
    except httpx.HTTPError:
        return None
    return None
```

## Key Data Classes

```python
@dataclass
class DiscoveredRepo:
    full_name: str
    owner_login: str
    owner_type: str       # "User" or "Organization"
    clone_url: str
    stars: int = 0
    description: str = ""

@dataclass
class CrawlStats:
    queries_made: int = 0
    repos_discovered: int = 0
    repos_processed: int = 0
    repos_skipped_checkpoint: int = 0
    skills_published: int = 0
    skills_skipped: int = 0
    skills_failed: int = 0
    skills_quarantined: int = 0
    orgs_created: int = 0
    emails_saved: int = 0
    errors: list[str] = field(default_factory=list)
```

## Constants

```python
GITHUB_API = "https://api.github.com"
DEFAULT_CHECKPOINT_PATH = Path("crawl_checkpoint.json")
CLONE_TIMEOUT_SECONDS = 120
BOT_GITHUB_ID = "0"
BOT_USERNAME = "dhub-crawler"
_SLUG_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")
```

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `server/migrations/YYYYMMDD_HHMMSS_add_org_email.sql` | **Create** | SQL migration for `email` column (may already exist from #14) |
| `server/src/decision_hub/models.py` | **Modify** | Add `email: str \| None = None` to `Organization` |
| `server/src/decision_hub/infra/database.py` | **Modify** | Add `email` column, update mapper, add `update_org_email()` |
| `server/modal_app.py` | **Modify** | Add `crawler_image` and `crawl_process_repo` function with `concurrency_limit` |
| `server/src/decision_hub/scripts/crawler/__init__.py` | **Create** | Package init |
| `server/src/decision_hub/scripts/crawler/__main__.py` | **Create** | CLI entry point + `run_crawler()` orchestrator |
| `server/src/decision_hub/scripts/crawler/discovery.py` | **Create** | All 5 strategies + `GitHubClient` |
| `server/src/decision_hub/scripts/crawler/processing.py` | **Create** | `process_repo_on_modal()` + `_publish_one_skill()` |
| `server/src/decision_hub/scripts/crawler/checkpoint.py` | **Create** | `Checkpoint` class with flush-every-N |
| `server/src/decision_hub/scripts/crawler/models.py` | **Create** | `DiscoveredRepo`, `CrawlStats` |
| `server/tests/test_scripts/test_github_crawler.py` | **Create** | Tests |

## Tests to Write

### Unit Tests (pure functions, no external dependencies)

- `test_run_code_search_pagination`: Mock GitHub responses, verify pagination stops at empty page and at 10-page limit.
- `test_run_code_search_rate_limit_retry`: Mock a 403 rate-limit response, verify retry after wait.
- `test_search_by_file_size_deduplication`: Same repo in multiple size ranges is only counted once.
- `test_search_by_path_all_paths`: Verify all `SKILL_PATHS` are queried.
- `test_search_by_topic_pagination`: Verify topic search paginates up to 5 pages.
- `test_scan_forks_top_repos`: Verify fork scanning only processes the top N repos.
- `test_parse_curated_lists_link_extraction`: Mock a README with GitHub links, verify extraction and deduplication.
- `test_parse_curated_lists_invalid_readme`: Base64 decode failure is handled gracefully.
- `test_github_client_rate_limit_tracking`: Verify `_update_rate_limit` parses headers correctly.
- `test_github_client_proactive_wait`: Verify client sleeps when remaining < 3.
- `test_discovered_repo_to_dict_roundtrip`: `_repo_to_dict` and `_dict_to_repo` are inverse operations.
- `test_clone_repo_timeout`: Mock `subprocess.run` raising `TimeoutExpired`, verify it propagates.
- `test_discover_skills_finds_nested`: Create temp dir with nested `SKILL.md` files, verify all found.
- `test_discover_skills_empty_dir`: No `SKILL.md` files returns empty list.
- `test_fetch_owner_email_user`: Mock GitHub user endpoint returning email.
- `test_fetch_owner_email_org`: Mock GitHub org endpoint returning email.
- `test_fetch_owner_email_none`: Mock endpoint returning no email field.
- `test_fetch_owner_email_error`: Mock network error, verify returns None (not generic Exception).
- `test_slug_validation`: Verify `_SLUG_PATTERN` rejects invalid slugs.

### Checkpoint Tests

- `test_checkpoint_save_load_roundtrip`: Save and load preserves all data.
- `test_checkpoint_mark_processed_flush_every_n`: Verify flush only happens every N results.
- `test_checkpoint_mark_processed_force_flush`: Verify final flush after processing completes.
- `test_checkpoint_resume_filters_processed`: Verify processed repos are excluded on resume (set-based O(1) lookup).
- `test_checkpoint_fresh_deletes_file`: Verify `--fresh` deletes existing checkpoint.
- `test_checkpoint_large_scale`: Create a checkpoint with 100k entries, verify load/save performance is acceptable.

### Publish Logic Tests

- `test_publish_one_skill_new`: First publish creates skill + version at `0.1.0`.
- `test_publish_one_skill_auto_bump`: Second publish with different checksum bumps patch.
- `test_publish_one_skill_same_checksum_skips`: Same checksum skips (no new version).
- `test_publish_one_skill_grade_f_quarantines`: Grade F goes to `rejected/` S3 prefix.
- `test_publish_one_skill_grade_a_publishes`: Grade A goes to `skills/` S3 prefix.
- `test_publish_one_skill_invalid_name`: Invalid skill name raises, caught by caller.

### Integration-style Tests (mocked Modal + DB)

- `test_process_repo_on_modal_no_skills`: Repo with no `SKILL.md` returns `no_skills` status.
- `test_process_repo_on_modal_invalid_slug`: Invalid org slug returns `skipped` status.
- `test_process_repo_on_modal_clone_timeout`: Timeout returns error status.
- `test_process_repo_on_modal_creates_org`: New org is created and bot is added as owner.
- `test_process_repo_on_modal_existing_org_adds_admin`: Existing org gets bot as admin member.
- `test_process_repo_on_modal_saves_email`: Email is saved when org has none.
- `test_process_repo_on_modal_skill_failure_continues`: One skill failing does not block others.

### Orchestrator Tests

- `test_run_crawler_discovery_phase`: Verify all active strategies are called.
- `test_run_crawler_resume_skips_discovery`: With `--resume`, discovery is skipped.
- `test_run_crawler_max_skills_stops`: Verify `--max-skills` limit stops processing after N skills are published.
- `test_run_crawler_dry_run_no_processing`: Verify `--dry-run` runs discovery but skips processing.
- `test_run_crawler_modal_error_handled`: Modal connectivity failure is caught per-result via `return_exceptions=True`.

## Notes for Re-implementation

### Experimental — design for easy removal

This feature is experimental and may be ripped out. Implement with that in mind:

- **Feature flag**: Add `ENABLE_GITHUB_CRAWLER: bool = False` to server settings. Off by default — opt-in only.
- **Fully isolated module**: All crawler code lives in `server/src/decision_hub/scripts/crawler/`. Nothing outside that directory should import from it. Only `modal_app.py` references the entry point.
- **No crawler-specific schema changes**: The `email` column on `organizations` is independently useful — implement it in an earlier PR or as a standalone migration. The crawler itself should not own any database tables. Removing the crawler requires zero rollback migrations.
- **Don't put shared utilities in the crawler**: Clone/discover/publish code belongs in `domain/repo_utils.py` (shared with PR #14). The crawler imports it, not the other way around.
- **Removal procedure**: Delete `scripts/crawler/`, remove `crawl_process_repo` and `crawler_image` from `modal_app.py`, remove the feature flag. No database changes, no other features affected.

### Reuse from PR #14 (Auto-Republish Tracker)

**Implement PR #14 first.** The auto-republish tracker (see `specs/pr-14-auto-republish.md`) establishes the shared utilities for repo cloning, skill discovery, and the publish pipeline. The crawler should import and reuse these instead of inlining duplicate implementations:

- `clone_repo()` — git clone with timeout and token injection
- `discover_skills()` — recursive `SKILL.md` discovery via `rglob`
- `_publish_one_skill()` / `_publish_skill_from_tracker()` — zip, checksum dedup, gauntlet, version bump, S3 upload

Extract these into a shared module (e.g. `server/src/decision_hub/domain/repo_utils.py`) during #14, then import from the crawler.

### Impact on auto-republish (#14)

The crawler seeds the database with potentially 170k+ skills. The auto-republish tracker (`dhub track`) monitors a **subset** of these (user-initiated via `dhub track add`). If many users track many repos, the `check_trackers` Modal scheduled function from #14 should also use Modal `.map()` fan-out instead of a sequential loop. Design #14's tracker processing to be Modal-dispatchable from the start.

### Must-haves

- **Must use loguru** for server-side logging, not `logging.getLogger()`.
- **Must use loguru `{}` placeholders**, not `%s` format strings.
- **Must use timestamp-based SQL migration**, not a Python migration script.
- **Must use `IF NOT EXISTS`** in DDL for idempotency.
- **Must follow current Modal patterns** from `modal_app.py`.
- **GitHub token** reads from `$GITHUB_TOKEN` env var by default and is forwarded to Modal containers for email lookups. Warn (don't error) if missing — unauthenticated rate limits (60 req/hr) will be very slow but technically work for small runs.

### Should-haves

- **`--dry-run` flag** — discover repos, print stats, do not process. Essential for estimating scope before committing resources.
- **The `GitHubClient` class is acceptable** — it encapsulates connection state (rate limit tracking, httpx client lifecycle). Classes for state management are allowed per project conventions.
- **`--max-skills`** caps skills published, not repos processed. Processing continues repo-by-repo until the cap is hit, then stops. Useful for test runs on a small batch.

### Avoid

- Do not remove `loguru` from the server.
- Do not remove `search_logs_table` or `semver_major/minor/patch` columns.
- Do not change the `DHUB_ENV` default from `dev` to `prod` in `settings.py`.
- Do not change the Modal org prefix in `_DEFAULT_API_URLS`.
- Do not remove `MIN_CLI_VERSION` handling from `modal_app.py`.
- Do not catch generic `Exception` in `fetch_owner_email()` — catch `httpx.HTTPError` specifically.

### Dependencies

- `httpx` (already a server dependency).
- No new PyPI dependencies.
- Modal worker image needs `git` via `apt_install("git")`.

### Client Package Independence

The Modal worker image does NOT include the `dhub-cli` client package. Functions like `clone_repo` and `discover_skills` live in the server package (`domain/repo_utils.py`). `parse_skill_md` comes from `dhub_core.manifest` (available in the Modal image).
