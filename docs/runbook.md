# Operations Runbook

Operational reference for DB access, crawler, trackers, backfills, and troubleshooting.

## DB Access

### Boilerplate

Always run from `server/` so pydantic-settings finds `.env.{env}`:

```bash
cd server && DHUB_ENV=dev uv run --package decision-hub-server python -c "
from decision_hub.infra.database import create_engine
from decision_hub.settings import create_settings
from sqlalchemy import text

settings = create_settings()
engine = create_engine(settings.database_url)

with engine.connect() as conn:
    rows = conn.execute(text('SELECT ...')).fetchall()
    for r in rows:
        print(dict(r._mapping))
"
```

**Common mistakes to avoid:**
- `get_engine()` does NOT exist — use `create_engine(settings.database_url)`
- `Settings()` does NOT work — use `create_settings()` (reads `.env.{env}`)
- The skills column is `name`, NOT `skill_name`

### Key table columns

**skills**: `id` (UUID), `org_id`, `name`, `description`, `category`, `visibility`, `source_repo_url`, `source_repo_removed`, `github_stars`, `github_forks`, `github_watchers`, `github_is_archived`, `github_license`, `latest_semver`, `latest_eval_status`, `latest_gauntlet_summary`, `latest_published_at`, `download_count`, `embedding` (vector 768)

**skill_trackers**: `id` (UUID), `user_id`, `org_slug`, `repo_url`, `branch`, `last_commit_sha`, `poll_interval_minutes`, `enabled`, `last_checked_at`, `last_published_at`, `last_error`, `next_check_at`, `consecutive_permanent_failures`

### Common queries

```sql
-- Look up a skill by name
SELECT id, name, source_repo_url, source_repo_removed, github_is_archived,
       latest_semver, latest_eval_status, updated_at
FROM skills WHERE name = 'skill-name';

-- Skills by org
SELECT name, latest_semver, latest_eval_status, download_count
FROM skills WHERE org_id = (SELECT id FROM orgs WHERE slug = 'org-slug')
ORDER BY name;

-- Catalog health overview
SELECT count(*) AS total,
       count(*) FILTER (WHERE source_repo_removed) AS removed,
       count(*) FILTER (WHERE github_is_archived) AS archived,
       count(*) FILTER (WHERE latest_eval_status = 'passed') AS eval_passed
FROM skills;

-- Tracker status for a repo
SELECT id, repo_url, enabled, last_checked_at, last_error,
       consecutive_permanent_failures, last_commit_sha
FROM skill_trackers WHERE repo_url ILIKE '%repo-name%';

-- All disabled trackers
SELECT repo_url, last_error, consecutive_permanent_failures, last_checked_at
FROM skill_trackers WHERE enabled = false
ORDER BY last_checked_at DESC;
```

## Republishing Skills

Skills published via the **crawler** must be re-published via the crawler (`--repos`), not via `dhub publish`. The crawler re-runs gauntlet analysis and updates metadata.

```bash
# Re-crawl specific repos (dev)
cd server && DHUB_ENV=dev uv run --package decision-hub-server \
  python -m decision_hub.scripts.github_crawler \
  --repos owner/repo --github-token "$(gh auth token)"

# Re-crawl specific repos (prod)
cd server && DHUB_ENV=prod uv run --package decision-hub-server \
  python -m decision_hub.scripts.github_crawler \
  --repos owner/repo --github-token "$(gh auth token)"
```

## Verifying GitHub App Tokens

Test that the GitHub App can mint tokens and access repos:

```bash
cd server && DHUB_ENV=prod uv run --package decision-hub-server python -c "
from decision_hub.settings import create_settings
from decision_hub.infra.github_app_token import mint_installation_token
from decision_hub.infra.github_client import GitHubClient

settings = create_settings()
token = mint_installation_token(
    settings.github_app_id,
    settings.github_app_private_key,
    settings.github_app_installation_id,
)
print(f'Token minted: {token[:8]}...')

with GitHubClient(token=token) as gh:
    data = gh.graphql('{rateLimit { remaining }}')
    print(f'Rate limit remaining: {data[\"rateLimit\"][\"remaining\"]}')

    # Test access to a specific repo
    data = gh.graphql('{repository(owner: \"pymc-labs\", name: \"python-analytics-skills\") { name }}')
    print(f'Repo access: {data}')
"
```

