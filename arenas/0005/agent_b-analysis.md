## RISKS — Known risks, edge cases, trade-offs

### Risk 1: Day 0 Remediation Is Cross-Cutting

The 6 blockers touch deploy config, CLI defaults, package metadata, documentation, and legal files across 4 packages. Fixing them as isolated PRs is straightforward (~3-4 hours total), but integration testing the combined changes requires deploying a dev instance to verify nothing breaks. Budget an additional 1-2 hours for verification.

**Mitigation:** Fix blockers in dependency order: (1) license metadata, (2) SECURITY.md, (3) remove PRD.md/tasks.md, (4) sanitize CLAUDE.md, (5) Modal domains, (6) CLI URLs. Items 1-4 have zero runtime risk. Items 5-6 affect deployment behavior and need testing.

### Risk 2: Release Contract Ambiguity Persists

If the team hasn't decided whether self-hosting is first-class, ~40% of findings have ambiguous severity. SEO domains, Modal secret names, and some `pymc-labs` references are only CRITICAL if forks are expected to be fully independent. For a "hosted product + open code" release, they're IMPORTANT.

**Mitigation:** Answer the release contract question before cutting the release. If unclear, treat as "self-host first-class" (the stricter interpretation) to avoid post-release complaints from early adopters who try to self-host.

### Risk 3: Auth Endpoint Abuse Vector

`/auth/github/code` and `/auth/github/token` are unthrottled. While GitHub's upstream device flow has its own rate limits, an attacker could exhaust the project's GitHub OAuth API budget or trigger expensive DB operations.

**Mitigating factors:** GitHub's device flow endpoints return rate-limit errors to abusers. The `/auth/github/token` endpoint requires a valid `device_code`. Modal may have edge-level protection. Classified as CRITICAL (Week 1) rather than BLOCKER because of these mitigating factors.

### Risk 4: CLAUDE.md Sanitization Is Subjective

What counts as "sensitive operational detail" vs "useful development context" requires judgment. Over-sanitizing creates a sterile document that doesn't help contributors. Under-sanitizing leaves reconnaissance surface.

**Mitigation:** Err on the side of stripping. Specific identifiers to remove are enumerated in the issue file (App IDs, Installation IDs, Modal secret names, PEM paths). Everything else (code standards, logging conventions, testing approach) stays. If in doubt, ask: "Would this help an attacker target our production infrastructure?" If yes, strip it.

### Risk 5: Git History Is Clean but Irrevocable

The git history audit found no secrets via `git log` filters, but once the repo is public, the full history is permanently exposed. A dedicated scanner (`trufflehog`, `gitleaks`) would catch objects in deleted branches and force-pushed commits that `git log` misses.

**Mitigation:** Run `trufflehog` or `gitleaks` against the repo before making it public. Takes minutes, provides high confidence.

### Risk 6: License Metadata Is Trivial but High-Impact

Adding `license = "MIT"` to three files is a 5-minute fix, but *not* doing it causes `dhub-core` on PyPI to show "License: UNKNOWN," blocking enterprise adoption. This is the highest ROI fix in the entire audit.

### Risk 7: Modal Vendor Lock-in Is Visible but Not Fixable Pre-Release

The entire deployment stack is Modal-specific. The OSS release makes this dependency visible. Abstracting Modal is a major architectural effort not worth doing before release. Document it as a known limitation.

---

## OPEN QUESTIONS — Uncertainties requiring verification

### Q1: Release contract — hosted product or self-host first-class?

This is the single most important question. It determines severity of ~40% of findings (SEO domains, Modal secret names, some branding references). Needs an explicit answer from the project owner before triage.

### Q2: Should `trufflehog` or `gitleaks` be run before release?

The git history audit used `git log` filters. A dedicated scanner would catch objects in deleted branches. **Recommendation: run before making the repo public.** Takes minutes.

### Q3: Is the copyright holder correct?

LICENSE says "Copyright (c) 2025 Luca Fiaschi." If others contributed under PyMC Labs employment, the copyright should reflect that. Verify with legal.

### Q4: Are there trademark concerns with "Decision Hub"?

MIT license allows code reuse but not trademark rights. If "Decision Hub" is trademarked, forks need guidance on naming. Consider a trademark notice in README.

### Q5: Does Modal's edge infrastructure rate-limit auth endpoints?

If Modal's proxy layer already throttles per-IP, the auth rate-limit finding is lower urgency. Verify with Modal docs or support.

### Q6: What is the PyPI governance model post-OSS?

Will OSS contributors be able to publish `dhub-cli` / `dhub-core` releases, or does this remain centrally controlled? Document the trust model.

### Q7: Will GitHub Actions workflows work for forks?

CI references GitHub Environments (`dev`) with specific secrets. Forks will fail on deploy workflows without configuration. Consider a "fork setup" guide.

### Q8: Is transitive dependency license attestation required?

Current audit checked direct dependencies only. Enterprise legal may require full transitive license scans. (Raised by Agent C.)

---

## DISAGREEMENTS — Remaining substantive disagreements with other approaches

### 1. CLAUDE.md as IMPORTANT vs BLOCKER (Agent C)

Agent C classifies operational runbook exposure as IMPORTANT. I maintain BLOCKER because CLAUDE.md contains specific GitHub App IDs (2887189, 2887208), Installation IDs (111380021, 111379955), and Modal secret naming patterns that reduce attacker reconnaissance effort against live infrastructure. This is distinct from PRD.md/tasks.md (strategy exposure, IMPORTANT-tier risk).

However, this disagreement has narrowed significantly. Agent C's round 01 revision correctly expanded the issue scope to include PRD.md, tasks.md, and `.claude/commands/*`, and the remediation path (sanitize, not delete) is now shared across all agents. The remaining disagreement is purely about severity classification of the operational identifiers, not about whether action is needed.

### 2. Issue count as a weakness

Agent C frames 19 findings as potentially causing "execution paralysis." I maintain that comprehensiveness is a feature, not a bug — the round 02 remediation sequencing (Day 0 / Week 1 / Post-release) directly addresses the execution concern without dropping valid findings. A 6-issue audit that misses license declarations, auth rate limits, SEO domains, and internal docs is a more dangerous outcome than a 19-issue audit with clear priorities.

### 3. No remaining factual disagreements

All factual claims have been verified or corrected across two rounds. The license count (Agent C's correction) is now accurate. The auth rate-limit gap (Agent C's original finding) is confirmed. The branding vs. lock-in distinction (Agent C's analytical contribution) is adopted.
