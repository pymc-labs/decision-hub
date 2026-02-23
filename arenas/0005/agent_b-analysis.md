## RISKS — Known risks, edge cases, trade-offs

### Risk 1: Hardcoded Infrastructure Creates a "Fork Tax"

The most pervasive risk is the tight coupling between the codebase and PyMC Labs' infrastructure. The CLI defaults to `pymc-labs--api.modal.run`, Modal deployment claims `hub.decision.ai`, and the frontend references these domains in SEO metadata. A fork requires touching 20+ files across 4 packages before basic deployment works.

**Trade-off:** Fixing all infrastructure references before release is substantial work (estimated 2-3 days). The alternative is shipping with clear "self-hosting guide" documentation that lists every configuration point, accepting that the initial fork experience is rough.

### Risk 2: CLAUDE.md Exposure Is a Judgment Call

`CLAUDE.md` contains GitHub App IDs, Modal secret names, and internal deployment procedures. None of these are secrets per se — App IDs are visible in GitHub's UI, and secret names don't grant access. However, publishing the full operational runbook reduces the attacker's reconnaissance effort.

**Trade-off:** Removing `CLAUDE.md` entirely degrades the AI-assisted development experience for the project. Moving it to `.cursor/rules` (git-ignored) means forks lose the development guidelines. The middle ground is a sanitized version that strips infrastructure identifiers while keeping code standards.

### Risk 3: Missing SECURITY.md Creates Liability

Without a security disclosure policy, the first vulnerability discovered by an external researcher will likely be disclosed publicly (as a GitHub issue). This could expose the production deployment before a fix is available.

**Trade-off:** A basic `SECURITY.md` takes 15 minutes to write. This should not be deferred.

### Risk 4: License Ambiguity for Enterprise Adopters

While the root LICENSE file is MIT, three sub-packages lack license metadata. Enterprise license compliance tools (FOSSA, Snyk, etc.) flag packages without declared licenses. The `dhub-core` package on PyPI is the most concerning since it's a public dependency.

**Trade-off:** Adding `license = "MIT"` to three files is trivial. No reason to defer.

### Risk 5: Git History Is Clean but Irrevocable

The git history audit found no secrets, but once the repo is public, the full history is permanently exposed. If any sensitive data was in branches that were later deleted, it would not appear in the current history check. A more thorough audit would use tools like `trufflehog` or `gitleaks` to scan all objects in the packfile.

**Trade-off:** Running `trufflehog` against the repo takes minutes and provides higher confidence. Recommended before making the repo public.

### Risk 6: PyMC Labs Branding May Be Intentional

The 50+ `pymc-labs` references in the frontend may be intentional if PyMC Labs wants to maintain brand presence as the primary maintainer/operator. Stripping all references creates a generic-looking project that doesn't acknowledge its origin.

**Trade-off:** A clear distinction should be made between "this project is maintained by PyMC Labs" (appropriate) and "this project only works with PyMC Labs infrastructure" (inappropriate for OSS). The former should stay; the latter must go.

### Risk 7: Modal Vendor Lock-in Visibility

The entire deployment stack (server, cron, crawler, eval) is Modal-specific. The OSS release makes this dependency very visible. Contributors who prefer other platforms (AWS Lambda, GCP Cloud Run, Railway) have no alternative deployment path.

**Trade-off:** Abstracting away Modal is a major architectural effort and not worth doing before release. However, documenting it as a known limitation and outlining a "bring your own compute" path would help manage expectations.

### Edge Case: Trusted Orgs List

The `TRUSTED_ORGS` frozenset in `discovery.py` is a curated list of ~40 major AI/tech organizations. This is not company-specific data, but it is an editorial decision baked into the code. OSS contributors may disagree with the list or want to customize it.

**Trade-off:** Moving to a configuration file or database table adds complexity. Keeping it in code is fine for now with a comment explaining it can be overridden.

---

## OPEN QUESTIONS — Uncertainties requiring verification

### Q1: Should `trufflehog` or `gitleaks` be run before release?

The git history audit was done via `git log` filters, which only catches files committed to current branches. A dedicated secret scanner (`trufflehog`, `gitleaks`) would scan all git objects including deleted branches and force-pushed commits. **Recommendation: run one of these tools before making the repo public.**

### Q2: Is the copyright holder correct?

The LICENSE says "Copyright (c) 2025 Luca Fiaschi <luca.fiaschi@pymc-labs.com>". Should this be "PyMC Labs" or "PyMC Labs and contributors"? The individual copyright may be correct if Luca is the sole original author, but if others contributed under PyMC Labs employment, the copyright should reflect that.

### Q3: Should the Terms of Service / Privacy Policy pages be included?

These pages reference PyMC Labs as the service operator and contain specific legal terms. For an OSS release of the *code*, these are templates. But if someone deploys a fork, they inherit PyMC Labs' legal terms by default, which is incorrect. Should these be stripped, templated, or left as-is with a notice?

### Q4: What about the `REQUIRE_GITHUB_ORG` restriction?

The server settings include `require_github_org` which can restrict login to members of a specific GitHub org. This is commented out in `.env.example` with `pymc-labs` as the example. Should the default behavior for a fresh deployment be open to all GitHub users (current default: yes, if the var is empty)?

### Q5: Are there any trademark concerns?

"Decision Hub" as a product name — has it been trademarked? If so, can forks use the same name? The MIT license allows code reuse but doesn't grant trademark rights. Consider adding a trademark notice to the README.

### Q6: Should the `.cursor/` and `.claude/` directories be git-ignored?

These contain AI agent configuration that's useful for contributors but also contains internal references. The `.cursor/rules` pattern is standard for Cursor IDE. The question is whether AI agent configs are "project infrastructure" (should be tracked) or "personal tooling" (should be ignored).

### Q7: What is the plan for the existing PyPI packages?

`dhub-cli` and `dhub-core` are already published to PyPI under specific maintainer accounts. Will OSS contributors be able to publish releases, or will this remain centrally controlled? This affects the trust model and should be documented.

### Q8: Should Modal deployment details be documented for self-hosters?

Currently there is no self-hosting guide. The deployment is entirely Modal-dependent. Should the OSS release include:
- A step-by-step Modal deployment guide?
- A Docker Compose alternative for local development?
- Documentation of all required environment variables and secrets?

### Q9: Will GitHub Actions workflows work for forks?

The CI workflows reference GitHub Environments (`dev`) with specific secrets. Forks will need to set up their own environments. The `deploy-dev.yml` workflow will fail silently for forks without proper configuration. Should there be a "fork setup" guide?

### Q10: Is the `jszip` dual license (MIT OR GPL-3.0) documented?

The `jszip` dependency offers a choice between MIT and GPL. While users can choose MIT (no copyleft obligation), this should be explicitly documented in a NOTICE or LICENSE-THIRD-PARTY file to avoid confusion.
