## PLAN — Numbered key decisions with rationale.

1. **Incorporate round-03 critique convergence from all agents.**  
   Re-read agent A/B/C critiques and preserved convergence on core blockers (deployability, legal clarity, security disclosure), while integrating stronger execution and scope details highlighted in feedback.

2. **Keep blocker criteria tied to major release headaches.**  
   Maintained blocker focus on immediate OSS failure modes (third-party deploy breakage, incorrect default routing, legal metadata ambiguity, no disclosure channel), and split out a dedicated blocker for sensitive operational identifiers in public runbooks.

3. **Adopt stronger breadth without inflating severity.**  
   Added high-signal important issues requested by feedback (print usage in production path, one-time dependency vulnerability audit) while keeping blocker/critical tiers focused.

4. **Strengthen execution sequencing with rough effort sizing.**  
   Updated remediation sequence to include estimated effort windows (Day 0 release gate, Week 1 hardening, post-release stabilization) to reduce triage ambiguity.

5. **Preserve lock-in vs branding distinction.**  
   Continued separating informational branding from runtime/deploy coupling so severity maps to functional impact, not merely project attribution.

## CHANGES — Unified diff or precise change descriptions.

- **Updated** `audit/oss-release-checklist.md` to **Round 03**:
  - retained blocker/critical/important classification,
  - added release-contract decision gate at the top,
  - added explicit checks for CORS policy, HTTP security header policy, CODEOWNERS resilience, one-time dependency audit, and print/log consistency,
  - upgraded remediation sequence with rough effort estimates.

- **Added blocker issue file**:
  - `audit/issues/BLOCKER-sensitive-operational-identifiers-in-public-runbooks.md`

- **Added important issue files**:
  - `audit/issues/IMPORTANT-print-statement-in-production-tracker-job.md`
  - `audit/issues/IMPORTANT-run-one-time-dependency-vulnerability-audit-before-release.md`

- **Updated existing important issue**:
  - `audit/issues/IMPORTANT-internal-ops-runbook-exposed-in-public-docs.md` now focuses on planning/scratch artifacts (`PRD.md`, `tasks.md`, `.claude/commands/*`), while sensitive operational identifiers moved to the new blocker.

- **Current classification after revision**:
  - blockers: modal custom domains, CLI default API URLs, missing package license metadata (shared/server), missing `SECURITY.md`, sensitive operational identifiers in public runbooks.
  - critical: auth endpoint rate limits, hardcoded public domains/SEO coupling, missing dependency security automation.
  - important: governance docs, planning/scratch artifacts, personal metadata email, frontend env template neutrality, CORS/header policy, CODEOWNERS resilience, print/log consistency, one-time dependency audit.

