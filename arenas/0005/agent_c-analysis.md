## RISKS — Known risks, edge cases, trade-offs.

1. **Blocker remediation is cross-cutting, not isolated.**  
   Fixing custom domains, CLI defaults, and package licensing touches deploy behavior, CLI onboarding, and packaging metadata; partial fixes can still leave release-breaking edges.

2. **Self-hosting expectations vs hosted-product defaults.**  
   Some hardcoded URLs may be intentional for first-party hosted UX. Releasing as OSS without a clear hosted-vs-self-host contract can create contradictory user expectations.

3. **Security maturity gap remains if CRITICALs are deferred.**  
   Deferring auth-route rate limits and dependency security automation is feasible only with explicit compensating controls; otherwise early abuse and vulnerability lag are likely.

4. **Internal-doc exposure is mostly reconnaissance risk, not direct compromise.**  
   No direct secret leaks were found, but operational/planning docs still reduce attacker effort and can cause contributor confusion.

5. **Legal/compliance risk depends on downstream consumer policy.**  
   Missing package-level license metadata may be tolerated by some users but blocks others (especially enterprise compliance tooling).

6. **Security hardening defaults vary by deployment architecture.**  
   Missing explicit CORS and HTTP security-header policy may be harmless in first-party same-origin setups but can produce avoidable failures or weak defaults for self-hosters.

7. **Governance bus-factor risk remains post-release.**  
   CODEOWNERS tied to one personal account can bottleneck changes in critical paths if availability changes.

8. **Runbook sanitization can drift over time.**  
   Even after initial cleanup, internal identifiers can reappear in docs unless there is a clear public-doc review policy.

9. **Execution overload remains possible with broader issue inventory.**  
   Adding valid lower-tier findings improves coverage but can still overwhelm teams unless phase gates are enforced strictly.

## OPEN QUESTIONS — Uncertainties requiring verification.

1. **Release contract:** Is this release positioned as “hosted product client + open code” or “fork/self-host first-class OSS”?  
   (This determines severity of several URL/domain coupling findings.)

2. **Auth protection posture:** Are `/auth/*` routes protected by upstream WAF/CDN rate limits today, and are those limits documented/tested?

3. **Package distribution scope:** Are `shared` and `server` packages intended for public publication/consumption, or only internal workspace use?

4. **Docs boundary decision:** Should `CLAUDE.md`, `PRD.md`, `tasks.md`, and `.claude/commands/*` remain public (sanitized) or move internal?

5. **Ownership policy:** Should package metadata use organization contact info rather than individual email for OSS governance consistency?

6. **Trademark/branding guidance:** Will the project publish explicit fork-branding/trademark guidance (to separate brand retention from runtime coupling)?

7. **Operational hardening source of truth:** Should CORS and security headers be enforced in app middleware, edge proxy templates, or both for OSS guidance?

8. **CODEOWNERS governance:** Is there a team alias ready for migration, and what review-policy transition is expected?

9. **Runbook publication controls:** What review step ensures future `CLAUDE.md`/`AGENTS.md` edits remain free of sensitive identifiers?

10. **Pre-release dependency scan owner:** Who signs off the one-time vulnerability audit result before the repo is made public?

## DISAGREEMENTS — Any remaining substantive disagreements with the other approaches, or "None."

1. **`frontend/.env.example` severity:** I now classify this as `IMPORTANT`, not `BLOCKER`.  
   Rationale: template files are editable and lower-impact than shipped runtime defaults.

2. **Broad branding references as blockers:** I still disagree with blanket blocker treatment of all `pymc-labs`/`decision.ai` references.  
   Rationale: branding can be intentional; blocker status should be reserved for references that break deployability or misroute runtime behavior.

3. **Governance docs as immediate blockers:** I keep `CONTRIBUTING`/`CODE_OF_CONDUCT` as `IMPORTANT` (high-priority, short deferral possible), while `SECURITY.md` remains a blocker due to direct vulnerability disclosure risk.

4. **Single-issue treatment for all internal docs:** I disagree with collapsing all internal docs into one remediation action.  
   Rationale: `CLAUDE.md`/`AGENTS.md` may warrant sanitization, while planning artifacts (`PRD.md`, `tasks.md`, `.claude/commands/*`) may be moved or rewritten; these paths should be tracked distinctly even if grouped under one theme.

5. **How far to expand the final release artifact:** I still disagree with treating maximal breadth as always superior without phase discipline.  
   Rationale: comprehensive findings are valuable, but go/no-go decisions should stay anchored to blockers and explicitly time-bounded criticals.

