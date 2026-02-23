## PLAN — Numbered key decisions with rationale.

1.  **Finalize the 19-issue audit scope**: I will adopt the comprehensive 19-issue scope from Agent B. The critiques confirm that volume is acceptable if structured well, and missing real issues (like CORS or dependency audits) is a worse outcome for a final audit.
2.  **Refine the "Branding vs Lock-in" Strategy**: I will explicitly adopt the three-tier classification for `pymc-labs` references:
    *   **Category A (Keep)**: Attribution/Legal.
    *   **Category B (Blocker)**: Runtime infrastructure lock-in (hardcoded URLs/Domains).
    *   **Category C (Cosmetic)**: Example commands/marketing text (Critical/Important but deferrable).
3.  **Elevate `SECURITY.md` to Blocker**: Consensus is clear that missing a vulnerability reporting channel is a release blocker.
4.  **License Metadata Correction**: I verified that `client` *does* have a license, but `server` and `shared` (dhub-core) do *not*. I will update the finding to reflect this precision.
5.  **Sanitization vs Removal**: For `CLAUDE.md`, I will recommend *sanitization* (removing App IDs/Secrets) rather than full removal, as the file contains useful dev context. `PRD.md` and `tasks.md` will remain "Remove".
6.  **Auth Rate Limits**: Confirmed as CRITICAL (deferrable with mitigating factors like GitHub's upstream limits, but urgent).

## CHANGES — Unified diff or precise change descriptions.

**Audit Checklist (`audit/oss-release-checklist.md`)**:
-   Updated to reflect the full 19-issue scope.
-   Refined status for License Metadata (Client PASS, Server/Shared FAIL).
-   Categorized issues by urgency (Blocker, Critical, Important).

**Blocker Issues**:
-   `BLOCKER-hardcoded-modal-domains.md` (Unchanged)
-   `BLOCKER-hardcoded-api-urls-in-client.md` (Unchanged)
-   `BLOCKER-missing-license-declarations.md`: Updated description to specify `server` and `shared` packages only.
-   `BLOCKER-internal-docs-committed.md`: Updated recommendation to "Sanitize CLAUDE.md, Remove PRD/tasks".
-   `BLOCKER-missing-security-policy.md` (Unchanged)

**Critical Issues**:
-   `CRITICAL-auth-endpoints-missing-rate-limits.md` (Unchanged)
-   `CRITICAL-branding-hardcoding.md`: Updated to use the 3-category framework (Keep/Block/Cosmetic).
-   `CRITICAL-hardcoded-seo-urls.md` (Unchanged)
-   `CRITICAL-modal-secret-names-hardcoded.md` (New from Agent B)
-   `CRITICAL-missing-community-docs.md`: Removed SECURITY.md reference (now its own blocker).

**Important Issues** (Adopted from Agent B to complete the set):
-   `IMPORTANT-missing-cors-configuration.md`
-   `IMPORTANT-print-statement-in-production.md`
-   `IMPORTANT-missing-security-headers.md`
-   `IMPORTANT-dependency-audit-needed.md`
-   `IMPORTANT-personal-modal-urls-in-examples.md`
-   `IMPORTANT-claude-directory-test-commands.md`
-   `IMPORTANT-codeowners-personal-username.md`
-   `IMPORTANT-personal-email-metadata.md`
