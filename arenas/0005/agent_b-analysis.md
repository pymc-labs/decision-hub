## RISKS — Known risks, edge cases, trade-offs

### Risk 1: Day 0 Remediation Is Cross-Cutting but Low-Risk

The 6 blockers touch deploy config, CLI defaults, package metadata, documentation, and legal files across 4 packages. Total effort is ~3-4 hours. Fix in dependency order: (1) license metadata, (2) SECURITY.md, (3) remove PRD.md/tasks.md — these three have zero runtime risk. Then (4) sanitize CLAUDE.md, (5) Modal domains, (6) CLI URLs — these affect deployment behavior and need testing. Budget 1-2 additional hours for verification against the exit criteria.

### Risk 2: Release Contract Ambiguity

If the team hasn't decided whether self-hosting is first-class, ~40% of findings have ambiguous severity. Default to the stricter interpretation ("self-host first-class") to avoid post-release complaints from early adopters who try to self-host and hit hardcoded infrastructure.

### Risk 3: Auth Endpoint Abuse

`/auth/github/code` and `/auth/github/token` are unthrottled. Mitigated partially by GitHub's upstream device flow limits and the requirement for a valid `device_code`. Classified as CRITICAL (Week 1) not BLOCKER because of these compensating controls. If Modal's edge infrastructure also rate-limits, urgency is further reduced.

### Risk 4: CLAUDE.md Sanitization Requires Judgment

Strip all specific identifiers (App IDs, Installation IDs, Modal secret names, PEM paths, troubleshooting commands referencing infrastructure). Keep all development guidelines (code standards, design principles, testing conventions, logging patterns). If in doubt: "Would this help an attacker target production infrastructure?" If yes, strip it.

### Risk 5: Git History Is Clean but Should Be Verified with Dedicated Tools

Run `trufflehog` or `gitleaks` before making the repo public. The `git log` audit found no secrets, but dedicated scanners check all git objects including deleted branches. Takes minutes, provides high confidence.

### Risk 6: License Metadata Is the Highest-ROI Fix

Adding `license = "MIT"` to three files takes 5 minutes but prevents `dhub-core` on PyPI from showing "License: UNKNOWN" which blocks enterprise adoption. Fix first.

### Risk 7: Modal Vendor Lock-in Is Visible but Not Fixable Pre-Release

The entire deployment stack is Modal-specific. Document as a known limitation. Abstracting Modal is a major architectural effort not warranted before release.

---

## OPEN QUESTIONS — Uncertainties requiring verification

### Q1: Release contract — hosted product or self-host first-class?

Determines severity of ~40% of findings. Needs an explicit answer from the project owner before triage.

### Q2: Should `trufflehog` or `gitleaks` be run before release?

Recommended. Takes minutes. Provides higher confidence than `git log` filters.

### Q3: Is the copyright holder correct?

LICENSE says "Copyright (c) 2025 Luca Fiaschi." Verify whether it should be "PyMC Labs" or "PyMC Labs and contributors."

### Q4: Are there trademark concerns with "Decision Hub"?

MIT license covers code reuse but not trademark rights. Consider a trademark notice in README if the name is trademarked.

### Q5: Does Modal's edge infrastructure rate-limit auth endpoints?

If yes, the auth rate-limit finding drops in urgency. Verify with Modal docs or support.

### Q6: What is the PyPI governance model post-OSS?

Will OSS contributors publish releases, or is this centrally controlled? Document the trust model.

### Q7: Will GitHub Actions workflows work for forks?

CI references GitHub Environments with specific secrets. Forks need guidance. Consider a "fork setup" section in CONTRIBUTING.md.

### Q8: Is transitive dependency license attestation required?

Current audit checked direct dependencies only. Enterprise legal may require full transitive scans.

### Q9: Should CORS and security headers be enforced in app middleware, edge proxy, or both?

(From Agent C.) Self-hosters need guidance on where these policies should live. Document the recommended architecture.

### Q10: Is there a GitHub team alias ready for CODEOWNERS migration?

(From Agent C.) Current CODEOWNERS uses a personal username. If a team alias exists, migration is straightforward. If not, creating one should precede the CODEOWNERS change.

---

## DISAGREEMENTS — Remaining substantive disagreements with other approaches

### CLAUDE.md severity: BLOCKER (Agent B) vs IMPORTANT (Agent C)

This is the sole remaining disagreement across all three agents. The remediation is identical (sanitize, don't delete). The disagreement is purely about timing — must it be done before the first public commit (BLOCKER/Day 0) or can it be tracked for shortly after (IMPORTANT)?

**My position (BLOCKER):** The file contains specific production GitHub App IDs (2887189, 2887208), Installation IDs (111380021, 111379955), and Modal secret naming patterns. While these are not secrets per se, publishing them in the first public commit creates a permanent record that reduces attacker reconnaissance effort against live infrastructure. The 1-2 hour sanitization effort is well within the Day 0 budget.

**Agent C's position (IMPORTANT):** App IDs are already visible in GitHub's UI. The operational details are context-dependent reconnaissance risk, not direct compromise vectors. The file's development value (code standards, contribution patterns) is high. Deferring briefly while the repo is low-visibility is acceptable.

**Resolution path:** This is a judgment call. If the team wants maximum security posture, classify as BLOCKER (my recommendation). If the team wants minimum release friction, classify as IMPORTANT and commit to sanitization within 48 hours of going public. Either way, the sanitization work is identical.

No other substantive disagreements remain. All three agents agree on: the 19-issue scope, the core 5 blockers, auth rate limiting as CRITICAL, the branding/lock-in/cosmetic framework, sanitize-not-delete for CLAUDE.md, remediation sequencing, exit criteria, and the release contract as the top strategic question.
