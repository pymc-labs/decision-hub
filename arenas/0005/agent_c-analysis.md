## RISKS — Known risks, edge cases, trade-offs.

1. **Repository-level audit only.**  
   Findings are based on code/docs/workflow review and targeted scans; this does not include full runtime penetration testing or production infrastructure validation.

2. **Issue tracker visibility limitations.**  
   Direct GitHub issue listing was blocked by repository integration permissions, so overlap with unpublished triage items may exist.

3. **Deferral trade-off for CRITICAL items.**  
   The two `CRITICAL` findings can be deferred only with explicit compensating controls (edge rate limiting/manual vuln reviews), but this increases short-term operational risk.

4. **Recon risk is contextual.**  
   The internal runbook exposure finding is important but context-dependent: no direct secrets were found, yet public operational details still increase attack surface for reconnaissance.

5. **Checklist completeness vs. implementation speed.**  
   This audit maximizes actionable release guidance quickly; deeper legal/compliance validation (e.g., full transitive license attestation) may still be required by legal counsel.

## OPEN QUESTIONS — Uncertainties requiring verification.

1. **Release policy decision:** Are `SECURITY.md` and neutral frontend env defaults mandatory gates for this release (recommended: yes)?

2. **Compensating controls status:** Is there confirmed edge/WAF rate limiting on `/auth/*` in current deployed environments?

3. **Security automation ownership:** Who owns adding Dependabot/security workflows, and what is the committed deadline?

4. **Public docs strategy:** Should `CLAUDE.md` remain publicly linked, or should contributor docs be split into public (`CONTRIBUTING`) and internal runbooks?

5. **Legal/compliance scope:** Is a formal third-party dependency license report required before release approval?

