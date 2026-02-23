## PLAN — Numbered key decisions with rationale.

1.  **Finalize the Audit Artifact**: I will adopt Agent B's comprehensive 19-issue scope as the final audit plan. This approach has proven robust through three rounds of critique, incorporating every valid finding from all agents while structuring them into an actionable "Day 0 / Week 1" execution plan.
2.  **Strategic Framing**: I will retain the "Release Contract" question (Hosted Product vs. Self-Hosted OSS) at the very top of the checklist. This is the single most important strategic decision for the release, as it dictates the severity of ~40% of the findings.
3.  **Remediation Sequencing**: I will explicitly include the "Prioritized Remediation Sequence" table (Day 0 / Week 1 / Post-Release) with effort estimates. This directly addresses the "analysis paralysis" concern by providing a clear critical path.
4.  **Refined Sanitize-Not-Delete**: I will maintain the specific instruction to *sanitize* `CLAUDE.md` (remove App IDs, Installation IDs, Modal secrets) rather than delete it. This preserves developer velocity while mitigating reconnaissance risk.
5.  **Blocker Definition**: I affirm the consensus blocker set:
    *   Missing `SECURITY.md` (Disclosure path)
    *   Hardcoded Modal Domains (Deployability)
    *   Hardcoded CLI Defaults (Runtime routing)
    *   Missing License Metadata (Legal clarity)
    *   Unsanitized Internal Docs (Reconnaissance risk)
6.  **Open Questions**: I will expand the Open Questions section to include Agent C's specific additions regarding CORS enforcement architecture and CODEOWNERS governance, ensuring the post-release roadmap is clear.

## CHANGES — Unified diff or precise change descriptions.

**Audit Checklist (`audit/oss-release-checklist.md`)**:
-   **Structure**: Retained the "Day 0 / Week 1 / Post-Release" remediation table.
-   **Content**: Full 19-issue inventory with PASS/FAIL status.
-   **Strategic Prompt**: "Release Contract" question remains at the top.

**Blocker Issues**:
-   `BLOCKER-hardcoded-modal-domains.md`: Unchanged.
-   `BLOCKER-hardcoded-api-urls-in-client.md`: Unchanged.
-   `BLOCKER-missing-license-declarations.md`: Confirmed text specifies `server` and `shared` only.
-   `BLOCKER-internal-docs-committed.md`: Explicit "Sanitize CLAUDE.md" instruction.
-   `BLOCKER-missing-security-policy.md`: Unchanged.

**Critical Issues**:
-   `CRITICAL-auth-endpoints-missing-rate-limits.md`: Unchanged.
-   `CRITICAL-branding-hardcoding.md`: Retained 3-category framework (Keep/Block/Cosmetic).
-   `CRITICAL-hardcoded-seo-urls.md`: Unchanged.
-   `CRITICAL-modal-secret-names-hardcoded.md`: Unchanged.
-   `CRITICAL-missing-community-docs.md`: Unchanged.

**Important Issues**:
-   Full set of 8 important issues (CORS, Headers, Dependencies, etc.) retained as "Post-Release" tasks.
