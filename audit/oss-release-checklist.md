# OSS Release Checklist — Decision Hub

**Audit date:** 2026-02-23 (final)
**Release contract:** Hosted product + open code
**Status legend:** `[x]` PASS — `[ ]` ISSUE (linked) — `[?]` UNKNOWN (needs owner confirmation)

---

## Release Contract Decision

> **This is a "hosted product + open code" release.**

The CLI (`dhub`) is the client for the hosted service at `hub.decision.ai`.
The default API URLs pointing to PyMC Labs infrastructure are **intentional** —
they route users to the hosted product. The `DHUB_API_URL` env var exists for
contributors who want to run against a local or custom server.

This means:
- Infrastructure coupling to PyMC Labs is expected, not a bug
- SEO domains, Modal secret names, and company branding are the hosted product's identity
- Self-hosting is possible but not a first-class supported use case
- Blockers are limited to: legal compliance, security governance, and sensitive information exposure

---

## Prioritized Remediation Sequence

### Day 0 — Must fix before repo goes public

| Priority | Issue | Effort | Tracking |
|----------|-------|--------|----------|
| 1 | Create `SECURITY.md` | 15-30 min | [#176](https://github.com/pymc-labs/decision-hub/issues/176) |
| 2 | Add `license = "MIT"` to server + shared pyproject.toml, frontend package.json | 5 min | [#177](https://github.com/pymc-labs/decision-hub/issues/177) |
| 3 | Sanitize AGENTS.md (strip App IDs, secret names, ops details), delete CLAUDE.md, remove PRD.md/tasks.md, decide on git history rewrite | 1-2 hr | [#178](https://github.com/pymc-labs/decision-hub/issues/178) |

**Exit criteria:** All 3 items merged to main. Verified: (1) `SECURITY.md` exists with a private contact channel, (2) `pyproject.toml` and `package.json` license fields present, (3) `AGENTS.md` contains no App IDs, Installation IDs, or Modal secret names; `CLAUDE.md`, `PRD.md`, and `tasks.md` are absent from the repo.

### Open decisions (blocking)

| Question | Tracking |
|----------|----------|
| Copyright holder: individual vs organization? | [#173](https://github.com/pymc-labs/decision-hub/issues/173) |
| "Decision Hub" trademark status? | [#174](https://github.com/pymc-labs/decision-hub/issues/174) |
| Enable GitHub private vulnerability reporting (requires admin) | [#175](https://github.com/pymc-labs/decision-hub/issues/175) |

### Week 1 — Fix ASAP with explicit risk acceptance if deferred (~3 hours)

| Priority | Issue | Effort |
|----------|-------|--------|
| 4 | Add rate limiting to auth endpoints | 1 hr |
| 5 | Create CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue templates | 1-2 hr |
| 6 | Make Modal custom domains configurable (for contributors) | 30 min |

**Exit criteria:** All 3 items merged. Verified: (4) auth endpoints return 429 on excessive requests, (5) CONTRIBUTING.md and CODE_OF_CONDUCT.md exist with contributor-facing content, (6) `modal deploy` works without hardcoded custom domains when `CUSTOM_DOMAINS` env var is unset.

### Post-release — Track as GitHub issues

All IMPORTANT items. Create one GitHub issue per finding on release day.

---

## 1. Secrets & Credentials

- [x] No real API keys in source — all keys are placeholders or loaded from env vars
- [x] No `.env` files tracked — only `.env.example` templates committed
- [x] No private keys or certificates — `.pem`/`.key` files are git-ignored
- [x] No secrets in git history — verified via `git log --diff-filter=A`
- [x] No hardcoded database credentials — connection strings use placeholders
- [x] No AWS credentials — loaded from environment / Modal secrets
- [x] Test files use fake keys — e.g. `sk-ant-test-key`, `ghp_test`
- [ ] Personal Modal URL in frontend `.env.example` → see `IMPORTANT-personal-modal-urls-in-examples.md`
- [ ] Personal Modal URLs in bootstrap skills → see `IMPORTANT-personal-modal-urls-in-examples.md`
- [x] Full git history scan with gitleaks — **clean** (16 findings, all false positives in test fixtures)

## 2. Infrastructure Coupling (hosted product context)

- [x] **CLI default API URLs** point to hosted service — intentional for hosted product model
- [ ] **Modal custom domains** hardcode `hub.decision.ai` — prevents contributor deployments → see `CRITICAL-hardcoded-custom-domains-in-modal.md`
- [ ] **SEO base URLs** hardcode hosted product domains → see `IMPORTANT-seo-hardcoded-domains.md`
- [ ] **Deploy script URLs** hardcode `pymc-labs--api` → see `IMPORTANT-pymc-labs-references-throughout-codebase.md`
- [ ] **Modal secret names** hardcode `decision-hub-*` prefix → see `IMPORTANT-modal-secret-names-hardcoded.md`

## 3. Branding

- [x] Maintainer branding in README, footer, legal pages — intentional for hosted product
- [x] Company-specific examples in frontend — intentional branding for hosted product
- [x] Test fixtures using `pymc-labs` — acceptable (just data)
- [x] `pymc-labs` in `featuredOrgs.ts` — intentional for hosted product
- [x] Repository URLs in pyproject.toml — correct (points to actual repo)

## 4. License & Legal

- [x] LICENSE file exists — MIT License at root
- [x] `client/pyproject.toml` has `license = "MIT"` — consistent
- [x] No GPL/copyleft dependency conflicts — all deps MIT/Apache/BSD compatible
- [x] `jszip` dual license (MIT OR GPL-3.0) — MIT option available
- [ ] **Missing license in `server/pyproject.toml`** → [#177](https://github.com/pymc-labs/decision-hub/issues/177)
- [ ] **Missing license in `shared/pyproject.toml`** → [#177](https://github.com/pymc-labs/decision-hub/issues/177)
- [ ] **Missing license in `frontend/package.json`** → [#177](https://github.com/pymc-labs/decision-hub/issues/177)
- [ ] Personal email inconsistency (Gmail vs PyMC Labs) → see `IMPORTANT-personal-email-in-metadata.md`
- [?] Copyright holder correctness (individual vs organization) → [#173](https://github.com/pymc-labs/decision-hub/issues/173)
- [?] "Decision Hub" trademark status → [#174](https://github.com/pymc-labs/decision-hub/issues/174)

## 5. Security

- [x] Parameterized SQL queries — SQLAlchemy Core with bind parameters throughout
- [x] JWT authentication — write endpoints protected, proper validation
- [x] Input validation — max_length constraints, Pydantic models, custom validators
- [x] Error messages sanitized — no credential leakage in errors
- [x] Subprocess credentials sanitized — tokens stripped from error messages
- [x] API keys encrypted at rest — Fernet encryption for stored keys
- [x] Rate limiting on public read endpoints — search, list, resolve, download, audit, scan
- [ ] **Auth endpoints missing rate limits** — `/auth/github/code` and `/auth/github/token` unthrottled → see `CRITICAL-auth-endpoints-missing-rate-limits.md` (Week 1)
- [ ] No explicit CORS middleware → see `IMPORTANT-missing-cors-configuration.md`
- [ ] Missing HTTP security headers → see `IMPORTANT-missing-security-headers.md`
- [ ] `print()` in production code (`modal_app.py:387`) → see `IMPORTANT-print-statement-in-production.md`

## 6. Security Governance

- [ ] **No SECURITY.md** — missing vulnerability disclosure policy → [#176](https://github.com/pymc-labs/decision-hub/issues/176)
- [ ] No automated dependency vulnerability monitoring → see `IMPORTANT-dependency-audit-needed.md`
- [?] GitHub private vulnerability reporting not verified → [#175](https://github.com/pymc-labs/decision-hub/issues/175) (requires admin)

## 7. Documentation & Community

- [x] README.md is public-quality — good overview, install instructions, usage examples
- [ ] **AGENTS.md contains sensitive info** — must be sanitized (keep dev guidelines, strip ops details); delete CLAUDE.md → [#178](https://github.com/pymc-labs/decision-hub/issues/178)
- [ ] **Internal planning docs committed** — PRD.md, tasks.md → [#178](https://github.com/pymc-labs/decision-hub/issues/178)
- [ ] No CONTRIBUTING.md → see `CRITICAL-missing-oss-community-docs.md` (Week 1)
- [ ] No CODE_OF_CONDUCT.md → see `CRITICAL-missing-oss-community-docs.md` (Week 1)
- [ ] No issue templates → see `CRITICAL-missing-oss-community-docs.md` (Week 1)
- [ ] `.claude/` directory contains internal test commands → see `IMPORTANT-claude-directory-test-commands.md`

## 8. GitHub Configuration

- [ ] CODEOWNERS uses personal username `@lfiaschi` → see `IMPORTANT-codeowners-personal-username.md`
- [x] PR template exists
- [x] CI workflows use secret references (`${{ secrets.* }}`)
- [x] Deploy script is env-aware (respects DHUB_ENV)

## 9. Git History

- [x] No secrets ever committed — clean history verified
- [x] No `.env` files in history — only `.env.example` tracked
- [x] No private keys in history
- [x] Commit messages are clean — no internal details leaked

---

## Findings Summary

### BLOCKERS (3) — Day 0 fixes before release

1. [#176](https://github.com/pymc-labs/decision-hub/issues/176) — No SECURITY.md (~15 min fix)
2. [#177](https://github.com/pymc-labs/decision-hub/issues/177) — server, shared, frontend lack license metadata (~5 min fix)
3. [#178](https://github.com/pymc-labs/decision-hub/issues/178) — Sanitize AGENTS.md, delete CLAUDE.md, remove PRD.md/tasks.md, decide on history rewrite (~1-2 hr)

### Open decisions (blocking)

1. [#173](https://github.com/pymc-labs/decision-hub/issues/173) — Copyright holder: individual vs organization?
2. [#174](https://github.com/pymc-labs/decision-hub/issues/174) — "Decision Hub" trademark status?
3. [#175](https://github.com/pymc-labs/decision-hub/issues/175) — Enable GitHub private vulnerability reporting (requires admin)

### Resolved

- [x] Full git history scan with gitleaks — **clean** (16 findings, all false positives in test fixtures)

### CRITICAL (3) — Week 1 fixes, deferrable with explicit risk acceptance

1. `CRITICAL-auth-endpoints-missing-rate-limits.md` — Auth endpoints unthrottled (~1 hr fix)
2. `CRITICAL-missing-oss-community-docs.md` — No CONTRIBUTING, CODE_OF_CONDUCT, issue templates (~1-2 hr)
3. `CRITICAL-hardcoded-custom-domains-in-modal.md` — Modal deploy fails for contributors (~30 min fix)

### IMPORTANT (12) — Post-release, track as GitHub issues

1. `IMPORTANT-missing-cors-configuration.md`
2. `IMPORTANT-print-statement-in-production.md`
3. `IMPORTANT-missing-security-headers.md`
4. `IMPORTANT-dependency-audit-needed.md`
5. `IMPORTANT-personal-modal-urls-in-examples.md`
6. `IMPORTANT-claude-directory-test-commands.md`
7. `IMPORTANT-codeowners-personal-username.md`
8. `IMPORTANT-personal-email-in-metadata.md`
9. `IMPORTANT-hardcoded-api-urls-in-client.md` — CLI defaults to hosted service (intentional; `DHUB_API_URL` override exists)
10. `IMPORTANT-seo-hardcoded-domains.md` — Hosted product's canonical domains
11. `IMPORTANT-modal-secret-names-hardcoded.md` — Hosted product's infrastructure naming
12. `IMPORTANT-pymc-labs-references-throughout-codebase.md` — Intentional branding for hosted product
