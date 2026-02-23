# IMPORTANT: Internal ops runbook content is exposed in public contributor surface

## Category

Important issue (deferrable, but should be cleaned up soon)

## Summary

The public contributor path points to `CLAUDE.md`, which includes detailed internal operational instructions and infrastructure identifiers (app IDs, installation IDs, secret naming conventions, and operational command patterns).

## Evidence

- `README.md` contributor section references `CLAUDE.md` for development guidance.
- `CLAUDE.md` contains operational details such as:
  - GitHub App IDs and installation IDs
  - Modal secret naming conventions
  - infra troubleshooting runbooks and command sequences

## Impact

- Increases reconnaissance value for potential attackers
- Mixes external contributor guidance with internal-only operational context
- Raises maintenance burden when internal operations change

## Why this is IMPORTANT (not CRITICAL/BLOCKER)

No private keys are committed, so immediate exploitability is limited. Still, this is a documentation-boundary problem that should be corrected to reduce avoidable exposure and confusion.

## Recommended fix

1. Split docs into:
   - public contributor guide (`CONTRIBUTING.md`),
   - internal operations runbook (private/internal location).
2. Remove or redact non-essential infrastructure identifiers from publicly linked docs.
3. Keep sensitive operational procedures in access-controlled documentation.

