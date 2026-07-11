# Codebase Review — 2026-07-11

Author: automated principal-engineer review (scheduled).
Scope: `client/`, `server/`, `shared/`, `frontend/`.

## 1. High-Level Summary

- **Purpose.** decision-hub is a two-sided registry for Anthropic Skills — a CLI (`dhub`, PyPI-published from `client/`) authors and publishes SKILL.md packages, a FastAPI backend (`server/`, deployed on Modal) stores/searches/evaluates them, and a React SPA (`frontend/`) is the public browsing surface. A shared library (`shared/dhub_core`) owns manifest parsing and validation.
- **Stack.** Python 3.11 + FastAPI + Pydantic + SQLAlchemy Core (raw SQL migrations, no Alembic) + Postgres + S3, Typer + Rich CLI, React 19 + Vite + CSS Modules on the front end, LLMs used are Gemini (search/classify/gauntlet) and Anthropic (eval judging).
- **Architectural health.** Layering is fundamentally sound: API → domain → infra with the `shared/` package as a single source of truth for models. The boundaries are respected in most places. The main problems are (a) two very large "god files" — `infra/database.py` (3465 lines) and `cli/registry.py` (1912 lines) — that fuse many responsibilities and dominate churn, and (b) accumulated duplication in the frontend and client-side shim modules that provide no abstraction, only friction.
- **Strengths.** Real tests exist across all four packages (see §4a for counts). Rate limiting, security headers, request IDs and structured logging are in place on the API. Migrations are validated in CI (`migrate-check`, `schema-drift`). The manifest parser lives in `shared/` and is the single source of truth. Recent DB/domain code follows a clean row → domain → response pattern.
- **Risks.** The 3465-line `database.py` mixes table declarations, query functions, and connection setup — safe schema changes require reading the whole file. `cli/registry.py` holds 10 top-level commands with intertwined helpers; a `74%` line coverage hides gaps in error paths (`1786-1912` uncovered). Frontend has 3 near-identical skill-card blocks (SkillsPage / OrgDetailPage / HomePage) that will drift. Two shim modules (`client/src/dhub/models.py`, `client/src/dhub/core/manifest.py`) create two ways to import the same symbols and are used inconsistently.
- **Test / observability state.** 291 passing client tests, 82 passing frontend tests, 56 server test files, 3 shared. Server coverage isn't reported by CI. Server logs via loguru with request IDs; no metrics or tracing.
- **Strategic outlook.** No emergency. But the god-files are exactly the class of code where a preventable bug will land the moment an unfamiliar contributor opens the file. Splitting `database.py` and `cli/registry.py` are the two highest-leverage projects on the 6-month horizon.

## 2. System Map

### Components

| Layer | Package | Entry point | Notes |
|---|---|---|---|
| CLI | `client/` (`dhub-cli`) | `dhub.cli.app:run` | Typer app; subcommands split by domain except `registry.py` (monolith) |
| Web UI | `frontend/` (Vite React SPA) | `App.tsx` | Bundled into Modal image at deploy |
| API | `server/api/` | `api/app.py::create_app()` mounted by Modal via `modal_app.py::@asgi_app` | 9 routers; `app.py` wires middlewares |
| Domain | `server/domain/` | Called from API | Auth, publish, evals, gauntlet, tracker, search, classification |
| Infra | `server/infra/` | Adapters | Postgres, S3, GitHub, Gemini, Anthropic, Modal, cache, embeddings |
| Shared | `shared/dhub_core/` | Imported by client & server | SkillManifest / RuntimeConfig / manifest parsing / validation |
| Background | `server/scripts/`, `modal_app.py` cron | `run_eval_task`, `crawl_process_repo`, `crawl_trusted_orgs_nightly` | Modal functions |

### Data & control flow (publish path — representative)

