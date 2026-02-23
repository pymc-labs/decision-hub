# OSS Release Readiness Checklist (Final Audit)

Audit date: 2026-02-23  
Auditor: agent_c  
Scope: repository-level OSS release readiness (legal, security, governance, supply chain, and operational defaults)

## Status legend

- `PASS` — checked and acceptable for release
- `ISSUE` — gap found; linked to a file in `audit/issues/`
- `UNKNOWN` — needs explicit owner confirmation

---

## 1) Legal and licensing

- [x] **Root OSS license is present and clear** (`LICENSE`) — `PASS`
- [x] **README references project license clearly** (`README.md`) — `PASS`
- [ ] **Public vulnerability disclosure policy exists** (`SECURITY.md`) — `ISSUE`  
  See: `audit/issues/BLOCKER-security-disclosure-policy-missing.md`
- [ ] **Contributor policy exists** (`CONTRIBUTING.md`) — `ISSUE`  
  See: `audit/issues/IMPORTANT-missing-contributor-governance-docs.md`
- [ ] **Community conduct policy exists** (`CODE_OF_CONDUCT.md`) — `ISSUE`  
  See: `audit/issues/IMPORTANT-missing-contributor-governance-docs.md`

## 2) Secrets and sensitive information hygiene

- [x] **No tracked `.env` secrets** (only `.env.example` files tracked) — `PASS`
- [x] **No committed private keys / PEM files** — `PASS`
- [x] **No obvious hardcoded cloud/API secrets in source** (targeted regex scan) — `PASS`
- [ ] **Public examples do not default to private maintainer infrastructure** — `ISSUE`  
  See: `audit/issues/BLOCKER-frontend-env-example-points-to-private-dev-backend.md`

## 3) Public API abuse resistance and security controls

- [x] **Public read-heavy endpoints are rate limited** (`/v1/ask`, listing/download/audit/scan routes) — `PASS`
- [ ] **Public auth endpoints are rate limited** (`/auth/github/code`, `/auth/github/token`) — `ISSUE`  
  See: `audit/issues/CRITICAL-public-auth-endpoints-missing-rate-limits.md`
- [x] **Write routers enforce auth at router level** (`Depends(get_current_user)` in app wiring) — `PASS`
- [x] **JWT validation path exists and returns 401 on invalid tokens** — `PASS`

## 4) Supply chain and dependency risk

- [x] **Python and frontend dependencies are declared and lockfiles exist** (`uv.lock`, `frontend/package-lock.json`) — `PASS`
- [ ] **Automated dependency/vulnerability monitoring is configured** (Dependabot / equivalent) — `ISSUE`  
  See: `audit/issues/CRITICAL-no-automated-dependency-vulnerability-monitoring.md`
- [ ] **Automated SAST/security scanning workflow is configured** (e.g., CodeQL/OSV scans) — `ISSUE`  
  See: `audit/issues/CRITICAL-no-automated-dependency-vulnerability-monitoring.md`

## 5) CI/release pipeline readiness

- [x] **CI workflow exists and covers lint/typecheck/tests/migrations** — `PASS`
- [x] **Dev deploy workflow exists** — `PASS`
- [x] **Release notes/tag workflow exists** — `PASS`
- [x] **Recent `main` CI mostly green** (latest failures appear non-persistent formatting issue later resolved) — `PASS`

## 6) OSS documentation and contributor onboarding

- [x] **Root README exists with install/usage/development basics** — `PASS`
- [ ] **Public contributor onboarding policy exists** (`CONTRIBUTING`) — `ISSUE`  
  See: `audit/issues/IMPORTANT-missing-contributor-governance-docs.md`
- [ ] **Community governance/moderation baseline exists** (`CODE_OF_CONDUCT`) — `ISSUE`  
  See: `audit/issues/IMPORTANT-missing-contributor-governance-docs.md`
- [ ] **Internal runbooks are separated from public contributor docs** — `ISSUE`  
  See: `audit/issues/IMPORTANT-internal-ops-runbook-exposed-in-public-docs.md`

## 7) Operational safety defaults for public users

- [x] **Server defaults to safe `DHUB_ENV=dev` behavior** — `PASS`
- [x] **Env templates use placeholders for secrets** — `PASS`
- [ ] **Example frontend API endpoint is neutral/safe for OSS users** — `ISSUE`  
  See: `audit/issues/BLOCKER-frontend-env-example-points-to-private-dev-backend.md`

## 8) Open-source release communications and support

- [ ] **Documented security contact path for embargoed reports** — `ISSUE`  
  See: `audit/issues/BLOCKER-security-disclosure-policy-missing.md`
- [ ] **Documented issue triage expectations / support scope** — `UNKNOWN` (can be folded into CONTRIBUTING)
- [ ] **Stable public roadmap/release notes policy for external users** — `UNKNOWN`

---

## Findings summary from checklist iteration

### OSS release blockers (must fix before release)

1. `audit/issues/BLOCKER-security-disclosure-policy-missing.md`
2. `audit/issues/BLOCKER-frontend-env-example-points-to-private-dev-backend.md`

### Urgent issues (fix ASAP; can be deferred only with explicit risk acceptance)

1. `audit/issues/CRITICAL-public-auth-endpoints-missing-rate-limits.md`
2. `audit/issues/CRITICAL-no-automated-dependency-vulnerability-monitoring.md`

### Important but deferrable issues

1. `audit/issues/IMPORTANT-missing-contributor-governance-docs.md`
2. `audit/issues/IMPORTANT-internal-ops-runbook-exposed-in-public-docs.md`

