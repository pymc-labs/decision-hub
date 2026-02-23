## PLAN — Numbered key decisions with rationale

### Round 01 revision — changes from round 00

This revision incorporates three key corrections from cross-agent critiques:
- **Factual fix:** Round 00 incorrectly claimed "rate limiting on all public endpoints." Auth endpoints (`/auth/github/code`, `/auth/github/token`) have no rate-limit dependencies. Corrected in checklist and added as a new CRITICAL issue. (Credit: Agent C)
- **Severity re-classification:** SECURITY.md elevated from CRITICAL to BLOCKER. Agent C's argument — that the first external vulnerability report will default to public disclosure without a private channel — is compelling for a project with live production infrastructure. (Consensus: Agent C proposed, Agent B and Agent A acknowledged in critiques)
- **Analytical sharpening:** Separated `pymc-labs` references into three categories — branding (keep), infrastructure lock-in (blocker), cosmetic coupling (fix post-release) — per Agent C's critique that "branding references are acceptable; hardcoded infra behavior that prevents deploy is the blocker."

---

### Numbered decisions

1. **Structured as a completed audit with status indicators, not a template.** Every checklist item is marked PASS (`[x]`), ISSUE (`[ ]` with linked issue file), or UNKNOWN (`[?]` needing owner confirmation). Agent A's round 00 checklist left all items unchecked, which is a template, not an audit. Agent C's PASS/ISSUE/UNKNOWN legend was the right approach.

2. **Six release blockers identified** (up from 5 in round 00):
   - **NEW: Missing SECURITY.md** — elevated from CRITICAL. No private vulnerability reporting channel means the first external security finding becomes a public 0-day disclosure against live production infrastructure.
   - Hardcoded CLI API URLs (`config.py`) — every `pip install dhub-cli` user hits PyMC Labs servers by default
   - Hardcoded Modal custom domains (`modal_app.py:65`) — `modal deploy` fails for third parties because `hub.decision.ai` is already claimed
   - Sensitive info in CLAUDE.md/AGENTS.md — operational runbook with GitHub App IDs, Modal secret names
   - Missing license declarations in 3 sub-packages — `dhub-core` on PyPI shows "License: UNKNOWN"
   - Internal planning docs committed (PRD.md, tasks.md) — product strategy exposure

3. **Five critical issues** (up from 4 in round 00):
   - **NEW: Auth endpoint rate limiting** — `/auth/github/code` and `/auth/github/token` are unthrottled unlike every other public endpoint. Mitigated partially by GitHub's upstream limits but still an abuse vector.
   - `pymc-labs` infrastructure lock-in vs cosmetic coupling — now cleanly separated
   - Missing contributor/governance docs (CONTRIBUTING, CODE_OF_CONDUCT, issue templates)
   - Hardcoded SEO domains (5+ files)
   - Modal secret name prefix hardcoded

4. **Eight important issues** (up from 7 in round 00):
   - **NEW: Personal email in metadata** (from Agent A) — Gmail in `client/pyproject.toml` vs PyMC Labs email in LICENSE
   - CORS middleware, security headers, dependency audit, print statement, personal Modal URLs, .claude directory, CODEOWNERS

5. **Confirmed clean areas remain unchanged:**
   - No secrets in source or git history
   - No private keys tracked
   - SQL injection protection (parameterized queries)
   - JWT authentication on write endpoints
   - API key encryption at rest (Fernet)
   - All dependency licenses MIT-compatible

6. **Adopted the branding vs lock-in distinction** (from Agent C's critique). The `pymc-labs` references issue now explicitly separates:
   - **Category A (keep):** Maintainer attribution in README, footer, legal pages — standard OSS practice
   - **Category B (blocker):** Hardcoded Modal workspace in API URLs and custom domains — tracked in BLOCKER issues
   - **Category C (cosmetic, fix post-release):** Example commands, featured orgs, animated terminal — make the project feel proprietary but don't break functionality

7. **Maintained comprehensive coverage** as the primary differentiator. Round 00 evaluation confirmed this audit has the broadest coverage (19 issues vs 6 each from Agents A and C). The revision tightens signal-to-noise by improving issue quality rather than reducing quantity — every issue now has sharper classification and deferral rationale.

## CHANGES — Unified diff or precise change descriptions

### New files created (round 01)

- `audit/issues/BLOCKER-security-disclosure-policy-missing.md` — SECURITY.md blocker with template fix and effort estimate (15-30 min)
- `audit/issues/CRITICAL-auth-endpoints-missing-rate-limits.md` — auth rate-limit gap with evidence, mitigating factors, and implementation pattern
- `audit/issues/IMPORTANT-personal-email-in-metadata.md` — personal Gmail in package metadata

### Files modified (round 01)

- `audit/oss-release-checklist.md` — complete rewrite:
  - Fixed factual error in security section (auth endpoints now correctly marked as unthrottled)
  - Added Security Governance section (SECURITY.md, dependency monitoring)
  - Restructured infrastructure section with branding distinction
  - Updated findings summary: 6 BLOCKERS, 5 CRITICAL, 8 IMPORTANT
  - Added `[?]` UNKNOWN items for owner verification (trufflehog scan, copyright holder, trademark)

- `audit/issues/CRITICAL-missing-oss-community-docs.md` — removed SECURITY.md (now tracked as separate BLOCKER), retitled to "Contributor & Governance Documents"

- `audit/issues/CRITICAL-pymc-labs-references-throughout-codebase.md` — complete rewrite with three-category framework (branding / lock-in / cosmetic), explicit keep/fix/defer guidance per category

### Files unchanged from round 00

All other BLOCKER, CRITICAL, and IMPORTANT issue files remain unchanged — their findings and recommendations were validated by cross-agent review with no factual corrections needed.

### Complete issue inventory (19 files)

**BLOCKERS (6):**
1. `BLOCKER-security-disclosure-policy-missing.md` — **NEW**
2. `BLOCKER-hardcoded-api-urls-in-client.md`
3. `BLOCKER-hardcoded-custom-domains-in-modal.md`
4. `BLOCKER-sensitive-info-in-claude-agents-md.md`
5. `BLOCKER-missing-license-declarations.md`
6. `BLOCKER-internal-docs-committed.md`

**CRITICAL (5):**
1. `CRITICAL-auth-endpoints-missing-rate-limits.md` — **NEW**
2. `CRITICAL-pymc-labs-references-throughout-codebase.md` — **REVISED**
3. `CRITICAL-missing-oss-community-docs.md` — **REVISED**
4. `CRITICAL-seo-hardcoded-domains.md`
5. `CRITICAL-modal-secret-names-hardcoded.md`

**IMPORTANT (8):**
1. `IMPORTANT-missing-cors-configuration.md`
2. `IMPORTANT-print-statement-in-production.md`
3. `IMPORTANT-missing-security-headers.md`
4. `IMPORTANT-dependency-audit-needed.md`
5. `IMPORTANT-personal-modal-urls-in-examples.md`
6. `IMPORTANT-claude-directory-test-commands.md`
7. `IMPORTANT-codeowners-personal-username.md`
8. `IMPORTANT-personal-email-in-metadata.md` — **NEW**
