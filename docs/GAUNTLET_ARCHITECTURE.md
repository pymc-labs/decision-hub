# Gauntlet System Architecture

This document traces the exact workflow for every path a skill can take through the Gauntlet pipeline — what runs where, which credentials are present, and where Python code and shell scripts execute.

---

## 1. Entry Points

There are **four** distinct entry points that feed skills into the Gauntlet. They all converge on the same static-analysis pipeline but differ in how they get there.

| Entry point | Trigger | Runs on | Code path |
|---|---|---|---|
| **CLI publish** | `dhub publish` | Client machine → Modal web container | `client/.../registry.py` → `POST /v1/publish` → `registry_routes.py` |
| **Crawler** | `python -m decision_hub.scripts.github_crawler` | Developer machine → Modal `crawl_process_repo` containers | `crawler/__main__.py` → `modal.Function.map()` → `processing.py` |
| **Tracker cron** | Modal scheduled function (every 5 min) | Modal `check_trackers` container | `modal_app.py:check_trackers()` → `tracker_service.py` |
| **Frontend (indirect)** | Web UI triggers publish via API | Same as CLI publish | Same `POST /v1/publish` endpoint |

---

## 2. Infrastructure Layout

### 2.1 Modal App (`modal_app.py`)

A single Modal app (`decision-hub` for prod, `decision-hub-dev` for dev) defines four functions:

| Function | Type | Image | Timeout | Purpose |
|---|---|---|---|---|
| `web()` | `@modal.asgi_app` | `debian_slim` + `dhub-core` + server deps | — (long-lived) | Serves the FastAPI app (all HTTP endpoints) |
| `run_eval_task()` | Regular function | Same as `web` | 1800s (30 min) | Runs agent assessments (evals) in their own container |
| `crawl_process_repo()` | Regular function | Same + `git` | 300s (5 min) | Clones a repo, runs Gauntlet, publishes skills |
| `check_trackers()` | Scheduled (5 min period) | Same as `web` | 600s (10 min) | Polls GitHub for repo changes, republishes |

### 2.2 Secrets Injected into Modal Containers

All four functions share the same secret bundles (defined in `modal_app.py`):

```
decision-hub-db[-dev]       → DATABASE_URL
decision-hub-secrets[-dev]  → JWT_SECRET, FERNET_KEY, GITHUB_CLIENT_ID, GOOGLE_API_KEY, GITHUB_TOKEN
decision-hub-aws[-dev]      → AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET, AWS_REGION
```

Plus a `from_dict` secret injecting `MODAL_APP_NAME` and optionally `MIN_CLI_VERSION`.

### 2.3 External Services

