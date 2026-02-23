## RISKS — Known risks, edge cases, trade-offs.

-   **Fork Tax / Vendor Lock-in**: The project is tightly coupled to PyMC Labs' infrastructure (Modal, internal URLs). Even after fixing blockers, the "Fork Tax" (effort to run an independent instance) remains high due to 50+ branding references.
    *   *Trade-off*: We prioritize unblocking deployment (fixing `modal_app.py`) over full rebranding (removing `pymc-labs` strings), accepting that early adopters will see PyMC branding.
-   **Security Disclosure Gap**: Launching without `SECURITY.md` guarantees that the first vulnerability found will be public.
    *   *Trade-off*: Writing a policy takes 15 minutes; the risk of not doing it is disproportionately high.
-   **Internal Operational Exposure**: `CLAUDE.md` and `AGENTS.md` contain runbooks that, while not strictly containing secrets (keys), map out the internal infrastructure for attackers.
    *   *Trade-off*: Sanitizing these files degrades the AI-assisted dev experience but protects operational security. A `sanitized` version should be committed.
-   **Legal ambiguity**: Missing license metadata in sub-packages creates friction for automated compliance tools.
    *   *Trade-off*: Trivial fix with high impact for enterprise adoption.

## OPEN QUESTIONS — Uncertainties requiring verification.

-   **Trademark Status**: Is "Decision Hub" trademarked? If so, guidelines for forks need to be explicit.
-   **JWT Rotation**: Verify if `JWT_SECRET` rotation policy is documented for self-hosters.
-   **`cisco-ai-skill-scanner`**: Confirm the maintenance status and long-term viability of this dependency.

## DISAGREEMENTS — Any remaining substantive disagreements.

-   **None.** I have aligned with Agent C regarding the `SECURITY.md` blocker classification and Auth Rate Limits, and with Agent B regarding the Licensing/Internal Docs findings. The resulting plan is a superset of all valid findings.
