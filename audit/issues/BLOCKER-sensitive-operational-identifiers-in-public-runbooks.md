# BLOCKER: Sensitive operational identifiers exposed in public runbooks

## Category

OSS release blocker

## Summary

Publicly tracked operator/runbook docs include production-relevant infrastructure identifiers and secret naming conventions that materially reduce attacker reconnaissance cost:

- GitHub App IDs and Installation IDs,
- Modal secret names and recreation command patterns,
- direct operational troubleshooting/runbook context.

## Evidence

- `CLAUDE.md` includes:
  - GitHub App IDs / installation IDs (dev + prod),
  - `modal secret create ...` command patterns and secret names.
- `AGENTS.md` includes equivalent operational details (same IDs/secret patterns).

## Why this blocks OSS release

The first public commit should not ship consolidated infrastructure identifiers tied to live systems in a single, easy-to-scrape runbook. This is not just generic contributor guidance; it materially increases targeting precision.

## Risk if released as-is

- Lower-cost reconnaissance against live infrastructure.
- Higher blast radius when combined with other partial disclosures.
- Harder incident response posture if identifiers are broadly mirrored.

## Required remediation before release

1. Sanitize `CLAUDE.md` and `AGENTS.md`:
   - remove app IDs / installation IDs,
   - remove explicit secret names and recreation commands,
   - keep non-sensitive engineering standards and workflows.
2. Move sensitive operator procedures to private/internal documentation.
3. Add a public-safe contributor path (`CONTRIBUTING.md`) so useful guidance remains available.

