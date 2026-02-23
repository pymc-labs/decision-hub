## PLAN — Numbered key decisions with rationale

### Release contract applied: "Hosted product + open code"

The team decided this is a hosted product release with open source code. The CLI is the client for the hosted service at `hub.decision.ai`. Infrastructure coupling to PyMC Labs is intentional, not a bug. This decision resolves the top-level strategic question that had driven ~40% of the audit's severity classifications.

### Key reclassifications

1. **CLI API URLs: BLOCKER → IMPORTANT.** The CLI defaulting to `pymc-labs--api.modal.run` is intentional — it routes to the hosted product. The `DHUB_API_URL` env var override already exists for contributors. Document in CONTRIBUTING.md.

2. **Modal custom domains: BLOCKER → CRITICAL.** The hosted service works fine with these. But contributors who want to deploy their own dev instance will hit Modal's domain uniqueness error. Fix in Week 1 by making `custom_domains` configurable with an empty default.

3. **SEO domains: CRITICAL → IMPORTANT.** These are the hosted product's canonical URLs. Intentional.

4. **Modal secret names: CRITICAL → IMPORTANT.** These are the hosted product's infrastructure naming. Intentional.

5. **pymc-labs references: CRITICAL → IMPORTANT.** All three categories (branding, infrastructure, cosmetic) are intentional under the hosted product model. The code is the hosted product's codebase.

6. **Company-specific frontend examples: now acceptable.** HowItWorks, AnimatedTerminal, featured orgs — all intentional branding for the hosted product.

### Final classification

**BLOCKERS (4) — Day 0 (~2 hours):**
1. Missing SECURITY.md (~15 min)
2. Missing license declarations in server, shared, frontend (~5 min)
3. CLAUDE.md sanitization — strip operational identifiers (~1-2 hr)
4. Internal planning docs removal — PRD.md, tasks.md (~5 min)

**CRITICAL (3) — Week 1 (~3 hours):**
1. Auth endpoint rate limiting (~1 hr)
2. Community docs — CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue templates (~1-2 hr)
3. Modal custom domains — make configurable for contributors (~30 min)

**IMPORTANT (12) — Post-release backlog:**
Original 8 items plus 4 downgraded from BLOCKER/CRITICAL.

## CHANGES — Unified diff or precise change descriptions

### Files renamed (category reclassification)
- `BLOCKER-hardcoded-api-urls-in-client.md` → `IMPORTANT-hardcoded-api-urls-in-client.md`
- `BLOCKER-hardcoded-custom-domains-in-modal.md` → `CRITICAL-hardcoded-custom-domains-in-modal.md`
- `CRITICAL-seo-hardcoded-domains.md` → `IMPORTANT-seo-hardcoded-domains.md`
- `CRITICAL-modal-secret-names-hardcoded.md` → `IMPORTANT-modal-secret-names-hardcoded.md`
- `CRITICAL-pymc-labs-references-throughout-codebase.md` → `IMPORTANT-pymc-labs-references-throughout-codebase.md`

### Files content-updated
- All 5 renamed files: updated rationale to reflect "hosted product" context
- `audit/oss-release-checklist.md`: complete rewrite of release contract section, remediation sequence, infrastructure coupling section, branding section, and findings summary

### Complete issue inventory (19 files)

**BLOCKERS (4):**
1. `BLOCKER-security-disclosure-policy-missing.md`
2. `BLOCKER-missing-license-declarations.md`
3. `BLOCKER-sensitive-info-in-claude-agents-md.md`
4. `BLOCKER-internal-docs-committed.md`

**CRITICAL (3):**
1. `CRITICAL-auth-endpoints-missing-rate-limits.md`
2. `CRITICAL-missing-oss-community-docs.md`
3. `CRITICAL-hardcoded-custom-domains-in-modal.md`

**IMPORTANT (12):**
1. `IMPORTANT-missing-cors-configuration.md`
2. `IMPORTANT-print-statement-in-production.md`
3. `IMPORTANT-missing-security-headers.md`
4. `IMPORTANT-dependency-audit-needed.md`
5. `IMPORTANT-personal-modal-urls-in-examples.md`
6. `IMPORTANT-claude-directory-test-commands.md`
7. `IMPORTANT-codeowners-personal-username.md`
8. `IMPORTANT-personal-email-in-metadata.md`
9. `IMPORTANT-hardcoded-api-urls-in-client.md` (downgraded from BLOCKER)
10. `IMPORTANT-seo-hardcoded-domains.md` (downgraded from CRITICAL)
11. `IMPORTANT-modal-secret-names-hardcoded.md` (downgraded from CRITICAL)
12. `IMPORTANT-pymc-labs-references-throughout-codebase.md` (downgraded from CRITICAL)
