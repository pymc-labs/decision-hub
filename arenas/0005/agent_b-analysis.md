## RISKS — Known risks, edge cases, trade-offs

### Risk 1: Day 0 Is Now Very Light (~2 hours)

Only 4 blockers remain: SECURITY.md (15 min), license metadata (5 min), CLAUDE.md sanitization (1-2 hr), and PRD.md/tasks.md removal (5 min). This is a comfortable budget. The main risk is CLAUDE.md sanitization requiring judgment calls on borderline content.

### Risk 2: "Hosted Product" Framing May Confuse Contributors

If contributors expect a fully self-hostable project but find hardcoded infrastructure everywhere, they may file issues or feel misled. Mitigation: document the release contract clearly in README.md — "Decision Hub is operated as a hosted service by PyMC Labs. The source code is open under MIT. Self-hosting is possible but requires infrastructure configuration."

### Risk 3: Auth Endpoint Abuse Still Exists

`/auth/github/code` and `/auth/github/token` are unthrottled. This affects the hosted product directly. Classified as CRITICAL with a 1-week fix window. GitHub's upstream rate limits provide partial mitigation.

### Risk 4: Modal Custom Domains Block Contributor Development

Contributors who try `modal deploy modal_app.py` will fail. This is the main friction point for anyone wanting to contribute server-side changes. Making `CUSTOM_DOMAINS` configurable with an empty default is a 30-minute fix that unblocks the contributor workflow.

### Risk 5: Git History Exposure

The git history audit found no secrets, but a `trufflehog` / `gitleaks` scan is still recommended before going public. The history becomes permanently public and irrevocable.

### Risk 6: CLAUDE.md Sanitization Requires Judgment

Strip: App IDs (2887189, 2887208), Installation IDs (111380021, 111379955), Modal secret names, PEM paths, and troubleshooting commands referencing specific infrastructure. Keep: code standards, design principles, testing conventions, logging patterns. Rule of thumb: "Would this help an attacker target production infrastructure?" If yes, strip it.

---

## OPEN QUESTIONS — Uncertainties requiring verification

### Q1: Should the README explicitly state the "hosted product + open code" model?

Recommended. A clear statement like "Decision Hub is a hosted service by PyMC Labs. The source code is open under MIT." sets expectations for contributors and avoids confusion about self-hosting support.

### Q2: Should `trufflehog` or `gitleaks` be run before release?

Recommended. Takes minutes. Catches secrets in deleted branches that `git log` misses.

### Q3: Is the copyright holder correct?

LICENSE says "Copyright (c) 2025 Luca Fiaschi." Verify with legal.

### Q4: Are there trademark concerns with "Decision Hub"?

If trademarked, add a notice to README.

### Q5: Does Modal's edge infrastructure rate-limit auth endpoints?

If yes, the auth rate-limit CRITICAL drops further in urgency.

### Q6: Is there a GitHub team alias ready for CODEOWNERS migration?

Current CODEOWNERS uses `@lfiaschi`. Migrating to a team alias improves bus-factor resilience.

---

## DISAGREEMENTS — Any remaining substantive disagreements with the other approaches, or "None."

None. The "hosted product + open code" decision resolves the primary source of disagreement across all previous rounds. Infrastructure coupling that was previously contested (CLI URLs, SEO domains, Modal secrets, branding) is now explicitly intentional. The remaining blockers (SECURITY.md, license metadata, CLAUDE.md sanitization, internal docs) and criticals (auth rate limits, community docs, Modal custom domains) have unanimous agreement.
