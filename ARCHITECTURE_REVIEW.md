# Decision Hub — Comprehensive Codebase Review

*Generated: 2026-03-01*

## 1. High-Level Summary

**System purpose:** Decision Hub is a registry for publishing, discovering, and installing AI agent Skills — modular packages of prompts and code that 38+ AI coding agents can consume. It provides CLI-based publishing, a security gauntlet (LLM-powered safety analysis), automated evals in sandboxes, hybrid search (pgvector + FTS + Gemini), and auto-tracking of GitHub repos.

**Technology stack:** Python 3.11 (FastAPI, Typer+Rich, SQLAlchemy Core, Pydantic), React 19 + TypeScript + Vite, PostgreSQL (Supabase/PgBouncer), S3, Modal (serverless compute + sandboxed evals), Gemini (search + classification + gauntlet), Anthropic (eval judging).

**Overall architectural health:** Good for a single-team project. The layered architecture (`api/` → `domain/` → `infra/`) is sound but has leaks — domain logic in the API layer, a 2,939-line database monolith, and a duplicated publish pipeline between the HTTP endpoint and tracker cron. Frozen dataclass models and SQLAlchemy Core are well-chosen. The callback-based gauntlet design is clean.

**Main strengths:**
- Thorough security posture: parameterized SQL, zip-slip protection, credential sanitization, mandatory LLM gauntlet, Fernet-encrypted API keys
- Well-structured domain models (frozen dataclasses, clear status vocabularies)
- Strong CLI test coverage (~22 test files, all commands tested)
- Comprehensive CLAUDE.md with battle-tested conventions
- CI pipeline with migration replay, schema drift detection, and 8 quality gates

**Main risks:**
- `database.py` (2,939 lines) is a maintenance bottleneck and merge-conflict magnet
- Publish pipeline logic duplicated between HTTP endpoint and tracker service
- Domain layer imports from API layer (inverted dependency)
- JWT tokens valid for 1 year with no revocation mechanism; stale org membership
- No test coverage measurement, no frontend E2E tests
- No application-level caching, metrics, or health check endpoint

**Strategic outlook:** The system will hit scaling friction in three areas: (1) the database monolith prevents multi-team ownership, (2) the per-container in-memory rate limiting is ineffective under horizontal scaling, and (3) the lack of caching means every page load hits the DB fresh.

---

## 2. System Map

- **`shared/` (dhub-core)**: Single source of truth for `SkillManifest`, `RuntimeConfig`, validation, SKILL.md parsing, taxonomy. 6 Python files.
- **`client/` (dhub-cli)**: Typer+Rich CLI — auth, publish, install, search, eval management, agent symlink management. 16 source files, published to PyPI.
- **`server/` (decision-hub-server)**: FastAPI backend deployed on Modal
  - `api/`: Route handlers, DI deps, rate limiting, response models. 12 files.
  - `domain/`: Business logic — publish validation, gauntlet safety analysis, eval pipeline, search index, tracker service, auth/crypto. 12 files.
  - `infra/`: Database (SQLAlchemy Core), S3 storage, Gemini/Anthropic LLM clients, GitHub App tokens, Modal sandbox client, embeddings. 9 files.
  - `scripts/`: Crawlers, backfills, health checks. 13 files across 3 directories.
- **`frontend/`**: React 19 SPA — skill browser, org pages, ask modal, detail pages. CSS Modules, React Router 7. 30+ source files.

**Data flow:** CLI/Frontend → FastAPI `/v1/` endpoints → PostgreSQL (via NullPool/PgBouncer) → S3 for zip artifacts. Publish: upload zip → extract → gauntlet scan (Gemini LLM) → grade → S3 store → DB insert → classify category → generate embedding → optionally trigger eval (Modal sandbox + Anthropic judge). Trackers: Modal cron → GitHub API poll → republish on new commits.

---

## 3. Top 15 High-Leverage Changes

### 1. Split `database.py` into domain-scoped repository modules
- **Category:** architecture
- **Impact:** high | **Effort:** M
- **Next steps:** Create `infra/database/` package with `core.py` (tables, engine), `skills.py`, `versions.py`, `trackers.py`, `evals.py`, `audit.py`, `orgs.py`, `users.py`, `search.py`. Re-export from `__init__.py` for backward compat. Migrate imports one router at a time.

