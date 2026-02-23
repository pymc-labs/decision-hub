# IMPORTANT: Missing CONTRIBUTING and CODE_OF_CONDUCT

## Category

Important issue (safe to defer briefly after release)

## Summary

The repository does not include standard open-source governance docs:

- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`

## Evidence

- No `CONTRIBUTING.md` found at repo root.
- No `CODE_OF_CONDUCT.md` found at repo root.
- `README.md` currently points contributors to `CLAUDE.md`, which is primarily an internal operational/agent runbook.

## Impact

- Higher contributor friction (unclear contribution workflow)
- No published behavior/moderation baseline for community spaces
- Increased triage overhead for maintainers

## Why this is IMPORTANT (not CRITICAL/BLOCKER)

The project can technically release without these docs, but community operations and contribution quality will degrade quickly as adoption grows.

## Recommended fix

1. Add `CONTRIBUTING.md` with setup, branching, commit, test, and review expectations.
2. Add `CODE_OF_CONDUCT.md` (Contributor Covenant or equivalent).
3. Update README contributor section to reference these public docs first.