```
dhub publish <path>
  ├─ client/cli/registry.py       (validates manifest via dhub_core.manifest)
  ├─ client/core/git_repo.py       (locates skill in local repo)
  ├─ POST /publish  ── api/registry_routes.py
  │                    ├─ deps.py (auth)
  │                    ├─ rate_limit.py
  │                    └─ registry_service.py → domain/publish_pipeline.py
  │                                              ├─ domain/gauntlet.py (LLM safety scan)
  │                                              ├─ infra/storage.py    (S3 upload)
  │                                              ├─ infra/database.py   (row inserts)
  │                                              └─ domain/classification.py (LLM taxonomy)
  └─ response persisted, returned to CLI, printed by client/cli/output.py
```

### Unclear areas (assumptions I made)

- `registry_service.py` sits inside `api/` but is service-shaped. Treated as thin adapter used by `registry_routes.py` only.
- Recent tracker work touched 5 files; I did not deep-audit the tracker code path.
- Rate limits are per-container Modal replicas; per CLAUDE.md this is intended, not a bug.

## 3. Top 10 High-Leverage Changes

Ranked by impact / effort ratio. `H/M/L` = impact and effort respectively.

| # | Title | Category | Impact | Effort | Next Steps |
|---|---|---|---|---|---|
| 1 | Split `server/infra/database.py` (3465 lines) into `database/tables.py`, `database/skills.py`, `database/orgs.py`, `database/evals.py`, `database/trackers.py`, `database/engine.py` | architecture | H | M | Phase 1: move table definitions unchanged; phase 2: split queries by domain aggregate; keep `database.py` as a barrel export for one release to avoid touching every call site at once. |
| 2 | Split `client/src/dhub/cli/registry.py` (1912 lines) into `cli/publish.py`, `cli/install.py`, `cli/list.py`, `cli/info.py`, `cli/logs.py`, `cli/eval_report.py`, `cli/update.py`, `cli/visibility.py`, `cli/uninstall.py`, `cli/delete.py` matching the existing per-domain convention (`auth.py`, `search.py`, etc.) | architecture | H | M | Extract one command per PR, keep helpers in `cli/_registry_helpers.py`, add tests as you go. |
| 3 | Extract shared `<SkillCard>` component; replace 3 duplicated blocks in `HomePage.tsx`, `SkillsPage.tsx`, `OrgDetailPage.tsx` | code-health | M | S | Component takes `skill` + `variant` ("full" \| "compact") + `showOrg` props; consolidate the `.card*` vs `.skill*` CSS. |
| 4 | Remove client-side shim modules `client/src/dhub/models.py` and `client/src/dhub/core/manifest.py` and update ~7 call sites to import from `dhub_core.*` directly | code-health | M | S | Included in this PR — see refactor below. |
| 5 | Extract `CheckResultsGrid` and `formatCheckName` from `SkillDetailPage.tsx` (785 lines) into `components/CheckResultsGrid.tsx` — matches the existing test filename (`CheckResultsGrid.test.tsx`) which currently has no matching source file | code-health | M | S | Included in this PR — see refactor below. |
| 6 | Adopt react-query (or keep `useApi` but add request dedupe + a per-mount cache TTL); every page mount currently refetches. Two `// eslint-disable-next-line react-hooks/exhaustive-deps` in `useApi.ts` are smells | performance | M | M | Add react-query as a devDep, migrate `HomePage`, `SkillsPage`, `SkillDetailPage`; measure LCP before/after. |
| 7 | Add per-domain database test module under `server/tests/test_infra/`. The current single `test_database.py` cannot scale as `database.py` splits | testing | M | S | See §4b. |
| 8 | Add server-side coverage reporting to CI (`pytest --cov`), fail below a floor (e.g. 70%). Server has 56 test files but no visibility. | testing / DX | M | S | Add `pytest-cov` to server dev deps and a `test-server-cov` make target; gate CI. |
| 9 | Add basic OpenTelemetry tracing on `POST /publish` and `POST /ask` — the two paths where latency is user-facing and multi-step (LLM + S3 + DB) | observability | M | M | Instrument via `opentelemetry-instrumentation-fastapi`; export to Grafana Tempo or console during local dev. |
| 10 | Replace `describe(...) { it(...) }` UI tests that assert on CSS class substrings (`[class*=checkCard]`, `[class*=checkMessageExpanded]`) with data-testid selectors; these tests break silently on CSS Module hash changes | testing | L | S | Add `data-testid` to affected elements, update 5 assertions in `CheckResultsGrid.test.tsx`. |