### 2. Unify the publish pipeline into a single domain function
- **Category:** architecture
- **Impact:** high | **Effort:** M
- **Next steps:** Extract `domain/publish_pipeline.py` with `execute_publish()`. Both `registry_routes.py:publish_skill` and `tracker_service._publish_skill_from_tracker` call it. Differences (visibility, version bumping, source URL) become parameters.

### 3. Fix domain→API layer violation
- **Category:** architecture
- **Impact:** high | **Effort:** S
- **Next steps:** Move pure business functions from `api/registry_service.py` to `domain/publish_pipeline.py`. Keep only HTTP wrappers (that raise HTTPException) in the API layer. Introduce domain exceptions (`ManifestParseError`, `AuthorizationError`) translated at the API boundary.

### 4. Reduce JWT lifetime and add org membership re-validation
- **Category:** security
- **Impact:** high | **Effort:** M
- **Next steps:** Reduce JWT expiry from 8,760 hours (1 year) to 24-72 hours. Implement refresh token flow or periodic org membership sync. Remove stale `org_members` rows when GitHub membership changes.

### 5. Add test coverage measurement and CI gates
- **Category:** testing
- **Impact:** high | **Effort:** S
- **Next steps:** Add `pytest-cov` to dev dependencies. Configure `--cov-fail-under=50` (raise iteratively). Add vitest coverage. Add coverage reporting to CI.

### 6. Add security headers and rate limiting to publish/auth endpoints
- **Category:** security
- **Impact:** medium | **Effort:** S
- **Next steps:** Add `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Strict-Transport-Security`. Add rate limiters to `POST /v1/publish` (10/min), auth endpoints (10/min/IP).

### 7. Escape ILIKE wildcards in user-facing search
- **Category:** bugs
- **Impact:** medium | **Effort:** S
- **Next steps:** Apply the existing `_escape_like()` helper (database.py:2850) in `_build_skills_filters` (line 1689) and `fetch_org_stats` (line 2060). Already tested in `mark_skills_source_removed`.

### 8. Add database integration tests against real Postgres
- **Category:** testing
- **Impact:** high | **Effort:** M
- **Next steps:** Create `test_database_queries.py` targeting CI Postgres. Test `fetch_all_skills_for_index`, `search_skills_hybrid`, `resolve_version`, `_apply_visibility_filter`, `_refresh_skill_latest_version`.

### 9. Consolidate semver/slug utilities into `dhub_core.validation`
- **Category:** code-health
- **Impact:** medium | **Effort:** S
- **Next steps:** Move `parse_semver_parts` and `bump_version` from database.py, repo_utils.py, and app.py into `shared/src/dhub_core/validation.py`. Unify the `_SLUG_PATTERN` regex (duplicated in 3 files).

### 10. Add application-level caching for hot read paths
- **Category:** performance
- **Impact:** medium | **Effort:** M
- **Next steps:** Add `Cache-Control` headers to taxonomy, org profiles, skill list endpoints (30-60s). Consider in-memory LRU for frequently-read, slowly-changing data. The stats endpoint already uses 60s caching — extend the pattern.

### 11. Add health check endpoint and structured logging
- **Category:** performance
- **Impact:** medium | **Effort:** S
- **Next steps:** Add `GET /health` that verifies DB connectivity. Add JSON logging mode when `LOG_FORMAT=json`. Enhance request logging with user_id, org/skill context, response size.

### 12. Remove dead code: 4 unused DB functions, legacy test models, feature flag
- **Category:** code-health
- **Impact:** medium | **Effort:** S
- **Next steps:** Delete `list_skill_access_grants`, `find_eval_report_by_version`, `find_latest_eval_run_for_version`, `update_eval_run_heartbeat` from database.py. Remove `TestCase` model and `parse_test_cases`/`evaluate_assertion`/`evaluate_test_results` from gauntlet.py. Remove `SHOW_GITHUB_BUTTONS` feature flag (permanently `true`).

### 13. Fix S3 upload before DB commit creating orphaned objects
- **Category:** bugs
- **Impact:** medium | **Effort:** S
- **Next steps:** In `registry_routes.py:publish_skill`, catch exceptions after S3 upload and clean up the uploaded object in the error path. Or reorder to upload after commit.

### 14. Add frontend component tests for critical pages
- **Category:** testing
- **Impact:** medium | **Effort:** M
- **Next steps:** Add tests for `SkillDetailPage`, `AskModal`, `HomePage`. The existing MSW + testing-library setup makes this straightforward.

