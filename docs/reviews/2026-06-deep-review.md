# Decision Hub — Deep Codebase Review (2026-06-28)

## 1. High-Level Summary

Decision Hub is a uv-workspace monorepo registry for AI "skills" (declarative
agent capabilities). Stack: **FastAPI + SQLAlchemy Core + Postgres**
(Supabase/PgBouncer) on Modal, **Typer/Rich** CLI distributed via PyPI,
**React 19 + Vite** frontend bundled into the same Modal image at deploy time,
and a shared `dhub-core` package owning manifest and validation models.
Side services include Gemini for search/classification/safety,
Anthropic for eval judging, and the Cisco AI Skill Scanner alongside the
in-house gauntlet pipeline.

**Architectural health is good for a six-month-old project.** Boundaries
between client / server / shared are clear; domain logic sits behind
infra adapters; pure functions dominate; SQL is parameterised via
SQLAlchemy Core; routers are thin and call domain services. The data model
is sensible: orgs ▸ skills ▸ versions, with denormalised "latest_*"
columns on `skills` for cheap listings.

**Strengths:** strong test inventory (Python and Vitest) for the size,
careful security-headers + version-gate middleware, explicit rate limiting
per public endpoint, working pre-commit + CI hooks, and unusually
thoughtful design notes in CLAUDE.md.

**Top risks:**
- Several large modules (`infra/database.py` 3,465 LoC,
  `cli/registry.py` 1,912 LoC, `domain/gauntlet.py` 1,355 LoC,
  `api/registry_routes.py` 1,352 LoC, `infra/gemini.py` 1,154 LoC)
  are starting to absorb unrelated concerns. None require an immediate
  break-up but each is approaching the size where they become hard to
  navigate.
- A few performance footguns: per-IP visibility grant fetches issued on
  every list query, per-repo UPDATE loops in GitHub-metadata batch jobs,
  swallowed errors masking infrastructure failures behind silent fallbacks.
- Wallpaper-thin DRY in two places — nine near-identical lazy
  rate-limiter factories in the API layer, twenty-five copies of
  `with httpx.Client(timeout=60)` in the CLI — both prime targets for
  a small mechanical cleanup.
- LLM call sites in `gemini.py` are missing a few cheap safety nets
  (timeout on the shared client, validation of LLM-returned skill
  references, prompt-injection hardening on user-supplied queries and
  metadata). Low severity individually, cumulatively a class of issue
  worth one focused PR.

**Test / observability state:** request-scoped logging with correlation
IDs is set up, log levels are env-driven, and metrics are recorded for
trackers. Tests cluster heavily around domain/auth/search; CLI commands
`delete`, `info`, `visibility`, `eval-report` and `logs` are
under-tested; the frontend lacks an `ErrorBoundary` and tests for
`FileBrowser`, infinite-scroll filters, and copy/download.

**DX:** tooling is excellent (ruff + mypy + pre-commit + Makefile,
schema-drift CI gate, migration replay). The main DX irritation today
is the cost of navigating the five very-large files.

**Strategic outlook:** the codebase is healthy and the team is using
good guardrails. Next 3–6 months: keep the big-five files from
swallowing new concerns by splitting them on natural seams
(scan/tracker/audit-log groupings in `database.py`; per-command
sub-modules in `cli/registry.py`; one prompt-builder module in
`gemini.py`). Invest in a small CLI-API client helper to remove the
duplicated `httpx` boilerplate.

## 2. System Map

```
            ┌──────────────────────┐        ┌────────────────────┐
   CLI ───▶ │ FastAPI (Modal app)  │ ───▶  │  Postgres (Supabase)│
 (dhub)     │  • registry_routes    │        │  • skills + versions│
            │  • search/ask         │        │  • skill_trackers  │
            │  • auth/keys/orgs     │        │  • scan_reports    │
            │  • trackers           │        │  • audit logs      │
 Frontend ─▶│ + SPA fallback        │        └────────────────────┘
 (React)    │                      │
            │  Domain               │  ┌──────────┐ ┌──────────┐
            │  • publish_pipeline ─▶│  │   S3     │ │ Gemini   │
            │  • gauntlet           │  └──────────┘ └──────────┘
            │  • trackers           │  ┌──────────┐ ┌──────────┐
            │  • evals (Modal-fan)  │  │ Anthropic│ │ Modal    │
            └──────────────────────┘  └──────────┘ └──────────┘
```