## 4. Test Suite Recommendations

### 4a. Inventory

| Package | Test files | Tests | Coverage |
|---|---|---|---|
| `client/` | 24 (17 CLI, 7 core) | 291 passing, 29 skipped | 78% line (`registry.py` 74%) |
| `shared/` | 3 (manifest, validation, ziputil) | 57 | Not reported |
| `server/` | 56 (api 18, domain 18, infra 18, scripts 2) | Not counted here | **Not reported by CI** |
| `frontend/` | 8 (client, 2 hooks, 3 pages, 1 component, 1 orphan) | 82 passing | Not tracked |

### 4b. Target strategy (test pyramid)

- **Wide bottom (shared/domain).** Pure functions in `dhub_core` and `server/domain/*.py`. Add a `test_domain/test_publish_pipeline.py` that pins the happy path + 3 failure modes (bad manifest, S3 down, gauntlet fail). Currently covered indirectly through API tests.
- **Middle (API).** Keep the existing route-level tests but move heavy-mock fixture setup to `factories.py`. `test_registry_routes.py` at 1824 lines is dangerously wide — split by endpoint.
- **Narrow top (E2E).** Two `test-login-and-upload` and `test-upload-evals-skill` slash-commands exist; they are the only real E2E. Formalize as a `make test-e2e` target that runs against dev.

### 4c. Top 10 tests to add

1. `server/tests/test_domain/test_publish_pipeline.py::test_gauntlet_fail_leaves_no_dangling_s3_object` — verify S3 rollback on gauntlet reject.
2. `server/tests/test_infra/test_database_transaction_rollback.py::test_failed_skill_insert_rolls_back_version_row` — atomicity.
3. `server/tests/test_api/test_registry_routes.py::test_publish_over_rate_limit_returns_429_with_retry_after` — no assertion of retry-after header currently.
4. `server/tests/test_api/test_search_routes.py::test_ask_with_100kb_query_rejected_by_max_length` — payload cap enforcement.
5. `client/tests/test_cli/test_registry_cli.py::test_publish_when_server_returns_5xx_shows_actionable_error_not_traceback` — user-facing error path.
6. `client/tests/test_cli/test_registry_cli.py::test_install_partial_download_removes_partial_files` — cleanup after crash.
7. `shared/tests/test_manifest.py::test_manifest_with_yaml_alias_bomb_rejected` — YAML safety.
8. `frontend/src/pages/SkillsPage.test.tsx::test_pagination_uses_server_total_not_array_length` — CLAUDE.md rule already flagged.
9. `frontend/src/pages/SkillDetailPage.test.tsx::test_state_resets_when_navigating_to_different_skill` — the `useEffect` at line 73 exists; no test pins it.
10. `frontend/src/hooks/useApi.test.ts::test_cancelled_fetch_does_not_update_state_of_unmounted_component` — currently one assertion covers half of this.

### 4d. Tests to remove / reclassify