| Service | Used by | Credential |
|---|---|---|
| **PostgreSQL** (Supabase) | All server code | `DATABASE_URL` |
| **S3** (AWS) | Skill zip storage, eval logs, quarantine | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` |
| **Gemini API** (Google) | LLM safety judge, classification, search | `GOOGLE_API_KEY` |
| **Anthropic API** | Eval LLM judge | User's stored `ANTHROPIC_API_KEY` (Fernet-encrypted in DB) |
| **GitHub API** | Crawler discovery, tracker polling, OAuth | `GITHUB_TOKEN` (system) or user's stored token |
| **Modal** | Sandbox creation for evals, function spawning | Implicit (Modal SDK auth) |

---

## 3. The Gauntlet Pipeline (Static Analysis)

The Gauntlet is **pure Python, no sandboxes, no shell scripts**. It runs synchronously inside whichever process triggers it. The core function is:

```
gauntlet.py:run_static_checks() → GauntletReport
```

Called via the wrapper `registry_service.py:run_gauntlet_pipeline()` which also serializes results for audit logging.

### 3.1 Where It Executes

| Entry point | Gauntlet runs in |
|---|---|
| CLI publish (`POST /v1/publish`) | Modal `web()` container (threadpool, since the handler is sync `def`) |
| Crawler | Modal `crawl_process_repo()` container |
| Tracker | Modal `check_trackers()` container |

In all cases, the Gauntlet runs **inside a Modal container** with access to `GOOGLE_API_KEY` for the LLM judge.

### 3.2 Checks Performed (in order)

1. **`check_manifest_schema`** — Parses YAML frontmatter, verifies `name` and `description` fields exist.
   - Pure Python (PyYAML). No external calls.

2. **`check_dependency_audit`** — Scans lockfile for blocked packages (`invoke`, `fabric`, `paramiko`).
   - Pure Python string matching. Only runs if a lockfile exists.

3. **`check_embedded_credentials`** — Two layers:
   - **Known-format patterns**: Regexes for AWS keys, GitHub tokens, Stripe keys, JWTs, PEM keys, etc.
   - **Shannon entropy scanner**: Extracts string literals, flags those with entropy above threshold.
   - Pure Python. Always rejects on match (no LLM override). Never legitimate to embed real secrets.

4. **`check_safety_scan`** — Two-stage code safety:
   - **Stage 1 (regex)**: Scans `.py` files for `subprocess`, `os.system`, `eval()`, `exec()`, `__import__`, hardcoded credentials.
   - **Stage 2 (LLM judge)**: If `GOOGLE_API_KEY` is set, sends regex hits + skill metadata to **Gemini** (`gemini.py:analyze_code_safety()`). Gemini decides if each hit is genuinely dangerous or legitimate for the skill's purpose. Fail-closed: uncovered hits are treated as dangerous.
   - **Credential**: `GOOGLE_API_KEY` (from Modal secrets).

5. **`check_prompt_safety`** — Two-stage prompt injection scan of SKILL.md body:
   - **Stage 1 (regex)**: Instruction overrides, role hijacks, memory wipes, zero-width unicode, exfiltration URLs, tool escalation markup.
   - **Stage 2 (LLM judge)**: Gemini classifies each hit as dangerous/ambiguous/safe (`gemini.py:analyze_prompt_safety()`).
   - **Stage 3 (holistic review)**: If regex found nothing but LLM is available, runs a full-body review (`gemini.py:review_prompt_body_safety()`) to catch sophisticated injection that bypasses patterns.
   - **Credential**: `GOOGLE_API_KEY`.

6. **`detect_elevated_permissions`** — Scans source + `allowed_tools` for shell, network, fs_write, env_var patterns.
   - Pure Python regex. Doesn't fail — feeds into grade calculation.

### 3.3 Grading

```
compute_grade(results, elevated_permissions, is_verified_org) → A/B/C/F
```

| Grade | Meaning |
|---|---|
| **F** | Any check failed → skill is **rejected** (quarantined) |
| **C** | Any check warned (ambiguous LLM judgment) |
| **B** | Elevated permissions detected, or unverified org |
| **A** | All clear |

Grade F skills are never published. They are uploaded to `rejected/{org}/{skill}/{version}.zip` in S3 and an audit log is written.

---

## 4. Detailed Workflow per Entry Point

### 4.1 CLI Publish (`dhub publish`)

**Client machine** (user's laptop):

1. CLI discovers skill directories, reads `SKILL.md`, creates zip archive in memory.
2. Fetches latest version from server, auto-bumps, computes checksum. Skips if checksum matches (no changes).
3. `POST /v1/publish` with multipart form: `metadata` (JSON) + `zip_file`.

**Modal `web()` container** (handling the HTTP request):

4. Authenticate user (JWT). Verify org membership.
5. Read zip bytes (50 MB limit), compute checksum.
6. `extract_for_evaluation(zip_bytes)` — unzip in memory, extract `SKILL.md`, `.py` files, lockfile. (Pure Python, no disk.)
7. `parse_manifest_from_content()` — write SKILL.md to a temp file, parse it with `dhub_core`, extract runtime config, eval config, eval cases, allowed_tools. Delete temp file.
8. **Run Gauntlet** (`run_gauntlet_pipeline()`) — all 5+ checks described in §3.
9. If grade F: upload zip to S3 quarantine, write audit log, return HTTP 422.
10. `classify_skill_category()` — Gemini LLM call to assign a taxonomy category. Non-critical, falls back to "Other & Utilities".
11. Upsert skill record in PostgreSQL. Check for duplicate version.
12. `generate_and_store_skill_embedding()` — Gemini embedding API call. Fail-open.
13. Upload zip to S3 at `skills/{org}/{skill}/{version}.zip`.
14. Insert version record. Insert audit log. **Commit transaction.**
15. `maybe_trigger_agent_assessment()` — if `evals:` config exists in manifest:
    - Generate UUID for run, create `eval_runs` row in fresh DB connection.
    - `modal.Function.from_name("decision-hub[-dev]", "run_eval_task").spawn(...)` — fire-and-forget to a separate Modal container.
16. Return `PublishResponse` with grade, version, eval run ID.

**Back on client machine**:

17. CLI prints grade, warnings. If eval was triggered, tails logs via polling `GET /v1/eval-runs/{id}/logs`.

### 4.2 Crawler

**Developer machine** (running the script from `server/`):

1. `python -m decision_hub.scripts.github_crawler` — parses args, loads settings from `.env.dev`/`.env.prod`.
2. **Discovery phase**: Calls GitHub Search API via `httpx` to find repos containing `SKILL.md`. Strategies: file-size partitioning, path search, topic search, curated lists, fork scanning. Yields batches incrementally.
3. Saves discovered repos to a local checkpoint file (`crawl_checkpoint.json`).
4. **Change detection**: For previously-crawled repos, fetches HEAD SHA from GitHub API to skip unchanged repos.

**Fan-out to Modal `crawl_process_repo()` containers** (up to 50 concurrent):

5. `modal.Function.from_name(app_name, "crawl_process_repo").map(chunk_dicts, ...)` — sends batches of repo dicts.
6. Each Modal container:
   a. Loads `Settings` from env vars (injected by Modal secrets).
   b. Creates DB engine, S3 client.
   c. Ensures org exists in DB (creates if needed). Syncs GitHub metadata (avatar, bio).
   d. `clone_repo()` — runs `git clone` as a **subprocess** inside the Modal container. The `crawler_image` has `git` installed.
   e. `discover_skills(repo_root)` — walks the file tree for `SKILL.md` files.
   f. For each skill directory:
      - `create_zip()` — zips skill directory in memory.
      - `extract_for_evaluation()` — extracts evaluation files.
      - **Run Gauntlet** (same pipeline as §4.1, step 8).
      - If grade F: quarantine to S3, write audit log.
      - If passed: classify category (Gemini), generate embedding (Gemini), upload to S3, insert version + audit log.
7. Returns result dict to the developer machine. Checkpoint is updated.

**Key difference from CLI publish**: No eval assessment is triggered. No user auth (uses a bot user `dhub-crawler`). Runs `git` as a subprocess.

### 4.3 Tracker Cron

**Modal `check_trackers()` container** (scheduled every 5 min):

1. Load settings. `claim_due_trackers()` — atomically claim a batch of trackers from DB.
2. For each tracker:
   a. Resolve GitHub token (user's stored encrypted token → decrypt with Fernet, or fall back to system `GITHUB_TOKEN`).
   b. `has_new_commits()` — `httpx.get()` to GitHub API comparing stored SHA with current HEAD.
   c. If no changes: update `last_checked_at`, continue.
   d. `clone_repo()` — **subprocess** `git clone` inside the Modal container.
   e. `discover_skills()` → for each skill:
      - Same pipeline as crawler: zip → extract → **Gauntlet** → publish or quarantine.
      - Also calls `maybe_trigger_agent_assessment()` if eval config exists (spawns `run_eval_task`).
   f. Update tracker row: advance `last_commit_sha`, `last_published_at`, clear/set `last_error`.

---

## 5. Agent Evals (Post-Gauntlet)

Evals are **separate from the Gauntlet** — they run after a skill passes the Gauntlet and is published. The Gauntlet is about static safety analysis; evals are about functional correctness via live agent execution.

### 5.1 Trigger

Evals are triggered when a skill's `SKILL.md` declares an `evals:` section with `agent` and `judge_model`, and the zip contains `evals/*.yaml` case files.

### 5.2 Execution: `run_eval_task()` Modal Container

**Modal container** (separate from `web()`, 30 min timeout):

1. Load settings. Download skill zip from S3.
2. Calls `run_assessment_background()`:
   a. **Load API keys**: Read user's encrypted keys from DB, decrypt with Fernet.
   b. **Validate keys**: Lightweight HTTP call to Anthropic `/v1/models` to verify key is valid before committing to a 15-min sandbox.
   c. **For each eval case**:

### 5.3 Modal Sandbox (nested inside `run_eval_task`)

The eval container creates **another** Modal sandbox for each test case:

```python
modal.Sandbox.create(image=image, secrets=[modal.Secret.from_dict(env)], app=app, ...)
```

**Inside the sandbox** (a `node:20-slim` container with Python, the agent CLI, and `uv`):

- **Image**: `node:20-slim` + `python3` + `curl` + `git` + agent NPM package (e.g. `@anthropic-ai/claude-code`) + `uv`.
- **User**: A non-root `sandbox` user (Claude Code refuses `--dangerously-skip-permissions` as root).
- **Env vars**: Agent API key (e.g. `ANTHROPIC_API_KEY`), `HOME=/home/sandbox`, `SKILL_PATH`, agent-specific extras.
- **Setup steps** (all inside the sandbox):
  1. `sb.mkdir()` — create skill directory.
  2. `sb.open()` — write each file from the zip (no shell needed, uses Modal filesystem API).
  3. `uv sync` — install Python deps if `pyproject.toml` exists (**shell command** via `sb.exec("bash", "-c", ...)`).
  4. Write `CLAUDE.md` at project root (skill body as system prompt for Claude Code).
  5. `git init` + `git commit` — so Claude Code recognizes a project root (**shell command**).
  6. `chown -R sandbox:sandbox /home/sandbox` (**shell command**).

- **Agent execution**:
  1. An inner shell script (`/tmp/run_inner.sh`) prepends the skill venv to `$PATH` and runs the agent command.
  2. An outer shell script (`/tmp/run_agent.sh`) runs the inner script as `su -m sandbox`, redirecting stdout/stderr to files.
  3. The outer script is backgrounded with `nohup`.
  4. A **Python monitor script** (`MONITOR_SCRIPT`) runs as root, tails the output files using seek offsets, and prints structured `OUT:`, `ERR:`, `RC:` lines.
  5. The parent process reads monitor output, yielding streaming events.

- **After agent finishes**:
  1. Sandbox is terminated.
  2. If exit code != 0: verdict = "error", skip judge.
  3. If exit code == 0: call **Anthropic API** (`anthropic_client.py:judge_eval_output()`) with the agent's stdout and the case's judge criteria. Uses the **user's** stored `ANTHROPIC_API_KEY` (not the system key).

### 5.4 Credential Flow for Evals

```
User stores API key via CLI → encrypted with Fernet → stored in user_api_keys table
                                                              ↓
run_eval_task() container reads encrypted keys from DB → decrypts with FERNET_KEY
                                                              ↓
                                    Passes decrypted keys as env vars to Modal Sandbox
                                                              ↓
                                    Agent process inside sandbox reads from $ANTHROPIC_API_KEY
```

The `FERNET_KEY` is a Modal secret. The user's API keys never leave the Modal infrastructure unencrypted.

---

## 6. Where Code Executes — Summary

| Code | Execution environment | Language |
|---|---|---|
| CLI (`dhub publish/install/list`) | User's machine | Python (Typer) |
| Crawler discovery (GitHub API calls) | Developer's machine | Python (httpx) |
| Crawler processing fan-out (`fn.map()`) | Developer's machine → Modal | Python (Modal SDK) |
| Repo cloning (`git clone`) | Modal container (subprocess) | Shell (git) |
| Gauntlet static checks | Modal container (in-process) | Pure Python |
| Gemini LLM calls (safety judge, classification) | Modal container → Google API | Python (httpx) |
| Skill zip upload/download | Modal container → AWS S3 | Python (boto3) |
| DB reads/writes | Modal container → PostgreSQL | Python (SQLAlchemy) |
| Eval sandbox setup (mkdir, file write, uv sync, git init) | Modal Sandbox container | Shell scripts + Python |
| Agent execution (Claude Code, Codex, Gemini CLI) | Modal Sandbox (as `sandbox` user) | Shell (agent CLI) |
| Monitor script (tail output files) | Modal Sandbox (as root) | Python |
| Eval judging (Anthropic API) | Modal `run_eval_task` container | Python (httpx) |
| Frontend | User's browser | TypeScript (React) |

---

## 7. Data Flow Diagram

```
                          ┌─────────────┐
                          │  User / CLI  │
                          └──────┬───────┘
                                 │ POST /v1/publish (zip + metadata)
                                 ▼
                    ┌────────────────────────────┐
                    │  Modal web() container     │
                    │                            │
                    │  1. Auth (JWT)             │
                    │  2. Extract zip in memory  │
                    │  3. Parse SKILL.md         │
                    │  4. ── GAUNTLET ────────── │
                    │     │ manifest_schema      │
                    │     │ dependency_audit     │
                    │     │ embedded_credentials │
                    │     │ safety_scan ──────────────── Gemini API (GOOGLE_API_KEY)
                    │     │ prompt_safety ────────────── Gemini API
                    │     │ elevated_permissions │
                    │     └─► Grade A/B/C/F     │
                    │  5. If F: quarantine ──────────── S3 (rejected/)
                    │  6. Classify category ─────────── Gemini API
                    │  7. Generate embedding ────────── Gemini API
                    │  8. Upload zip ────────────────── S3 (skills/)
                    │  9. Write DB records ──────────── PostgreSQL
                    │  10. Spawn eval (if config) ──┐  │
                    └───────────────────────────────┘  │
                                                       │ modal.Function.spawn()
                                                       ▼
                              ┌──────────────────────────────────┐
                              │  Modal run_eval_task() container │
                              │                                  │
                              │  1. Download zip from S3         │
                              │  2. Read+decrypt user API keys ──── PostgreSQL + FERNET_KEY
                              │  3. For each eval case:          │
                              │     ┌────────────────────────┐   │
                              │     │ Modal Sandbox          │   │
                              │     │ (node:20 + agent CLI)  │   │
                              │     │                        │   │
                              │     │ - Extract skill files  │   │
                              │     │ - uv sync (shell)      │   │
                              │     │ - git init (shell)     │   │
                              │     │ - Run agent (shell)    │   │
                              │     │ - Monitor (Python)     │   │
                              │     └────────────────────────┘   │
                              │  4. Judge output ────────────────── Anthropic API (user's key)
                              │  5. Write results ───────────────── PostgreSQL + S3 (logs)
                              └──────────────────────────────────┘
```

---

## 8. Credentials Matrix

| Credential | Stored in | Available in | Used for |
|---|---|---|---|
| `DATABASE_URL` | Modal secret `decision-hub-db[-dev]` | All Modal containers | PostgreSQL access |
| `AWS_ACCESS_KEY_ID` | Modal secret `decision-hub-aws[-dev]` | All Modal containers | S3 read/write |
| `AWS_SECRET_ACCESS_KEY` | Modal secret `decision-hub-aws[-dev]` | All Modal containers | S3 read/write |
| `S3_BUCKET` | Modal secret `decision-hub-aws[-dev]` | All Modal containers | Bucket name |
| `GOOGLE_API_KEY` | Modal secret `decision-hub-secrets[-dev]` | All Modal containers | Gemini LLM (safety judge, classification, search, embeddings) |
| `JWT_SECRET` | Modal secret `decision-hub-secrets[-dev]` | `web()` container | Signing/verifying auth tokens |
| `FERNET_KEY` | Modal secret `decision-hub-secrets[-dev]` | `web()`, `run_eval_task()` | Encrypting/decrypting user API keys at rest |
| `GITHUB_TOKEN` | Modal secret `decision-hub-secrets[-dev]` | All Modal containers | Tracker polling, crawler cloning (system fallback) |
| `GITHUB_CLIENT_ID` | Modal secret `decision-hub-secrets[-dev]` | `web()` container | OAuth device flow |
| User's `ANTHROPIC_API_KEY` | `user_api_keys` table (Fernet-encrypted) | Decrypted in `run_eval_task()`, passed to Sandbox as env var | Agent execution + eval judging |
| User's `GITHUB_TOKEN` | `user_api_keys` table (Fernet-encrypted) | Decrypted in tracker service | Private repo access for trackers |

**Key point**: The Sandbox (where untrusted agent code runs) only receives the user's agent API key. It does **not** have `DATABASE_URL`, `FERNET_KEY`, `GOOGLE_API_KEY`, or any system secrets. The Sandbox env is built explicitly from `agent_config.extra_env` + user's decrypted keys.