## Crawler

Discovers GitHub repos containing `SKILL.md` files and publishes them through the gauntlet pipeline via Modal. Run from `server/`:

```bash
# Crawl up to 100 skills on dev (use a single fast strategy)
cd server && DHUB_ENV=dev uv run --package decision-hub-server \
  python -m decision_hub.scripts.github_crawler \
  --max-skills 100 --strategies size --github-token "$(gh auth token)"

# Full discovery (all 5 strategies — slow, ~15 min due to rate limits)
cd server && DHUB_ENV=dev uv run --package decision-hub-server \
  python -m decision_hub.scripts.github_crawler \
  --github-token "$(gh auth token)"

# Resume from checkpoint (skip discovery, go straight to processing)
cd server && DHUB_ENV=dev uv run --package decision-hub-server \
  python -m decision_hub.scripts.github_crawler \
  --resume --github-token "$(gh auth token)"

# Process specific repos (skip discovery)
cd server && DHUB_ENV=dev uv run --package decision-hub-server \
  python -m decision_hub.scripts.github_crawler \
  --repos git@github.com:machina-sports/sports-skills.git owner/repo \
  --github-token "$(gh auth token)"

# Dry-run (discovery only, no processing)
cd server && DHUB_ENV=dev uv run --package decision-hub-server \
  python -m decision_hub.scripts.github_crawler --dry-run
```

**Key flags:** `--max-skills N` (stop after N published), `--strategies size|path|topic|fork|curated` (pick subset), `--fresh` (delete checkpoint), `--resume` (skip discovery), `--repos REPO [REPO ...]` (process specific repos, accepts `owner/repo`, HTTPS, or SSH URLs). A GitHub token is required — unauthenticated rate limit is only 60 req/hr.

## Data Maintenance

Use the `backfill` target from the `Makefile` to run all backfills (categories, embeddings, org metadata). Defaults to dev; override with `DHUB_ENV=prod`. Individual backfill scripts can also be run directly from `server/` — see `server/scripts/backfill_categories.py` and `server/src/decision_hub/scripts/backfill_embeddings.py`.

## Monitoring Trackers

Trackers (`skill_trackers` table) poll GitHub repos for new commits and republish changed skills. Trackers are created automatically when publishing from a GitHub URL (`dhub publish --track`, enabled by default) or via the API (`POST /v1/trackers`).

**Key source files:**
- Cron schedule & fan-out: `server/modal_app.py` (`check_trackers`, `tracker_process_repo`)
- Orchestration & republish logic: `server/src/decision_hub/domain/tracker_service.py`
- CRUD routes: `server/src/decision_hub/api/tracker_routes.py`
- DB table & queries: `server/src/decision_hub/infra/database.py` (search `skill_trackers`)
- Settings (batch size, jitter, rate-limit floor): `server/src/decision_hub/settings.py` (search `tracker_`)

### GitHub App Authentication

Trackers authenticate to GitHub using **GitHub App installation tokens** instead of a personal access token (PAT). Each cron tick / Modal container mints its own short-lived token (~1 hr) from the App's private key. This gives dev and prod independent 12,500 req/hr rate-limit budgets.

**Apps:** App IDs, Installation IDs, and PEM keys are stored inline in `server/.env.dev` and `server/.env.prod` (git-ignored). The PEM is embedded as a multi-line quoted value (`GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA..."`). Original PEM files are also kept at `server/decision-hub-dev.*.pem` / `server/decision-hub.*.pem` (git-ignored).

**Note:** The crawler and backfill scripts still use a PAT passed via `--github-token`. Only the tracker cron uses App tokens.

**Quick health check:** Use the `tracker-health` target from the `Makefile`. Defaults to dev; override with `DHUB_ENV=prod`.

**Check Modal logs for failures:**
```bash
modal app logs decision-hub 2>&1 | grep -i "tracker\|check_trackers"     # prod
modal app logs decision-hub-dev 2>&1 | grep -i "tracker\|check_trackers"  # dev
```

