## PLAN — Numbered key decisions with rationale

1. **Structured the audit as a 10-category checklist** covering secrets, infrastructure references, org/company references, license, documentation, security, GitHub Apps, CI/CD, test data, and git history. Rationale: a comprehensive audit needs orthogonal categories to avoid blind spots; these ten cover the full surface area of an OSS release.

2. **Ran parallel automated audits** using separate agents for secrets scanning, infrastructure reference discovery, security analysis, license compliance, documentation readiness, and git history review. Rationale: parallel execution covers more ground than sequential manual inspection; each agent focuses on one dimension and can be thorough.

3. **Classified issues into three tiers** (BLOCKER / CRITICAL / IMPORTANT) with explicit deferral rationale for non-blockers. Rationale: not all issues are equal — blockers prevent a functional OSS release, critical issues hurt credibility but can be fixed in the first week, and important issues are quality improvements.

4. **Identified 5 release blockers:**
   - Hardcoded PyMC Labs API URLs in CLI client (`config.py`) — every `pip install dhub-cli` user hits PyMC Labs' servers by default
   - Hardcoded custom domains in Modal deployment (`modal_app.py:65`) — `modal deploy` fails for anyone else because `hub.decision.ai` is claimed
   - Sensitive info in CLAUDE.md/AGENTS.md — GitHub App IDs, Modal secret names, internal deployment details
   - Missing license declarations in 3 of 4 sub-packages — `dhub-core` on PyPI shows "License: UNKNOWN"
   - Internal planning docs committed (PRD.md, tasks.md) — product strategy exposure

5. **Identified 4 critical (urgent but deferrable) issues:**
   - `pymc-labs` hardcoded in 50+ locations across frontend, examples, legal pages
   - Missing community docs (SECURITY.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue templates)
   - Hardcoded SEO domains (`hub.decision.ai`, `decisionhub.dev`) in 5+ files
   - Modal secret names hardcoded with `decision-hub-` prefix

6. **Identified 7 important (clearly deferrable) issues:**
   - No explicit CORS middleware
   - Missing HTTP security headers
   - Dependency vulnerability audit not performed
   - `print()` in production code instead of logger
   - Personal Modal URLs in example files
   - `.claude/` directory with internal test commands
   - CODEOWNERS using personal username

7. **Confirmed several areas are clean and release-ready:**
   - No secrets in source code or git history
   - No private keys tracked
   - SQL injection protection (parameterized queries throughout)
   - JWT authentication on write endpoints
   - Rate limiting on all public endpoints
   - Input validation with max_length constraints
   - API key encryption at rest (Fernet)
   - All dependency licenses compatible with MIT

## CHANGES — Unified diff or precise change descriptions

No code changes were made. This audit is a read-only assessment producing:

### Files Created

**Checklist:**
- `audit/oss-release-checklist.md` — 10-category checklist with 50+ items, each marked checked (pass) or unchecked (needs attention)

**Blocker Issues (5):**
- `audit/issues/BLOCKER-hardcoded-api-urls-in-client.md`
- `audit/issues/BLOCKER-hardcoded-custom-domains-in-modal.md`
- `audit/issues/BLOCKER-sensitive-info-in-claude-agents-md.md`
- `audit/issues/BLOCKER-missing-license-declarations.md`
- `audit/issues/BLOCKER-internal-docs-committed.md`

**Critical Issues (4):**
- `audit/issues/CRITICAL-pymc-labs-references-throughout-codebase.md`
- `audit/issues/CRITICAL-missing-oss-community-docs.md`
- `audit/issues/CRITICAL-seo-hardcoded-domains.md`
- `audit/issues/CRITICAL-modal-secret-names-hardcoded.md`

**Important Issues (7):**
- `audit/issues/IMPORTANT-missing-cors-configuration.md`
- `audit/issues/IMPORTANT-print-statement-in-production.md`
- `audit/issues/IMPORTANT-missing-security-headers.md`
- `audit/issues/IMPORTANT-dependency-audit-needed.md`
- `audit/issues/IMPORTANT-personal-modal-urls-in-examples.md`
- `audit/issues/IMPORTANT-claude-directory-test-commands.md`
- `audit/issues/IMPORTANT-codeowners-personal-username.md`

Each issue file contains: summary, affected files with line numbers, explanation of why it matters, recommended fix, and deferral rationale (for non-blockers).