### 15. Stream S3 downloads instead of loading into memory
- **Category:** performance
- **Impact:** medium | **Effort:** S
- **Next steps:** In `download_skill` endpoint (registry_routes.py:767), use `StreamingResponse` with S3's streaming API instead of loading the entire zip (up to 50 MB) into memory. This prevents OOM under concurrent downloads on the 512 MB Modal container.

---

## 4. Test Suite Recommendations

### 4a. Test Inventory

| Category | Component | Files | Coverage Quality | Speed |
|----------|-----------|-------|-----------------|-------|
| Unit | shared (parsing, validation) | 3 | Excellent | Fast |
| Unit | client core (install, manifest, runtime) | 7 | Very good | Fast |
| Unit | client CLI (all commands) | 10 | Very good | Fast |
| Unit | server domain (gauntlet, tracker, auth, crypto) | 15 | Good | Fast |
| Integration | server API routes | 14 | Good (mocked DB) | Fast |
| Unit | server infra (LLM clients, GitHub, embeddings) | 11 | Good | Fast |
| Component | frontend | 4 | Weak — only 4 of 15+ pages | Fast |
| E2E | none | 0 | Missing | N/A |

### 4b. Target Testing Strategy

Recommended pyramid: **70% unit / 25% integration / 5% E2E**. The system is heavy on business logic (gauntlet checks, publish orchestration, search ranking) which suits deep unit testing. Integration tests should target DB queries against real Postgres in CI. E2E should cover the 3 critical user flows (browse, search, install command copy).

### 4c. Top 10 Tests to Add

1. **DB integration: `_apply_visibility_filter`** — Unit, test public/org/private visibility with different user contexts. `server/tests/test_infra/test_database_queries.py`
2. **DB integration: `search_skills_hybrid`** — Integration, test FTS + vector combo with real Postgres. Same file.
3. **Registry service: full publish pipeline** — Integration, valid zip → gauntlet → S3 → DB → eval trigger. `server/tests/test_domain/test_registry_service.py`
4. **Concurrent publish race condition** — Integration, two simultaneous publishes of same version → one 409. `server/tests/test_api/test_registry_routes.py`
5. **Frontend: SkillDetailPage** — Component, metadata rendering + version history + install command. `frontend/src/pages/SkillDetailPage.test.tsx`
6. **Frontend: AskModal multi-turn** — Component, conversation flow + skill references. `frontend/src/components/AskModal.test.tsx`
7. **Auth flow: stale org membership** — Unit, JWT with old orgs → verify membership check catches it. `server/tests/test_domain/test_auth.py`
8. **Tracker: partial publish failure** — Unit, 3/5 skills succeed, 2 fail → verify SHA handling and error recording. `server/tests/test_domain/test_tracker_service.py`
9. **BadZipFile handling** — Unit, non-zip upload → 422 not 500. `server/tests/test_api/test_registry_routes.py`
10. **Eval report unique constraint on re-run** — Unit, eval completes twice for same version → verify INSERT ON CONFLICT. `server/tests/test_domain/test_evals.py`

### 4d. Tests to Remove or Reclassify

- **Duplicated validation tests**: `validate_semver` and `validate_skill_name` are tested identically in shared, client, AND server. Keep the comprehensive parametrized suite in `shared/tests/test_validation.py`; reduce client/server copies to thin import-path verification.
- **Brittle docx integration tests**: `test_docx_integration.py` asserts exact file counts (`len(zf.namelist()) == 59`) and exact description lengths. Use range/structural assertions.

### 4e. Flakiness and Speed Fixes

- Replace `time.sleep(1)` in `test_auth.py:test_decode_jwt_expired_token` with `freezegun` or `time-machine`
- Replace `time.sleep(1.1)` in `test_rate_limit.py:test_window_expiry_resets_limit` with time mocking
- **Target runtime**: Unit suite < 10s, integration suite < 30s, frontend suite < 10s

### 4f. Test Design Improvements

- Add a DB fixture factory for tests that need users+orgs+skills+versions, reducing 40+ lines of setup per test
- Create a `make_skill_zip(manifest_content, files)` test helper for publish tests
- Consider property-based testing (`hypothesis`) for SKILL.md parser — generate random valid/invalid frontmatter

### 4g. Tooling and CI Recommendations

- Add `pytest-cov` to all packages; configure `--cov-fail-under=50` (raise to 70 over 2 quarters)
- Add vitest coverage reporting: `npx vitest run --coverage`
- Add explicit `test-shared` CI job (currently untested in CI)
- Add `pytest-xdist` for parallel execution
- Add Playwright E2E smoke test job (browse → detail → install command copy)

### 4h. Phased Migration Plan