`shared/dhub_core` owns SKILL.md manifest parsing, semver, and
validation — imported by both CLI and server, so changes are
double-released by design.

**Data/control flow — happy publish path:**

1. CLI zips a directory, sends `POST /v1/publish` with metadata + zip.
2. Middleware: request-id, security headers, CLI-version gate.
3. Route validates JSON, semver, name; rejects blocked orgs;
   enforces org-membership; reads up to 50 MB.
4. `execute_publish` runs the gauntlet (Gemini-backed regex →
   LLM judgement), uploads to S3, writes the version row, refreshes the
   denormalised `latest_*` columns, and emits an audit log.
5. If `enable_cisco_scanner`, the Cisco scan runs in the same
   try-block, but its output is best-effort.
6. Response carries the new version metadata; the eval-run is fired
   asynchronously into a Modal app.

**Unclear / scary areas:**
- The denormalised `latest_*` columns on `skills` are written by
  `_refresh_skill_latest_version` only on version *insert / delete* — a
  later UPDATE to a version row (e.g. eval-status flip) does not
  refresh them.
- The skill-tracker reconciliation loop owns mid-job rollback decisions
  that are scattered between `tracker_service` and `publish_pipeline`.

## 3. Top 12 High-Leverage Changes

| # | Title | Category | Impact | Effort | Next Steps |
|---|-------|----------|--------|--------|------------|
| 1 | Collapse 9 near-identical `_enforce_*_rate_limit` lazy-factories into one shared helper | code-health | M | S | Add `get_or_create_rate_limiter(request, name, max_req, window)` to `rate_limit.py`; use it from `registry_routes`, `search_routes`, `auth_routes`. |
| 2 | Replace per-repo UPDATE loop in `batch_update_github_*` with a single CASE/VALUES batch | performance | M | S | Use one UPDATE with `CASE WHEN url=...` or a VALUES-driven subquery. Cuts 100 round-trips to 1 on hourly tracker reconciliation. |
| 3 | Apply `_escape_like` everywhere LIKE patterns interpolate user-controlled URLs | security | M | S | Lines 1197 + 1220 of `database.py` already have safe twins at 3135/3163. Mirror them. |
| 4 | URL-encode `org_slug`/`skill_name` in the download Content-Disposition header | security | L | S | `urllib.parse.quote(...)` around the components used in `filename=...` in `registry_routes.py`. |
| 5 | Pull `httpx.Client(timeout=60)` out of 25 sites in `cli/registry.py` into named constants and bump download timeout | code-health / bug | M | S | `_API_TIMEOUT = 60`, `_DOWNLOAD_TIMEOUT = 300`; default `client.get(download_url)` uses the second. |
| 6 | Refactor `_apply_visibility_filter` to take grants as a lazy subquery so it stops issuing an extra round-trip per list query | performance | M | M | One small SQL helper, plus updating six callers in `database.py`. |
| 7 | Add an explicit timeout to the shared httpx client passed into Gemini calls so retries don't multiply a stuck request | bugs | M | S | `httpx.Client(timeout=httpx.Timeout(30))` in `create_gemini_client`. |
| 8 | Validate LLM-returned `org_slug`/`skill_name` against the candidate map before returning them to clients (don't surface hallucinated rows) | bugs / security | M | S | `_ask_skills_inner` already builds `candidate_map`; drop refs whose keys aren't in it (already partly done; tighten and log when dropped). |
| 9 | Refresh `skills.latest_*` denormalised columns on version UPDATE, not just INSERT/DELETE | bugs / correctness | M | M | Either call `_refresh_skill_latest_version` from `update_eval_run_status` paths that mutate version state, or attach a Postgres trigger. |
| 10 | Add an Error Boundary at the SPA root and an `<AsyncView />` to consolidate loading/error UI (currently duplicated across ~6 pages) | code-health | M | S | Wrap `<Layout />` in an error boundary, create `useCopyToClipboard` + `<AsyncView />`. |
| 11 | Extract per-command modules from `cli/registry.py` once the file passes ~2k LoC | architecture | M | M | Phase: pull `delete`, `info`, `logs`, `visibility`, `eval-report` into siblings of `registry.py`; keep imports stable for now. |
| 12 | Tests: `delete_command`, `visibility_command`, `info_command`, `eval_report_command`, `FileBrowser`, and `useCopyToClipboard` | testing | M | M | One pytest class + one vitest suite per untested command/component. |

## 4. Test Suite Recommendations

### 4a. Inventory

- **Server pytest:** 21 domain tests + 16 API tests + 3 script tests + 4 infra tests. Heavy on `gauntlet`, `tracker_service`, `evals`, `publish`. Good fixtures (`conftest.py`, `factories.py`, `helpers.py`).
- **Client pytest:** 18 CLI tests + 6 core tests. Strong on `publish`, `install`, `init`, `version-check`; weak on `delete`, `info`, `visibility`, `logs`, `eval-report`.
- **Shared:** `manifest`, `validation`, `ziputil` — adequate.
- **Frontend vitest:** 8 component/page tests, `AskModal` and `useApi` are deeply tested. `FileBrowser`, `OrgDetailPage`, `OrgsPage`, `ScannerReport` lack tests.

### 4b. Target strategy

- Pyramid: more unit tests around domain pure functions (gauntlet
  helpers, search index serialisation, manifest parse). Integration
  tests at the route level for the read paths (already strong).
- One e2e smoke for `publish → list → download` against the local
  stack, runnable via `make` (not in CI by default).

### 4c. Top 10 tests to add

1. CLI `delete_command` dry-run + 404 + 403 + JSON output.
2. CLI `visibility_command` happy path + invalid value + 403.
3. CLI `info_command` happy path + 404 + non-published.
4. CLI `eval_report_command` happy path + bad ref + 404.
5. Frontend `FileBrowser` render / expand / filter.
6. Frontend `useCopyToClipboard` cleanup on unmount.
7. Server `batch_update_github_repo_metadata` SQL shape (one statement,
   no N+1).
8. Server `_apply_visibility_filter` correctness with org-grant edge
   cases.
9. Server `has_active_tracker_for_repo` returns False on
   disabled / wrong-URL trackers.
10. Server `_refresh_skill_latest_version` invoked on eval-status
    changes.

### 4d. Tests to remove / reclassify

- `test_slow` LLM tests should remain marked `slow` and out of CI.
  Consider gating with `pytest --runslow` and skipping by default to
  avoid accidental cost.

### 4e. Flakiness / speed

- `time.sleep`-style delays in `test_version_check.py` are fine; nothing
  jumped out as flaky.

### 4f. Test-design improvements

- Frontend: switch from prop-drilled fakes to MSW for `client.test.ts`
  so the fetch wrapper is exercised in tests too.
- Server: many tests instantiate `engine` per test — fixture-scope this
  to `session` for read-only tests.

### 4g. Tooling / CI

- Add a CI job that runs `make test-frontend -- --coverage` (vitest
  already supports). Today the frontend coverage isn't visible in PRs.

### 4h. Phased migration plan

- **Phase 1 (this PR):** rate-limit DRY + batch GitHub update perf +
  LIKE escaping + filename encoding + new tests.
- **Phase 2:** httpx-timeout constants in CLI + visibility-filter
  cache + denormalisation refresh fix.
- **Phase 3:** prompt-builder extraction in `gemini.py`,
  `<AsyncView />` + error boundary on the frontend.
- **Phase 4:** modular break-up of `cli/registry.py` (commands as
  siblings), and of `database.py` (per-domain query files).
- **Phase 5:** add MSW-based fetch coverage and a `make e2e-local`
  smoke test.

## 5. Detailed Findings by Category

### Architecture & Design
- `cli/registry.py` is now the catch-all for every CLI command. The
  per-command structure already exists for `auth`, `org`, `keys`,
  `access`, `search` — extending the same pattern keeps the code base
  navigable.
- `domain/publish_pipeline.py` reaches across `infra/storage`,
  `infra/database`, `infra/gemini`, `infra/modal_client`. It is the
  natural orchestration boundary, so this coupling is expected; the
  Cisco scanner block should be moved into its own
  `_run_optional_scanners` helper so it can no longer accidentally
  fail the critical path.
- `infra/database.py` mixes table definitions, row mappers, CRUD
  helpers, batch operations, and analytic queries. Split candidates
  along the `Skill`, `Tracker`, `ScanReport`, `EvalRun`, `AuditLog`,
  `Org` lines.

### Code Health & Dead Code
- Nine near-identical `_enforce_*_rate_limit` helpers
  (`registry_routes.py:86-167`, `search_routes.py:32-41`,
  `auth_routes.py:29-`). Single helper kills 80+ LoC.
- 25 `httpx.Client(timeout=60)` literals in `cli/registry.py`.
- `SkillSummary` Pydantic model has 24 fields, half are GitHub metadata.
  Worth grouping into a nested `GitHubMetadata` model for readability.

### Bugs, Correctness & Edge Cases
- `_refresh_skill_latest_version` not called on version UPDATE → stale
  denormalised columns when eval-status flips for the latest version.
- The shared `httpx.Client` passed into `create_gemini_client` has no
  default timeout, so the per-call timeout is bypassed for shared
  clients (`gemini.py:104`).
- LLM-returned skill references are returned to clients without checking
  the candidate map for org-grant visibility; rare in practice because
  the candidate map drives the prompt, but a defensive filter is cheap.
- `_install_single_skill` downloads use the surrounding
  `httpx.Client(timeout=60)` — a 60-second cap on multi-megabyte zip
  downloads.

### Security
- `batch_update_github_stars` / `batch_update_github_repo_metadata`
  build `like(f"{repo_url}/%")` without escaping `%` / `_` /
  backslash. Not a SQL injection (SQLA still parameterises) but a
  wildcard-injection vector. Mirror the `_escape_like` pattern already
  used at lines 3135 / 3163.
- `Content-Disposition: attachment; filename=...` in the download
  route uses raw `org_slug` / `skill_name`. Encode via
  `urllib.parse.quote` to defang slashes / quotes.
- `parse_query_with_guard` interpolates the user query directly into
  the prompt; the existing prompt is robust but the surface deserves a
  comment, and the failure path should distinguish "Gemini down"
  from "looked off-topic".
- `analyze_code_safety` / `review_code_body_safety` truncate files but
  with separate loops; extract to a single `_truncate_files_to_cap`.

### Performance & Reliability
- `list_granted_skill_ids` is invoked from every visibility-filtered
  list / resolve / search query. Cache per-request or pass as a
  scalar-subquery.
- `batch_update_github_*` loops issue one UPDATE per repo; collapse
  into a single statement.
- `claim_due_trackers` orders by `next_check_at ASC NULLS FIRST` but no
  matching partial index exists on `enabled=true`. Cheap to add.
- Skill list query already uses `COUNT(*) OVER()` for the page total
  — good — but pagination of `list_all_org_profiles` is missing.

### Testing & Observability
- CLI tests skew toward publish/install. Adding pytest classes for
  `delete`, `info`, `visibility`, `eval-report`, `logs` is mechanical
  and high-value.
- No `ErrorBoundary` on the SPA — a render-time bug in markdown or
  scanner-report tabs unmounts the entire page.
- Logging is correct; metrics would benefit from a `publish_latency`
  histogram and a `tracker_failure_total` counter.

### Standards, Consistency & DX
- Naming and structure are consistent; CLAUDE.md is unusually rich.
- Frontend uses CSS Modules; spot-check at 400 px shows the
  `SkillDetailPage` tabs row needs `flex-wrap` to avoid overflow.

### External libraries
- `pgvector.sqlalchemy.Vector(768)` — fine.
- `loguru` configured once at startup as documented.
- `pydantic-settings` `.env.{env}` resolution is path-relative to CWD —
  already documented in CLAUDE.md.
- `httpx` is used everywhere but never with retry helpers; consider
  `httpx.Transport(retries=N)` for the CLI.
- `boto3` clients are created at app start — correct for Modal.

## 6. Non-Obvious Insights / Time Bombs

- The denormalised-column refresh gap is a quiet correctness bomb: it
  *looks* fine because publish + delete are the most common
  transitions, but any later `update_eval_run_status` that mutates a
  latest version leaves `skills.latest_eval_status` stale.
- The CLI's `httpx.Client(timeout=60)` literal-explosion will become
  the obvious "why don't downloads work behind corporate proxies?"
  bug. Centralising the timeout is the cheapest hedge.
- The 9 rate-limit factories are tempting to copy when adding a new
  endpoint — fixing now blocks the next copy.
- `cli/registry.py` at 1,912 LoC is past the point where developers
  start scrolling — each new feature accelerates the rot.

## 7. Open Questions & Assumptions

- Are concurrent publishes for the same skill rare enough that the
  current "fetch grants then filter" race is acceptable? (Assume yes.)
- Is the Cisco scanner allowed to fail loud (block publish) or must
  it stay best-effort? (Assume best-effort, but the failure path
  should be logged loudly and isolated from the gauntlet try-block.)
- Are there target SLOs on `claim_due_trackers` throughput that would
  justify the index addition this PR cycle?
