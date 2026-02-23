## RISKS — Known risks, edge cases, trade-offs

### Risk 1: Hardcoded Infrastructure Creates a "Fork Tax"

The most pervasive risk is the tight coupling between the codebase and PyMC Labs' infrastructure. The CLI defaults to `pymc-labs--api.modal.run`, Modal deployment claims `hub.decision.ai`, and the frontend references these domains in SEO metadata. A fork requires touching 20+ files across 4 packages before basic deployment works.

**Trade-off:** Fixing all infrastructure references before release is substantial work (estimated 2-3 days). The alternative is shipping with clear "self-hosting guide" documentation that lists every configuration point, accepting that the initial fork experience is rough. The round 01 distinction between branding (keep) and lock-in (fix) helps prioritize: only Category B items are true blockers.

### Risk 2: CLAUDE.md Exposure Is a Judgment Call

`CLAUDE.md` contains GitHub App IDs, Modal secret names, and internal deployment procedures. None of these are secrets per se — App IDs are visible in GitHub's UI, and secret names don't grant access. However, publishing the full operational runbook reduces the attacker's reconnaissance effort.

**Trade-off:** Removing `CLAUDE.md` entirely degrades the AI-assisted development experience for the project. Moving it to `.cursor/rules` (git-ignored) means forks lose the development guidelines. The middle ground is a sanitized version that strips infrastructure identifiers while keeping code standards. Agent C correctly noted this is "context-dependent" — the risk depends on the threat model.

### Risk 3: Auth Endpoint Abuse Vector (NEW in round 01)

`/auth/github/code` and `/auth/github/token` are unthrottled. While GitHub's upstream device flow has its own rate limits, an attacker could:
- Flood `/auth/github/code` to exhaust the project's GitHub OAuth API budget
- Flood `/auth/github/token` to trigger expensive DB upserts and GitHub API calls

**Mitigating factors:** GitHub's device flow endpoints return rate-limit errors to abusers directly. The `/auth/github/token` endpoint requires a valid `device_code` from a real GitHub flow, limiting amplification. Modal may have edge-level protection.

**Trade-off:** This is deferrable because of the mitigating factors, but should be fixed within the first week. The implementation pattern is already established in the codebase (copy from any other rate-limited endpoint).

### Risk 4: Missing SECURITY.md Is High-Consequence (ELEVATED in round 01)

Without a security disclosure policy, the first vulnerability discovered by an external researcher will likely be disclosed publicly. For a project with live production infrastructure, this creates a 0-day window.

**Trade-off:** None. This takes 15-30 minutes to create and has no downside. Should not be deferred.

### Risk 5: License Ambiguity for Enterprise Adopters

While the root LICENSE file is MIT, three sub-packages lack license metadata. Enterprise license compliance tools (FOSSA, Snyk, etc.) flag packages without declared licenses. The `dhub-core` package on PyPI is the most concerning since it's a public dependency.

**Trade-off:** Adding `license = "MIT"` to three files is trivial. No reason to defer.

### Risk 6: Git History Is Clean but Irrevocable

The git history audit found no secrets, but once the repo is public, the full history is permanently exposed. If any sensitive data was in branches that were later deleted, it would not appear in the current branch-based check. A more thorough audit would use tools like `trufflehog` or `gitleaks` to scan all objects in the packfile.

**Trade-off:** Running `trufflehog` against the repo takes minutes and provides higher confidence. Recommended before making the repo public.

### Risk 7: Modal Vendor Lock-in Visibility

The entire deployment stack (server, cron, crawler, eval) is Modal-specific. The OSS release makes this dependency very visible. Contributors who prefer other platforms have no alternative deployment path.

**Trade-off:** Abstracting away Modal is a major architectural effort and not worth doing before release. However, documenting it as a known limitation and outlining a "bring your own compute" path would help manage expectations.

### Edge Case: Trusted Orgs List

The `TRUSTED_ORGS` frozenset in `discovery.py` is a curated list of ~40 major AI/tech organizations. This is not company-specific data, but it is an editorial decision baked into the code. OSS contributors may disagree with the list or want to customize it.

**Trade-off:** Moving to a configuration file adds complexity. Keeping it in code is fine for now with a comment explaining it can be overridden.

---

