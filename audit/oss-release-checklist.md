# OSS Release Readiness Checklist (Round 02 Revision)

Audit date: 2026-02-23  
Auditor: agent_c  
Scope: repository-level OSS readiness for legal clarity, deployability/forkability, security hardening, and operational support.

## Status legend

- `PASS` — checked and acceptable for release
- `ISSUE` — concrete gap found (linked issue file)
- `UNKNOWN` — requires explicit owner/legal decision

---

## 1) Legal and package licensing

- [x] Root license file exists and is clear (`LICENSE`) — `PASS`
- [x] README references license — `PASS`
- [ ] Package manifests consistently declare license metadata — `ISSUE`  
  See: `audit/issues/BLOCKER-missing-license-metadata-in-shared-and-server-packages.md`
- [ ] Security disclosure policy exists (`SECURITY.md`) — `ISSUE`  
  See: `audit/issues/BLOCKER-security-disclosure-policy-missing.md`

## 2) Deployability and forkability (must work outside maintainer org)

- [ ] Deployment does not depend on maintainer-owned custom domains — `ISSUE`  
  See: `audit/issues/BLOCKER-hardcoded-modal-custom-domains-break-third-party-deploys.md`
- [ ] CLI defaults are neutral (not hardwired to maintainer infra) — `ISSUE`  
  See: `audit/issues/BLOCKER-hardcoded-cli-default-api-urls-lock-to-maintainer-infra.md`
- [x] Core runtime configuration exists via env/settings — `PASS`

## 3) Public-domain/URL coupling hygiene

- [ ] Canonical/SEO/user-facing links are configuration-driven — `ISSUE`  
  See: `audit/issues/CRITICAL-hardcoded-public-domains-in-seo-and-ux.md`
- [ ] Example env templates are neutral and non-maintainer-specific — `ISSUE`  
  See: `audit/issues/IMPORTANT-frontend-env-example-points-to-private-dev-backend.md`

## 4) Public endpoint abuse resistance and security controls

- [x] Read-heavy public endpoints are rate-limited — `PASS`
- [ ] Public auth endpoints are rate-limited — `ISSUE`  
  See: `audit/issues/CRITICAL-public-auth-endpoints-missing-rate-limits.md`
- [x] Write routes are authenticated at router level — `PASS`
- [x] JWT validation/401 path exists — `PASS`
- [ ] CORS behavior is explicitly configured for self-host and split-origin deployments — `ISSUE`  
  See: `audit/issues/IMPORTANT-missing-cors-configuration.md`
- [ ] HTTP security headers are explicitly set by app/reverse-proxy policy — `ISSUE`  
  See: `audit/issues/IMPORTANT-missing-http-security-headers.md`

## 5) Secrets and sensitive data hygiene

- [x] No tracked `.env` secrets (only examples) — `PASS`
- [x] No committed private keys/PEM files — `PASS`
- [x] No obvious hardcoded credentials in source scan — `PASS`

## 6) Supply chain and dependency security process

- [x] Dependency manifests/lockfiles exist — `PASS`
- [ ] Automated dependency/vuln monitoring configured (Dependabot + scans) — `ISSUE`  
  See: `audit/issues/CRITICAL-no-automated-dependency-vulnerability-monitoring.md`

## 7) OSS governance and contributor readiness

- [ ] CONTRIBUTING.md exists — `ISSUE`  
  See: `audit/issues/IMPORTANT-missing-contributor-governance-docs.md`
- [ ] CODE_OF_CONDUCT.md exists — `ISSUE`  
  See: `audit/issues/IMPORTANT-missing-contributor-governance-docs.md`
- [ ] Public docs are separated from internal runbooks/planning docs — `ISSUE`  
  See: `audit/issues/IMPORTANT-internal-ops-runbook-exposed-in-public-docs.md`

## 8) Metadata and ownership clarity

- [ ] Published package maintainer contact policy is explicit — `ISSUE`  
  See: `audit/issues/IMPORTANT-personal-email-in-package-metadata.md`
- [ ] Trademark/branding policy for forks is documented — `UNKNOWN`

## 9) CI/release controls

- [x] CI runs lint/typecheck/tests/migration checks — `PASS`
- [x] Deploy and release-note workflows exist — `PASS`
- [x] Recent `main` workflows are mostly green — `PASS`
- [ ] Ownership rules are resilient to maintainer churn (team-based CODEOWNERS where appropriate) — `ISSUE`  
  See: `audit/issues/IMPORTANT-codeowners-uses-personal-user-instead-of-team.md`

---

## Findings summary from checklist iteration

### OSS release blockers (must fix before public release)

1. `audit/issues/BLOCKER-hardcoded-modal-custom-domains-break-third-party-deploys.md`
2. `audit/issues/BLOCKER-hardcoded-cli-default-api-urls-lock-to-maintainer-infra.md`
3. `audit/issues/BLOCKER-missing-license-metadata-in-shared-and-server-packages.md`
4. `audit/issues/BLOCKER-security-disclosure-policy-missing.md`

### Urgent issues (fix ASAP; can be deferred only with explicit compensating controls)

1. `audit/issues/CRITICAL-public-auth-endpoints-missing-rate-limits.md`
2. `audit/issues/CRITICAL-hardcoded-public-domains-in-seo-and-ux.md`
3. `audit/issues/CRITICAL-no-automated-dependency-vulnerability-monitoring.md`

### Important but clearly deferrable issues

1. `audit/issues/IMPORTANT-frontend-env-example-points-to-private-dev-backend.md`
2. `audit/issues/IMPORTANT-missing-contributor-governance-docs.md`
3. `audit/issues/IMPORTANT-internal-ops-runbook-exposed-in-public-docs.md`
4. `audit/issues/IMPORTANT-personal-email-in-package-metadata.md`
5. `audit/issues/IMPORTANT-missing-cors-configuration.md`
6. `audit/issues/IMPORTANT-missing-http-security-headers.md`
7. `audit/issues/IMPORTANT-codeowners-uses-personal-user-instead-of-team.md`

---

## Suggested remediation sequence (round 02)

1. **Day 0 (release gate):** close all BLOCKER items.
2. **Week 1 hardening:** close CRITICAL items or explicitly document compensating controls and deadlines.
3. **Post-release stabilization:** close IMPORTANT items in descending operational risk (security posture first, governance/metadata next).

