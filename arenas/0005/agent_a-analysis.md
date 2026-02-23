## RISKS — Known risks, edge cases, trade-offs.

-   **Deployment Failure Risk**: The hardcoded custom domains in `modal_app.py` pose a significant risk that any third-party deployment will fail immediately. This is the highest priority fix.
-   **User Experience Risk**: If the CLI defaults to the internal PyMC Labs API, new users might inadvertently try to authenticate against a private instance or get confusing errors. This degrades the "out of the box" experience.
-   **Community Health Risk**: Launching without `CONTRIBUTING.md` or `CODE_OF_CONDUCT.md` can lead to a chaotic initial contribution period and signals a lack of readiness for external collaboration.
-   **Security Perception**: While no live credentials were found, the presence of `CLAUDE.md` referencing internal secrets and deployment workflows might confuse security auditors or users about what is required to run the stack.

## OPEN QUESTIONS — Uncertainties requiring verification.

-   **`cisco-ai-skill-scanner` Dependency**: Verified as a public package, but its maintenance status and compatibility with the project's long-term goals should be monitored.
-   **Trademark / Branding**: Are "Decision Hub" and the logo trademarked? If so, guidelines on their usage in forks should be added.
-   **Internal `CLAUDE.md`**: Should this file be included in the release, or is it purely for internal AI agents? If it contains sensitive workflow descriptions (even if not secrets), it might be better to exclude or sanitize it.
-   **Auth0 / JWT Secret**: The project uses a `JWT_SECRET`. It is correctly loaded from env vars, but we should double-check that the production environment rotation policy is documented for self-hosters.