## OPEN QUESTIONS — Uncertainties requiring verification

### Q1: Should `trufflehog` or `gitleaks` be run before release?

The git history audit was done via `git log` filters, which only catches files committed to current branches. A dedicated secret scanner would scan all git objects including deleted branches and force-pushed commits. **Recommendation: run one of these tools before making the repo public.**

### Q2: Is the copyright holder correct?

The LICENSE says "Copyright (c) 2025 Luca Fiaschi <luca.fiaschi@pymc-labs.com>". Should this be "PyMC Labs" or "PyMC Labs and contributors"? The individual copyright may be correct if Luca is the sole original author, but if others contributed under PyMC Labs employment, the copyright should reflect that.

### Q3: Should the Terms of Service / Privacy Policy pages be included?

These pages reference PyMC Labs as the service operator and contain specific legal terms. For an OSS release of the *code*, these are templates. But if someone deploys a fork, they inherit PyMC Labs' legal terms by default, which is incorrect. Should these be stripped, templated, or left as-is with a notice?

### Q4: Are there any trademark concerns?

"Decision Hub" as a product name — has it been trademarked? If so, can forks use the same name? The MIT license allows code reuse but doesn't grant trademark rights. Consider adding a trademark notice to the README. (Also raised by Agent A.)

### Q5: Does Modal's edge infrastructure provide auth endpoint rate limiting?

The auth rate-limit finding assumes no external protection. If Modal's proxy layer already throttles per-IP request rates, the urgency is lower. **Verify with Modal's documentation or support.**

### Q6: What is the plan for the existing PyPI packages?

`dhub-cli` and `dhub-core` are already published to PyPI under specific maintainer accounts. Will OSS contributors be able to publish releases, or will this remain centrally controlled? This affects the trust model and should be documented.

### Q7: Will GitHub Actions workflows work for forks?

The CI workflows reference GitHub Environments (`dev`) with specific secrets. Forks will need to set up their own environments. The `deploy-dev.yml` workflow will fail silently for forks without proper configuration. Should there be a "fork setup" guide?

### Q8: Is a formal dependency license attestation required?

Agent C raised this: "deeper legal/compliance validation (e.g., full transitive license attestation) may still be required by legal counsel." The current audit checked direct dependencies but did not perform a full transitive license scan.

---

## DISAGREEMENTS — Remaining substantive disagreements with other approaches

### 1. Frontend `.env.example` as BLOCKER (Agent C) — I disagree

Agent C classified the personal Modal URL in `frontend/.env.example` as a release BLOCKER. I maintain this is IMPORTANT at most. A `.env.example` is a template file that users are expected to copy and edit before use. The file literally begins with a comment explaining it's a configuration template. The **real** blockers are the compiled defaults in the CLI's `config.py` (which every `pip install` user gets) and the Modal custom domains in `modal_app.py` (which prevent deployment). These are the files that actually break third-party use without source modification.

### 2. Scope narrowness (Agents A and C) — I maintain broader coverage is warranted

Both Agent A and Agent C produced 6 issues each. This audit produces 19. Agent C's critique noted my "volume may overwhelm maintainers," but I disagree that fewer findings is better if the missed findings are real. The round 01 revision improved signal-to-noise by sharpening classifications (branding distinction, severity corrections) rather than dropping valid findings. Missing license declarations, internal planning docs, auth rate limits, and SEO domains are all real issues that a 6-issue audit misses.

### 3. Branding removal as a category (Agent C) — Nuanced agreement

Agent C correctly argued that "branding references are acceptable; hardcoded infra behavior that prevents deploy is the blocker." I fully adopted this distinction in round 01. However, I still flag **cosmetic coupling** (Category C in the revised pymc-labs issue) as a CRITICAL-tier concern because it makes forks feel second-class. This isn't branding — it's example code that says `dhub install pymc-labs/pymc-modeling` in the How It Works page, which is confusing for users of a fork that has nothing to do with PyMC Labs.

### 4. No remaining factual disagreements

All three agents' factual claims have been verified or corrected. The auth rate-limit gap (Agent C) is confirmed. The Modal domain blocker (Agents A and B) is confirmed. The license declaration gap (Agent B) is confirmed. The personal email issue (Agent A) is confirmed.
