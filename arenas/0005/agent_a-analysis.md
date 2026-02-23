## RISKS — Known risks, edge cases, trade-offs.

-   **Execution Paralysis**: A 19-issue audit can be overwhelming.
    *   *Mitigation*: The "Day 0" list is short (6 items, ~3-4 hours). We must enforce this prioritization rigorously.
-   **Ambiguous Release Contract**: If the "Hosted vs Self-Hosted" question is ignored, we risk shipping a release that satisfies neither audience (too coupled for self-hosters, too open for a proprietary product).
    *   *Trade-off*: Default to "Self-Hosted First-Class" assumptions (stricter decoupling) to minimize technical debt.
-   **Security Process Gap**: Launching without automated dependency scanning is a risk.
    *   *Trade-off*: Accepted for Day 1 to ship; manual checks during the Week 1 "hardening" phase are the stopgap.
-   **Legal Compliance**: `dhub-core` license metadata is a binary blocker for enterprise adoption.
    *   *Trade-off*: Zero tolerance; must be fixed Day 0.

## OPEN QUESTIONS — Uncertainties requiring verification.

-   **Release Contract**: Is this "Hosted Product Client" or "Open Source Platform"?
-   **CORS Architecture**: Should CORS be enforced at the App Middleware layer or Edge Proxy layer? (From Agent C)
-   **CODEOWNERS Governance**: Is there a `maintainers` team ready to replace individual usernames? (From Agent C)
-   **Modal Edge Protection**: Does Modal provide undocumented rate limiting for Auth endpoints?
-   **Trademark**: "Decision Hub" status.
-   **Copyright Holder**: "PyMC Labs" vs "Luca Fiaschi".

## DISAGREEMENTS — Any remaining substantive disagreements.

-   **None.** I have fully aligned with Agent B's structural approach and comprehensive scope, and incorporated Agent C's specific governance/architectural questions. The consensus is strong across all three agents on the core blockers and the remediation strategy.
