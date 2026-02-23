## PLAN — Numbered key decisions with rationale

### Round 03 — Final revision

This round applies targeted refinements from round 02 critiques. The audit has converged across all three agents — round 03 changes are incremental, not structural.

**Changes from round 02:**
- **Exit criteria per remediation phase** (from Agent C's critique): Each phase (Day 0, Week 1, Post-release) now has explicit exit criteria defining what "done" looks like. Day 0 criteria include deployment verification and content checks. Week 1 criteria include behavioral verification (429 responses on auth endpoints, config-driven SEO URLs). This was Agent C's strongest remaining critique — "tighter exit criteria per phase."
- **Checklist marked as final.** After three rounds of cross-agent review with zero remaining factual errors and near-complete convergence, the checklist and 19 issue files represent the definitive audit.

---

### Numbered decisions (stable from round 02)

1. **Release contract question precedes all triage.** The strategic question "hosted product + open code vs. self-host first-class OSS" determines severity of ~40% of findings. Placed at the top of the checklist.

2. **Six release blockers — total Day 0 effort ~3-4 hours:**
   - Missing SECURITY.md (~15 min)
   - Missing license declarations in server, shared, frontend (~5 min)
   - Hardcoded Modal custom domains (~30 min)
   - Hardcoded CLI API URLs (~30 min)
   - CLAUDE.md/AGENTS.md sanitization (~1-2 hr) — sanitize, don't delete
   - Internal planning docs removal (~5 min)

3. **Five critical issues — total Week 1 effort ~5-7 hours:**
   - Auth endpoint rate limiting (~1 hr)
   - Community docs (~1-2 hr)
   - `pymc-labs` infrastructure lock-in + cosmetic coupling (~2-3 hr)
   - SEO domain hardcoding (~1 hr)
   - Modal secret name prefix (~30 min)

4. **Eight important issues — tracked as GitHub issues post-release.**

5. **Exit criteria added for each phase.** Day 0 exit criteria verify that deployment, CLI routing, content sanitization, and legal metadata are all correct. Week 1 criteria verify behavioral changes (rate limiting, config-driven URLs, contributor-facing docs).

6. **19-issue comprehensive inventory maintained.** All three agents converge on this scope. No findings dropped, no false positives after three rounds of review.

7. **Three-category branding framework stable.** Branding (keep) / lock-in (blocker) / cosmetic (critical/important) validated across all rounds.

## CHANGES — Unified diff or precise change descriptions

### Files modified (round 03)

- `audit/oss-release-checklist.md`:
  - Added explicit exit criteria for Day 0 phase (6 verification items: SECURITY.md presence, license fields, deployment test, CLI routing test, CLAUDE.md content check, PRD/tasks absence)
  - Added explicit exit criteria for Week 1 phase (5 verification items: auth 429 responses, CONTRIBUTING/CODE_OF_CONDUCT existence, SEO config derivation, generic frontend examples, Modal secret env vars)
  - Added post-release tracking guidance (create GitHub issues on release day)
  - Marked checklist as "round 03 — final"

### Complete issue inventory (19 files, unchanged from round 02)

**BLOCKERS (6):**
1. `BLOCKER-security-disclosure-policy-missing.md`
2. `BLOCKER-missing-license-declarations.md`
3. `BLOCKER-hardcoded-custom-domains-in-modal.md`
4. `BLOCKER-hardcoded-api-urls-in-client.md`
5. `BLOCKER-sensitive-info-in-claude-agents-md.md`
6. `BLOCKER-internal-docs-committed.md`

**CRITICAL (5):**
1. `CRITICAL-auth-endpoints-missing-rate-limits.md`
2. `CRITICAL-missing-oss-community-docs.md`
3. `CRITICAL-pymc-labs-references-throughout-codebase.md`
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
8. `IMPORTANT-personal-email-in-metadata.md`