**Phase 1 (1-2 weeks):** Add coverage tooling, fix flaky time.sleep tests, add test-shared CI job, remove duplicate validation tests

**Phase 2 (2-3 weeks):** Add DB integration tests against CI Postgres, add publish pipeline tests, add auth flow tests

**Phase 3 (2-3 weeks):** Add frontend component tests (SkillDetailPage, AskModal, HomePage), add error-path API tests

**Phase 4 (1-2 weeks):** Add health check, structured JSON logging, Playwright E2E smoke test

**Phase 5 (ongoing):** Raise coverage threshold 5% per quarter, add property-based testing, add mutation testing for gauntlet

---

## 5. Detailed Findings by Category

### Architecture and Design

- **`database.py` God-module** (2,939 lines): Contains ALL tables, mappers, and queries for every domain entity. Every route file imports 10-28 functions from it. Split into domain-scoped repo modules.
- **Domain→API layer violation**: `tracker_service.py` (domain) imports from `api/registry_service.py`. The publish orchestration logic lives in the wrong layer.
- **Duplicated publish pipeline**: HTTP endpoint (`registry_routes.py:360-563`) and tracker (`tracker_service.py:610-790`) independently orchestrate the same 10-step publish flow.
- **`registry_service.py` identity crisis**: Mixes HTTP error adapters, pure domain logic, and background orchestration in one 748-line file.
- **5 copy-pasted `_build_*_fn` Gemini callback factories** in `registry_service.py:247-368`. A single higher-order factory could replace all five.
- **Response models defined inline** in `registry_routes.py:157-345` — 15 Pydantic models not reusable by other services.

### Code Health and Dead Code

- **4 dead DB functions**: `list_skill_access_grants`, `find_eval_report_by_version`, `find_latest_eval_run_for_version`, `update_eval_run_heartbeat`
- **Legacy `TestCase` model** and 3 related gauntlet functions: leftover from pre-eval-pipeline testing flow
- **3 duplicated semver parsers** across database.py, repo_utils.py, and app.py
- **3 duplicated slug regex patterns** across validation.py, orgs.py, and crawler/processing.py
- **Dead frontend code**: `resolveSkill()` function and `OrgSummary` interface never used
- **`SHOW_GITHUB_BUTTONS`** feature flag permanently `true`
- **Two crawler packages**: `scripts/crawler/` is the real one; `scripts/github_crawler/` is a 5-line alias

### Bugs, Correctness, and Edge Cases

- **ILIKE wildcard injection** (database.py:1689): User search input not escaped for `%`/`_` wildcards. Existing `_escape_like` helper not applied.
- **Race condition in concurrent publishes**: Both pass `find_version` check, both upload to S3, one hits IntegrityError — S3 orphan with potentially wrong zip content.
- **S3 upload before DB commit**: Failed DB insert leaves orphaned S3 objects (registry_routes.py:496-531).
- **Partial tracker publish failures silently swallowed**: When some skills in a multi-skill repo fail, SHA advances and `last_error` is cleared.
- **Eval report unique constraint**: `insert_eval_report` can fail on `version_id` unique constraint during error handling, causing the error handler itself to fail.
- **Zombie eval runs**: Only detected when a user actively polls status. No background sweep.
- **`BadZipFile` not caught**: Non-zip upload causes unhandled 500 instead of 422.
- **Missing `s3_endpoint_url`** in `modal_app.py:run_eval_task` S3 client creation — breaks local dev evals.

### Security

- **JWT lifetime 1 year** with no revocation. Stale org membership baked into claims indefinitely.
- **No security headers**: No CORS middleware, no `X-Frame-Options`, no CSP, no HSTS.
- **No rate limiting** on publish, auth, and key management endpoints.
- **Gemini API key in URL query params** (gemini.py:77) — visible in logs, error traces.
- **Sandbox network egress unrestricted**: User API keys injected into eval sandboxes; malicious skills could exfiltrate.
- **Audit logs expose LLM reasoning publicly**: Could help attackers understand gauntlet evasion strategies.
- **Gauntlet bypass via non-scannable extensions**: `.rb`, `.rs`, `.go`, `.java`, `.c`, `.php` not scanned.
- **Positive findings**: SQL injection fully mitigated, zip-slip protected, Fernet encryption for API keys, `diagnose=False` in loguru, visibility filtering consistently applied.

### Performance and Reliability