- `frontend/src/pages/CheckResultsGrid.test.tsx` — file is misnamed (there is no source file at the same path). Fixed in this PR by extracting `CheckResultsGrid` into `components/` and moving the test to match.
- `client/tests/test_cli/test_registry_cli.py` at 1647 lines is a candidate for splitting into per-command test files once the source is split (task #2 above).

### 4e. Flakiness & speed

- No flaky tests observed in local runs. Frontend suite runs in ~8s; client suite in ~18s. `make test-slow` gate for LLM regression tests is well-designed — keep out of PR CI.
- `test-server` was not measured here (Postgres not running in the environment); consider a smoke-test subset for pre-commit.

### 4f. Test design improvements

- **Assertions on CSS Module hashes.** `CheckResultsGrid.test.tsx` matches `[class*=checkCard]` and `[class*=checkMessageExpanded]`. Vite hashes CSS module class names in production — these tests could pass in dev and fail in a production-mode build. Add `data-testid` and assert on that.
- **Factory usage.** `server/tests/factories.py` exists — encourage new tests to use it instead of hand-rolling `EvalCase(...)` dicts, which drift with model changes.
- **Assertion-free tests.** None found in this pass.

### 4g. Tooling / CI

- Add `pytest --cov=decision_hub --cov-report=term-missing --cov-fail-under=70` to `test-server` target and CI.
- Add `vitest --coverage` gate to `test-frontend`.
- `check-migrations` and `migrate-check` are excellent — no changes.

### 4h. Phased migration plan

- **Phase 1 (this PR).** Extract `CheckResultsGrid`, delete shim modules, add doc. Zero-risk cleanups.
- **Phase 2 (next 2 weeks).** Extract shared `SkillCard`; split `registry_routes.py` tests by endpoint; add server coverage to CI.
- **Phase 3 (next month).** Split `database.py` into `database/*.py` under a barrel export; keep old import path working for one release.
- **Phase 4 (next 2 months).** Split `client/cli/registry.py` — one command per file.
- **Phase 5 (quarter).** Adopt react-query on the frontend; instrument publish/ask with OTel.

## 5. Detailed Findings by Category

### Architecture & Design

- **God file: `server/infra/database.py` (3465 lines).** Table definitions, query functions, engine setup, connection pool config, and migration table shim all in one module. Every schema change touches this file. Split proposed in change #1.
- **God file: `client/src/dhub/cli/registry.py` (1912 lines).** 10 top-level Typer commands. Every other CLI domain (`auth`, `search`, `runtime`, `init`, `env`, `doctor`, `access`, `org`, `keys`, `config`) is already one-command-per-file. `registry.py` is the outlier. Change #2.
- **Two-tier shim modules in client.** `client/src/dhub/models.py` and `client/src/dhub/core/manifest.py` do nothing but re-export from `dhub_core.*`. Some files import via the shim, others go direct. Two ways to import the same symbol is worse than one. Change #4 (this PR).
- **`api/registry_service.py`** is a service, but lives under `api/`. Naming implies routing. Move to `domain/registry_service.py` or fold into `domain/publish_pipeline.py`.
- **`frontend/src/pages/auditUtils.ts`** — a util named "audit" in the pages directory, used only by `SkillDetailPage.tsx` for `formatCheckName`. Belongs with the component that uses it. Change #5 co-locates it.

### Code Health & Dead Code

- **Duplication: skill card rendering** — 3 near-identical blocks in `HomePage.tsx:270-305`, `SkillsPage.tsx:264-319`, `OrgDetailPage.tsx:147-186`. Slight prop and CSS-class divergence but same information density. Change #3.
- **Orphan test file** — `frontend/src/pages/CheckResultsGrid.test.tsx` names a source file that does not exist at that path (the actual component lives inside `SkillDetailPage.tsx`). Change #5 (this PR) extracts the component so the test filename matches.
- **`registry.py:1786-1912`** — uncovered tail of the CLI monolith; contains fallback/error branches that would surface real user pain if hit. Coverage report attached above.

### Bugs, Correctness & Edge Cases

- **Assertions on CSS-Module class-hash substrings** (`CheckResultsGrid.test.tsx:41`, `59`, `63`, `67`). Vite hashes CSS-Module class names in production builds — these `[class*=checkCard]` regex assertions would still match (`checkCard` remains a substring of the hashed name) but the tests are one config flip away from breaking silently. Prefer `data-testid`.
- **`useApi` double-fires on rapid nav** — `hooks/useApi.ts` guards on `cancelled`, but a fresh mount before the previous unmount can start two in-flight requests and drop the first. Low impact (staleness only), but worth pinning with a test.
- I did NOT deep-audit publish/gauntlet/eval paths for correctness — 1355 + 848 + eval lines is beyond a single-pass review. Recommend a follow-up.

### Security

- **Rate limiters, security headers, request IDs, statement timeout** all present. Well done.
- **Public endpoints have `max_length` caps** per CLAUDE.md — good.
- **Zip-slip guard** lives in `dhub_core/ziputil.py::validate_zip_entries` — ensure every server-side unzip path calls it (spot-checked `publish_pipeline.py` — yes).
- **Not audited in this pass:** LLM prompt injection surface on `/ask` and gauntlet re-scan.

### Performance & Reliability

- **`useApi` refetches on every page mount** — the biggest single perceived-latency win on the frontend (see #6).
- **N+1 not obviously present** in the DB paths I read; every list endpoint uses a single joined `SELECT`.
- **No caching layer** on the search index — every `/ask` hits Gemini. `infra/cache.py` exists but I did not confirm it's wired to the ask path.

### Testing & Observability

- Covered above in §4.
- No metrics, no tracing. Structured logging via loguru is good but "why is this ask slow" requires reading logs by request-ID today.

### Standards, Consistency & DX

- **`.env` files as source of truth for deploy config** — clear and simple. No hidden Modal secrets to rotate.
- **`CLAUDE.md` is unusually good** — it acts as an in-repo playbook for both humans and agents, and its "hard rules" section is a template other repos should copy.
- **Ruff + mypy + pre-commit** all wired. Frontend has ESLint + tsc typecheck. DX is above average.
- **`make help` output uses ANSI escape codes** that render as raw `[36m...[0m` in some terminals; consider stripping color when `TERM=dumb`.

### External libraries

- **FastAPI, Pydantic, SQLAlchemy Core, Typer, loguru** — all current, idiomatic usage where I looked.
- **react-router-dom v7** — routes wired via `<Route element={<Layout />}>` nesting; correct for v7.
- **`react-syntax-highlighter`** — pulled in only for `SkillDetailPage.tsx`; heavy dep for one call site. Consider lazy-loading or switching to `shiki`.
- **`jszip` + `file-saver`** — used only in `FileBrowser.tsx`; verify still needed if a "download raw" path is available server-side.
- **No obviously deprecated API usage** in the code I read.

## 6. Non-Obvious Insights

- **Time bomb: `MIN_CLI_VERSION` gate.** Baked into Modal image at deploy time (per CLAUDE.md). If a bad `.env.prod` is deployed with `MIN_CLI_VERSION` above the highest published CLI, every user is locked out until a rollback. Consider a floor (e.g. never advance more than one minor per release) and an alarm on 4xx spikes at the version-check middleware.
- **Time bomb: manual rate limits per Modal replica.** As the service scales horizontally, effective rate limits scale linearly with replica count. Fine today; if traffic 10×'s, move to Redis-backed sliding window.
- **Strategic refactor for next 6 months.** Split `database.py` first (biggest churn hazard) → then `registry.py` in client (biggest CLI hazard) → then adopt react-query on frontend (biggest UX win). Do NOT try to do all three at once.
- **Documentation health.** `CLAUDE.md`, `README.md`, and `docs/runbook.md` are all live and used. Rare and valuable — protect it.

## 7. Open Questions & Assumptions

- Server test coverage is not reported; I estimated based on file counts and read patterns. Actual coverage may be lower or higher.
- `infra/cache.py` — I did not read this file. If it's wired to `/ask`, my "no caching" comment in §5 is wrong.
- Tracker code path had recent churn (5 files touched) but I did not deep-audit — flagging as a follow-up target.
- `docs/plans/2026-03-05-agent-friendly-cli-design.md` exists and might already plan the `registry.py` split. Confirm before starting change #2.
