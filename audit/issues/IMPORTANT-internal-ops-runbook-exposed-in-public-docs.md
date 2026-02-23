# IMPORTANT: Internal planning and ad-hoc command artifacts are public

## Category

Important issue (deferrable, but should be cleaned up soon)

## Summary

Public repository content includes internal planning and ad-hoc command artifacts that are low-value for external contributors:

- root-level `PRD.md` and `tasks.md` expose internal planning context,
- `.claude/commands/*` includes internal workflow scripts.

## Evidence

- `PRD.md` and `tasks.md` are committed at repo root.
- `.claude/commands/` files are committed and include internal testing/deploy guidance.

## Impact

- Exposes internal planning noise in public OSS surface.
- Blurs boundary between stable contributor docs and internal scratch workflows.
- Raises maintenance burden as internal process docs evolve.

## Why this is IMPORTANT (not CRITICAL/BLOCKER)

These files are mostly governance/usability debt rather than direct exploit vectors, so they are important but deferrable after blocker cleanup.

## Recommended fix

1. Split docs into:
   - public contributor guide (`CONTRIBUTING.md`),
   - internal operations runbook (private/internal location).
2. Move `PRD.md`, `tasks.md`, and `.claude/commands/*` to an internal/private location, or replace with sanitized public equivalents.
3. Keep stable, public-safe contributor guidance in dedicated docs instead of operational scratch files.