- **No caching** on hot read paths (list skills, taxonomy, org profiles). Only `/v1/stats` has `Cache-Control`.
- **5-6 sequential DB queries** in `get_skill_summary` — `list_granted_skill_ids` called redundantly.
- **Correlated EXISTS subquery** for tracker detection on every skill row — no index on `skill_trackers.repo_url`.
- **Download endpoint loads entire zip into memory** (up to 50 MB) — risk of OOM under concurrency with 512 MB container.
- **N+1 UPDATEs** in `batch_update_github_stars` and `batch_update_github_repo_metadata`.
- **3 LLM calls per ask request** — steps 1+2 correctly parallelized, step 3 sequential.
- **Eval pipeline no overall timeout** — N cases x 900s per case can exceed 30-minute Modal timeout.
- **Rate limiter per-container, not shared** — documented design choice, effective limit multiplied by container count.

### Observability

- **No structured (JSON) logging** — human-readable format only, poor for log aggregation.
- **No application-level metrics** — no Prometheus, StatsD, or equivalent.
- **No health check endpoint** — no `/health` or `/healthz` for load balancers.
- **Good request ID correlation** via `RequestLoggingMiddleware`.
- **Tracker metrics table** exists for cron observability — good pattern, should extend to other domains.

### Standards, Consistency, and Developer Experience

- **Inconsistent DB query naming**: 5 verb prefixes (`find_`, `fetch_`, `get_`, `list_`, `resolve_`) with no clear semantic distinction.
- **mypy configured too loosely**: `disallow_untyped_defs = false`, blanket `ignore_missing_imports`.
- **No `CONTRIBUTING.md`**: CLAUDE.md is AI-optimized, not human-readable for onboarding.
- **Stale "Sprint N" comments** in settings.py and .env.example.
- **3 hardcoded `rem` font sizes** in `GradeBadge.module.css` violating the design system.
- **Missing return type** on `get_s3_client` in deps.py.
- **Missing `uv.lock`** from repository — reproducibility risk for Modal deployments.

---

## 6. Non-Obvious Insights

1. **The 8-step sync checklist for new skill fields is an architectural time bomb.** CLAUDE.md documents that adding a skill field requires updating 8 locations across 4 packages. This will cause bugs every time someone forgets a step. Consider auto-generating response models or using a single column-to-API mapping.

2. **The gauntlet's security scanning is static-only.** Skills execute arbitrary code in eval sandboxes with user-provided API keys and unrestricted network. A sophisticated attacker could craft a skill that passes static analysis but exfiltrates credentials at runtime. Network egress restrictions in the sandbox would mitigate this.

3. **NullPool + PgBouncer is correct but creates a cold-start penalty.** Every request pays TCP+TLS to PgBouncer. Under burst traffic after a Modal scale-up, many containers simultaneously opening connections could pressure PgBouncer's connection limit. Monitor `max_client_conn` on PgBouncer.

4. **The denormalized `latest_*` columns on the skills table are a good optimization but lack a consistency guarantee.** `_refresh_skill_latest_version` is called during `insert_version` and `delete_version`, but if either call fails after the version write succeeds, the denormalized data becomes stale with no repair mechanism.

5. **Strategic refactoring sequence for next 3-6 months:** (1) Split database.py → immediate merge-conflict relief. (2) Unify publish pipeline → required before any publish-flow feature work. (3) JWT/auth hardening → prerequisite for any enterprise/team features. (4) Coverage gates → compound returns on every future PR. (5) Caching layer → required before any significant traffic growth.

---

## 7. Open Questions and Assumptions

1. **What is the current traffic volume?** Caching and performance recommendations assume growth beyond current levels. If traffic is low, caching may be premature.

2. **Is PgBouncer configured for transaction mode?** The NullPool + `statement_cache_size=0` settings assume this, but it's not verified.

3. **Are there plans for multi-tenancy beyond GitHub org scoping?** The current auth model (GitHub-only, org-based permissions) would need significant rework for enterprise SSO or RBAC.

4. **What is the actual eval sandbox network policy?** Modal's default network isolation may already restrict egress, but this is undocumented in the codebase.

5. **Is `uv.lock` intentionally excluded from the repo?** If reproducible builds on Modal are desired, the lockfile should be committed.

6. **What happened to the `archive/` directory?** It contains subdirectories but was not explored — may contain deprecated code that should be cleaned up or documented.

7. **Why are there both `python-jose` and `PyJWT` in server dependencies?** Both are JWT libraries. The codebase uses `python-jose` for JWT operations. `PyJWT` may be a transitive dependency or a migration artifact.