**Query tracker health in DB:**
```sql
-- Failed trackers
SELECT repo_url, last_checked_at, last_error
FROM skill_trackers WHERE last_error IS NOT NULL AND enabled = true;
```

### Tracker Metrics

The `tracker_metrics` table records one row per `check_trackers` cron tick with key counters for historical observability. Metrics are written at the end of each cron invocation.

**Useful queries:**
```sql
-- Recent cron ticks (last 24h)
SELECT recorded_at, total_checked, trackers_changed, trackers_failed,
       github_rate_remaining, batch_duration_seconds
FROM tracker_metrics
WHERE recorded_at > now() - interval '24 hours'
ORDER BY recorded_at DESC;

-- Average duration and failure rate over last 7 days
SELECT date_trunc('day', recorded_at) AS day,
       count(*) AS ticks,
       avg(batch_duration_seconds)::numeric(5,1) AS avg_dur_s,
       sum(trackers_failed) AS total_failed,
       sum(trackers_disabled) AS total_disabled
FROM tracker_metrics
WHERE recorded_at > now() - interval '7 days'
GROUP BY 1 ORDER BY 1 DESC;

-- Check if circuit breaker has tripped (look for mass downgrades)
-- The circuit breaker has no dedicated metric column; it writes a
-- "transient: circuit breaker tripped" error message on affected trackers.
SELECT id, repo_url, last_error, updated_at
FROM skill_trackers
WHERE last_error LIKE '%circuit breaker%'
ORDER BY updated_at DESC;
```

## Troubleshooting

### Modal Cold Starts

Modal containers spin down after inactivity. The first HTTP request after a cold start can take 30-60 seconds. Always use `timeout=60` (or higher) when making HTTP requests to Modal endpoints. Do NOT use default timeouts — they will fail on cold starts.

### Inspecting Logs

```bash
# Stream live logs from Modal
modal app logs decision-hub          # prod
modal app logs decision-hub-dev      # dev

# Filter by request ID to trace a single request
modal app logs decision-hub-dev 2>&1 | grep "a1b2c3d4"
```

### Debugging Modal Sandboxes

When eval pipelines fail or hang, **do not** blindly poll the eval-report endpoint. Spin up a sandbox interactively and test each step in isolation:

```python
# From server/ directory:
# DHUB_ENV=dev uv run --package decision-hub-server python3 -c "..."

import modal
from decision_hub.infra.modal_client import build_eval_image, AGENT_CONFIGS

config = AGENT_CONFIGS['claude']
image = build_eval_image(config)
app = modal.App.lookup('decision-hub-eval', create_if_missing=True)
sb = modal.Sandbox.create(image=image, app=app, timeout=120)

# 1. Verify the agent binary
proc = sb.exec('which', 'claude'); proc.wait()
print(proc.stdout.read())

# 2. Run agent with output to file (avoids I/O blocking)
proc = sb.exec('bash', '-c',
    'nohup claude -p --dangerously-skip-permissions "Say hi" '
    '> /tmp/out.txt 2>/tmp/err.txt &')
proc.wait()

import time; time.sleep(15)

# 3. Read stdout AND stderr
proc = sb.exec('bash', '-c',
    'echo STDOUT: && cat /tmp/out.txt '
    '&& echo STDERR: && cat /tmp/err.txt')
proc.wait()
print(proc.stdout.read())

sb.terminate()
```

**Common issues:**
- **Exit 137 near the timeout duration** = sandbox timeout kill, not OOM. Correlate duration with the configured timeout.
- **Exit 137 well before timeout** = actual OOM. Increase `memory` in `Sandbox.create`.
- **`Invalid API key`** = stored `ANTHROPIC_API_KEY` expired/revoked. Claude Code hangs waiting for user input. Verify the key directly: `httpx.post('https://api.anthropic.com/v1/messages', headers={'x-api-key': key, 'anthropic-version': '2023-06-01'}, ...)`
- **`--dangerously-skip-permissions cannot be used with root`** = the sandbox image creates a `sandbox` user; agent commands must run via `sudo -E -u sandbox`.
- **Zero stdout from agent** = always check stderr. Use `nohup` + file redirect and inspect after a few seconds instead of waiting for the full timeout.
