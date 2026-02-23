# IMPORTANT: Internal ops/planning content is exposed in public contributor surface

## Category

Important issue (deferrable, but should be cleaned up soon)

## Summary

Public repository content currently mixes external contributor guidance with internal operational/planning artifacts:

- `README.md` points contributors to `CLAUDE.md` (internal-heavy runbook content),
- root-level `PRD.md` and `tasks.md` expose internal planning context,
- `.claude/commands/*` includes internal workflow scripts.

## Evidence

- `README.md` contributor section references `CLAUDE.md`.
- `CLAUDE.md` contains operational details such as:
  - GitHub App IDs and installation IDs
  - Modal secret naming conventions
  - infra troubleshooting runbooks and command sequences
- `PRD.md` and `tasks.md` are committed at repo root.
- `.claude/commands/` files are committed and include internal testing/deploy guidance.

## Impact

- Increases reconnaissance value for attackers.
- Blurs boundary between public contributor docs and internal operator playbooks.
- Raises maintenance burden as internal process docs evolve.

## Why this is IMPORTANT (not CRITICAL/BLOCKER)

No private keys are committed, so immediate exploitability is limited. This is still a docs-boundary problem that should be corrected to reduce exposure and confusion.

## Recommended fix

1. Split docs into:
   - public contributor guide (`CONTRIBUTING.md`),
   - internal operations runbook (private/internal location).
2. Remove/redact non-essential infrastructure identifiers from public-facing docs.
3. Move `PRD.md`, `tasks.md`, and `.claude/commands/*` to an internal/private location, or replace with sanitized public equivalents.

