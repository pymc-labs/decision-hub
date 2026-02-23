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

## OPEN QUESTIONS — Uncertainties requiring verification.

1. **Release contract:** Is this release positioned as “hosted product client + open code” or “fork/self-host first-class OSS”?  
   (This determines severity of several URL/domain coupling findings.)

2. **Auth protection posture:** Are `/auth/*` routes protected by upstream WAF/CDN rate limits today, and are those limits documented/tested?

3. **Package distribution scope:** Are `shared` and `server` packages intended for public publication/consumption, or only internal workspace use?

4. **Docs boundary decision:** Should `CLAUDE.md`, `PRD.md`, `tasks.md`, and `.claude/commands/*` remain public (sanitized) or move internal?

5. **Ownership policy:** Should package metadata use organization contact info rather than individual email for OSS governance consistency?

6. **Trademark/branding guidance:** Will the project publish explicit fork-branding/trademark guidance (to separate brand retention from runtime coupling)?

## DISAGREEMENTS — Any remaining substantive disagreements with the other approaches, or "None."

1. **`frontend/.env.example` severity:** I now classify this as `IMPORTANT`, not `BLOCKER`.  
   Rationale: template files are editable and lower-impact than shipped runtime defaults.

2. **Broad branding references as blockers:** I still disagree with blanket blocker treatment of all `pymc-labs`/`decision.ai` references.  
   Rationale: branding can be intentional; blocker status should be reserved for references that break deployability or misroute runtime behavior.

3. **Governance docs as immediate blockers:** I keep `CONTRIBUTING`/`CODE_OF_CONDUCT` as `IMPORTANT` (high-priority, short deferral possible), while `SECURITY.md` remains a blocker due to direct vulnerability disclosure risk.

