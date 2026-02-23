## PLAN — Numbered key decisions with rationale

### Round 02 revision — changes from round 01

This revision incorporates three improvements from round 01 cross-agent critiques:

- **Remediation sequencing** (from Agents A and C): Added explicit Day 0 / Week 1 / Post-release priority ordering with effort estimates per item. Agent C's critique that "comprehensive audits also need prioritized sequencing to avoid execution paralysis" is valid — breadth without ordering creates triage overhead.
- **CLAUDE.md remediation refined** (consensus across all agents): Changed from "move or delete" to "sanitize and retain." All three agents agree CLAUDE.md contains both valuable development guidelines (keep) and sensitive operational identifiers (strip). The round 02 issue file now specifies exactly what to strip (App IDs, Installation IDs, Modal secret names, PEM paths) and what to keep (code standards, design principles, testing conventions).
- **Release contract framing** (from Agent C): Added the strategic question "Is this release hosted product + open code, or fork/self-host first-class OSS?" at the top of the checklist. This determines severity of ~40% of findings and should be answered before triage begins.
- **License count correction** (from Agent C): Clarified that `client/pyproject.toml` already has `license = "MIT"`. The missing declarations are in server, shared, and frontend only. The issue file was already accurate; the checklist and summary text now match.

---

### Numbered decisions

1. **Structured as a completed audit with prioritized remediation sequence.** Every checklist item has PASS/ISSUE/UNKNOWN status. The top of the document now contains a Day 0 / Week 1 / Post-release remediation table with effort estimates, converting the audit from a "findings report" into an "execution plan." This addresses Agent C's concern about volume-driven execution paralysis.

2. **Six release blockers with effort estimates** — total Day 0 effort: ~3-4 hours:
   - Missing SECURITY.md (~15 min)
   - Missing license declarations in server, shared, frontend (~5 min)
   - Hardcoded Modal custom domains (~30 min)
   - Hardcoded CLI API URLs (~30 min)
   - CLAUDE.md/AGENTS.md sanitization (~1-2 hr) — now specifies "sanitize, don't delete"
   - Internal planning docs removal (~5 min)

3. **Five critical issues with effort estimates** — total Week 1 effort: ~5-7 hours:
   - Auth endpoint rate limiting (~1 hr)
   - Community docs (CONTRIBUTING, CODE_OF_CONDUCT, issue templates) (~1-2 hr)
   - `pymc-labs` infrastructure lock-in and cosmetic coupling (~2-3 hr)
   - SEO domain hardcoding (~1 hr)
   - Modal secret name prefix (~30 min)

4. **Eight important issues** — tracked as GitHub issues post-release:
   - CORS middleware, security headers, dependency audit, print statement, personal Modal URLs, .claude directory, CODEOWNERS, personal email in metadata

5. **Release contract question precedes all triage.** The severity of many findings depends on whether self-hosting is first-class. For a "hosted product + open code" release, SEO domains and Modal secret names can be downgraded to IMPORTANT. For "self-host first-class OSS," they remain CRITICAL.

6. **Maintained comprehensive 19-issue coverage.** All three agents now acknowledge this audit has the broadest coverage. The round 02 revision addresses the signal-to-noise concern not by dropping findings but by sequencing them — Day 0 items get attention first, IMPORTANT items become GitHub issues to track post-release.

7. **Branding framework unchanged.** The three-category distinction (branding/lock-in/cosmetic) from round 01 was validated by all critiques and remains the most actionable treatment.

## CHANGES — Unified diff or precise change descriptions

### Files modified (round 02)

- `audit/oss-release-checklist.md` — major revision:
  - Added "Release Contract" decision prompt at top (from Agent C)
  - Added "Prioritized Remediation Sequence" with Day 0 / Week 1 / Post-release tables and effort estimates (from Agents A and C)
  - Explicitly marked `client/pyproject.toml` license as PASS (factual correction from Agent C)
  - Updated CLAUDE.md checklist item to say "must be sanitized" not just "contains sensitive info"
  - Added effort estimates to all items in Findings Summary

- `audit/issues/BLOCKER-sensitive-info-in-claude-agents-md.md` — refined remediation:
  - Changed recommended fix from "move to .cursor/rules or git-ignored location" to "sanitize, don't delete"
  - Specifies exactly what to strip (App IDs, Installation IDs, Modal secret names, PEM paths, troubleshooting commands)
  - Specifies what to keep (code standards, design principles, testing conventions, logging patterns)
  - Preserves AI-assisted development experience while removing reconnaissance risk

### Files unchanged from round 01

All other issue files (18 remaining) validated by cross-agent review — no factual corrections needed.

### Complete issue inventory (19 files)

**BLOCKERS (6) — Day 0:**
1. `BLOCKER-security-disclosure-policy-missing.md`
2. `BLOCKER-missing-license-declarations.md`
3. `BLOCKER-hardcoded-custom-domains-in-modal.md`
4. `BLOCKER-hardcoded-api-urls-in-client.md`
5. `BLOCKER-sensitive-info-in-claude-agents-md.md` — **REVISED** (sanitize, don't delete)
6. `BLOCKER-internal-docs-committed.md`

**CRITICAL (5) — Week 1:**
1. `CRITICAL-auth-endpoints-missing-rate-limits.md`
2. `CRITICAL-missing-oss-community-docs.md`
3. `CRITICAL-pymc-labs-references-throughout-codebase.md`
4. `CRITICAL-seo-hardcoded-domains.md`
5. `CRITICAL-modal-secret-names-hardcoded.md`

**IMPORTANT (8) — Post-release:**
1. `IMPORTANT-missing-cors-configuration.md`
2. `IMPORTANT-print-statement-in-production.md`
3. `IMPORTANT-missing-security-headers.md`
4. `IMPORTANT-dependency-audit-needed.md`
5. `IMPORTANT-personal-modal-urls-in-examples.md`
6. `IMPORTANT-claude-directory-test-commands.md`
7. `IMPORTANT-codeowners-personal-username.md`
8. `IMPORTANT-personal-email-in-metadata.md`
