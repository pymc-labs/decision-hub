## RISKS — Known risks, edge cases, trade-offs.

-   **"Fork Tax" Reality**: Even with blockers fixed, the "Cosmetic" branding coupling (Category C) means forks will essentially look like PyMC Labs products until a deep scrub is performed.
    *   *Trade-off*: We accept this to get the release out, prioritizing *functional* independence (Category B) over *brand* independence.
-   **Security Process Gap**: Launching with a `SECURITY.md` is a good first step, but without an automated dependency auditor (flagged as Important), we rely on manual checks for supply chain attacks.
    *   *Trade-off*: Acceptable for Day 1; automated scanning should be a fast-follow.
-   **Operational Exposure via `CLAUDE.md`**: Sanitizing this file reduces risk but doesn't eliminate it. The operational patterns revealed could still aid an attacker.
    *   *Trade-off*: The dev velocity benefit for contributors outweighs the residual reconnaissance risk after App IDs are removed.
-   **Legal Compliance**: The missing license metadata in `dhub-core` (shared) is the highest legal risk since it's a library dependency. Fixing this is a zero-downside blocker.

## OPEN QUESTIONS — Uncertainties requiring verification.

-   **Release Contract**: Is this "PyMC Labs Product Source" or "Community Project"? The answer dictates whether Category C branding issues should be elevated to Blockers later.
-   **Trademark**: "Decision Hub" trademark status needs verification.
-   **Modal Edge Protection**: Does Modal provide undocumented rate limiting that might mitigate the Auth endpoint risk?
-   **Copyright Holder**: Should it be "PyMC Labs" or "Luca Fiaschi"? Legal needs to clarify based on employment status/IP assignment.

## DISAGREEMENTS — Any remaining substantive disagreements.

-   **None.** I have fully aligned with Agent B's comprehensive scope and risk analysis, and incorporated Agent C's specific security finding (Auth Rate Limits). The slight difference in `frontend/.env.example` classification (Important vs Non-issue) is negligible.
