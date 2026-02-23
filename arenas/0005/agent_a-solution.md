## PLAN — Numbered key decisions with rationale.

1.  **Checklist Creation**: Created a comprehensive `audit/oss-release-checklist.md` covering Legal, Security, Documentation, Code Quality, Build/Release, and Product Specifics. This ensures a systematic review process.
2.  **Codebase Audit**: Scanned the codebase for hardcoded secrets, internal URLs, and configuration issues using `grep` and manual inspection of key files (`server/modal_app.py`, `client/src/dhub/cli/config.py`, scripts).
3.  **Issue Identification & Classification**: Identified 6 specific issues ranging from Blockers to Important.
    -   **Blocker**: Hardcoded Modal custom domains prevent deployment by others.
    -   **Critical**: Hardcoded default API URLs point to internal infrastructure.
    -   **Critical**: Hardcoded "decision.ai" URLs in frontend/CLI.
    -   **Important**: Missing standard community docs (CONTRIBUTING, CODE_OF_CONDUCT).
    -   **Important**: Personal email in metadata.
    -   **Important**: Hardcoded URL in deploy script output.
4.  **Documentation**: Documented each issue in `audit/issues/[CATEGORY]-[DESCRIPTION].md` to provide clear actionable feedback for the team.

## CHANGES — Unified diff or precise change descriptions.

Created the following files:

-   `audit/oss-release-checklist.md`: The master checklist used for the audit.
-   `audit/issues/BLOCKER-hardcoded-modal-domains.md`: Describes hardcoded domains in `server/modal_app.py`.
-   `audit/issues/CRITICAL-hardcoded-api-urls.md`: Describes hardcoded API URLs in `client/src/dhub/cli/config.py`.
-   `audit/issues/CRITICAL-hardcoded-decision-ai-urls.md`: Describes hardcoded `decision.ai` URLs in frontend/CLI.
-   `audit/issues/IMPORTANT-missing-community-docs.md`: Describes missing CONTRIBUTING/CODE_OF_CONDUCT files.
-   `audit/issues/IMPORTANT-personal-email-metadata.md`: Describes personal email usage in `pyproject.toml`.
-   `audit/issues/IMPORTANT-deploy-script-hardcoded-url.md`: Describes hardcoded URL in `scripts/deploy.sh`.
