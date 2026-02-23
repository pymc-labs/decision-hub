## PLAN — Numbered key decisions with rationale.

1.  **Synthesize findings into a unified checklist**: Created `audit/oss-release-checklist.md` combining the structural strengths of Agent B (10 categories) with the specific findings of all agents. This ensures no gap is left unchecked.
2.  **Elevate `SECURITY.md` to Blocker**: Based on feedback from Agent C and B, the absence of a vulnerability reporting policy is a release blocker because public disclosure (via GitHub Issues) is the default alternative, which puts production at risk.
3.  **Classify "Hardcoded Infrastructure" as the top Blocker**: The combination of `modal_app.py` custom domains and `client/config.py` default URLs effectively makes the project unusable for anyone but PyMC Labs. This is the definition of a release blocker for OSS.
4.  **Flag Licensing Gaps**: Included the missing license declarations in sub-packages (found by Agent B) as a Blocker to ensure legal compliance for enterprise adopters.
5.  **Identify Internal Leakage**: Flagged `PRD.md`, `tasks.md`, and `CLAUDE.md` (sensitive operational details) for removal/sanitization.
6.  **Prioritize Auth Rate Limits**: Added the missing rate limits on `/auth` endpoints (found by Agent C) as a Critical issue to prevent abuse.

## CHANGES — Unified diff or precise change descriptions.

**Audit Checklist**:
-   Created `audit/oss-release-checklist.md` with explicit PASS/FAIL status for Legal, Security, Infrastructure, Documentation, and Code Quality.

**Blocker Issues**:
-   `audit/issues/BLOCKER-hardcoded-modal-domains.md`: `modal_app.py` custom domain prevents deployment.
-   `audit/issues/BLOCKER-hardcoded-api-urls-in-client.md`: `config.py` defaults to internal API.
-   `audit/issues/BLOCKER-missing-license-declarations.md`: Sub-packages missing license metadata.
-   `audit/issues/BLOCKER-internal-docs-committed.md`: `PRD.md`, `tasks.md`, `CLAUDE.md` must go.
-   `audit/issues/BLOCKER-missing-security-policy.md`: `SECURITY.md` required for responsible disclosure.

**Critical Issues**:
-   `audit/issues/CRITICAL-missing-auth-rate-limits.md`: Protect `/auth` endpoints.
-   `audit/issues/CRITICAL-hardcoded-seo-urls.md`: Frontend `decision.ai` links confuse forks.
-   `audit/issues/CRITICAL-branding-hardcoding.md`: `pymc-labs` references increase "Fork Tax".
-   `audit/issues/CRITICAL-missing-community-docs.md`: `CONTRIBUTING` / `CODE_OF_CONDUCT`.

**Important Issues**:
-   `audit/issues/IMPORTANT-personal-email-metadata.md`: Use org email.
-   `audit/issues/IMPORTANT-hardcoded-deploy-url-output.md`: Fix deploy script output.
-   `audit/issues/IMPORTANT-codeowners-personal-username.md`: Use GitHub Teams.
