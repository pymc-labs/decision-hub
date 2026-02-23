# OSS Release Checklist — Decision Hub

**Audit date:** 2026-02-23 (revised)
**Status legend:** `[x]` PASS — `[ ]` ISSUE (linked) — `[?]` UNKNOWN (needs owner confirmation)

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
- [?] Full git packfile scan with `trufflehog`/`gitleaks` not yet performed

## 2. Infrastructure Lock-in (Deployment Blockers)

- [ ] **CLI default API URLs** hardcode `pymc-labs--api.modal.run` → see `BLOCKER-hardcoded-api-urls-in-client.md`
- [ ] **Modal custom domains** hardcode `hub.decision.ai` → see `BLOCKER-hardcoded-custom-domains-in-modal.md`
- [ ] **SEO base URLs** hardcode `hub.decision.ai` / `decisionhub.dev` → see `CRITICAL-seo-hardcoded-domains.md`
- [ ] **Deploy script URLs** hardcode `pymc-labs--api` → see `CRITICAL-pymc-labs-references-throughout-codebase.md`
- [ ] **Modal secret names** hardcode `decision-hub-*` prefix → see `CRITICAL-modal-secret-names-hardcoded.md`

## 3. Branding vs. Lock-in Distinction

- [x] Maintainer branding in README, footer, legal pages — acceptable for OSS
- [ ] Company-specific examples in frontend (HowItWorks, AnimatedTerminal) → see `CRITICAL-pymc-labs-references-throughout-codebase.md`
- [x] Test fixtures using `pymc-labs` — acceptable (just data)
- [ ] `pymc-labs` in `featuredOrgs.ts` — cosmetic, fix post-release
- [x] Repository URLs in pyproject.toml — correct (points to actual repo)

## 4. License & Legal

- [x] LICENSE file exists — MIT License at root
- [x] No GPL/copyleft dependency conflicts — all deps MIT/Apache/BSD compatible
- [x] `jszip` dual license (MIT OR GPL-3.0) — MIT option available
- [ ] **Missing license in `server/pyproject.toml`** → see `BLOCKER-missing-license-declarations.md`
- [ ] **Missing license in `shared/pyproject.toml`** → see `BLOCKER-missing-license-declarations.md`
- [ ] **Missing license in `frontend/package.json`** → see `BLOCKER-missing-license-declarations.md`
- [ ] Personal email inconsistency (Gmail vs PyMC Labs) → see `IMPORTANT-personal-email-in-metadata.md`
- [?] Copyright holder correctness (individual vs organization)
- [?] "Decision Hub" trademark status

## 5. Security

- [x] Parameterized SQL queries — SQLAlchemy Core with bind parameters throughout
- [x] JWT authentication — write endpoints protected, proper validation
- [x] Input validation — max_length constraints, Pydantic models, custom validators
- [x] Error messages sanitized — no credential leakage in errors
- [x] Subprocess credentials sanitized — tokens stripped from error messages
- [x] API keys encrypted at rest — Fernet encryption for stored keys
- [x] Rate limiting on public read endpoints — search, list, resolve, download, audit, scan
- [ ] **Auth endpoints missing rate limits** — `/auth/github/code` and `/auth/github/token` unthrottled → see `CRITICAL-auth-endpoints-missing-rate-limits.md`
- [ ] No explicit CORS middleware → see `IMPORTANT-missing-cors-configuration.md`
- [ ] Missing HTTP security headers → see `IMPORTANT-missing-security-headers.md`
- [ ] `print()` in production code (`modal_app.py:387`) → see `IMPORTANT-print-statement-in-production.md`

## 6. Security Governance

- [ ] **No SECURITY.md** — missing vulnerability disclosure policy → see `BLOCKER-security-disclosure-policy-missing.md`
- [ ] No automated dependency vulnerability monitoring → see `IMPORTANT-dependency-audit-needed.md`
- [?] GitHub private vulnerability reporting not verified

## 7. Documentation & Community

- [x] README.md is public-quality — good overview, install instructions, usage examples
- [ ] **CLAUDE.md contains sensitive info** — GitHub App IDs, Modal secret names, internal ops → see `BLOCKER-sensitive-info-in-claude-agents-md.md`
- [ ] **Internal planning docs committed** — PRD.md, tasks.md → see `BLOCKER-internal-docs-committed.md`
- [ ] No CONTRIBUTING.md → see `CRITICAL-missing-oss-community-docs.md`
- [ ] No CODE_OF_CONDUCT.md → see `CRITICAL-missing-oss-community-docs.md`
- [ ] No issue templates → see `CRITICAL-missing-oss-community-docs.md`
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

### BLOCKERS (6) — Must fix before release

1. `BLOCKER-security-disclosure-policy-missing.md` — No SECURITY.md
2. `BLOCKER-hardcoded-api-urls-in-client.md` — CLI defaults to PyMC Labs servers
3. `BLOCKER-hardcoded-custom-domains-in-modal.md` — Modal deploy fails for anyone else
4. `BLOCKER-sensitive-info-in-claude-agents-md.md` — Ops runbook exposed
5. `BLOCKER-missing-license-declarations.md` — 3 sub-packages lack license metadata
6. `BLOCKER-internal-docs-committed.md` — PRD.md, tasks.md expose strategy

### CRITICAL (5) — Fix ASAP, deferrable with explicit risk acceptance

1. `CRITICAL-auth-endpoints-missing-rate-limits.md` — Auth endpoints unthrottled
2. `CRITICAL-pymc-labs-references-throughout-codebase.md` — Infra lock-in + cosmetic coupling
3. `CRITICAL-missing-oss-community-docs.md` — No CONTRIBUTING, CODE_OF_CONDUCT, issue templates
4. `CRITICAL-seo-hardcoded-domains.md` — Canonical URLs hardcoded
5. `CRITICAL-modal-secret-names-hardcoded.md` — Secret name prefix hardcoded

### IMPORTANT (8) — Clearly deferrable post-release

1. `IMPORTANT-missing-cors-configuration.md`
2. `IMPORTANT-print-statement-in-production.md`
3. `IMPORTANT-missing-security-headers.md`
4. `IMPORTANT-dependency-audit-needed.md`
5. `IMPORTANT-personal-modal-urls-in-examples.md`
6. `IMPORTANT-claude-directory-test-commands.md`
7. `IMPORTANT-codeowners-personal-username.md`
8. `IMPORTANT-personal-email-in-metadata.md`
