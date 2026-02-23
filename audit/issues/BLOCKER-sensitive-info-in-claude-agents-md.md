# BLOCKER: Sensitive Internal Information in AGENTS.md and CLAUDE.md

**Tracking:** [#178](https://github.com/pymc-labs/decision-hub/issues/178) (combined with internal docs removal)

## Summary

`AGENTS.md` and `CLAUDE.md` contain specific infrastructure identifiers,
internal deployment procedures, and operational details that should not be
public. These files are loaded as AI agent instructions and will be immediately
visible to anyone who clones the repo.

`AGENTS.md` is the canonical file (works in both Cursor and Claude Code).
`CLAUDE.md` should be deleted.

## Sensitive Content

### GitHub App IDs and Installation IDs

While not secrets themselves, these allow targeting the project's GitHub Apps
for abuse (e.g., flooding webhook events, social engineering GitHub support).

### Modal Secret Names

Knowing the exact Modal secret names helps an attacker who gains partial access
to the Modal workspace.

### Internal Deployment Details

- GitHub Environment names and secret keys
- Specific deploy workflows and environment variables
- PEM file naming conventions and paths
- Internal troubleshooting procedures with specific app names

## Recommended Fix

**Sanitize, don't delete.** `AGENTS.md` contains valuable content (code
standards, design principles, testing conventions) alongside the sensitive
operational details. The right approach is:

1. **Strip operational identifiers** from `AGENTS.md` — remove GitHub App IDs,
   Installation IDs, Modal secret names, PEM file paths, and troubleshooting
   commands that reference specific infrastructure
2. **Keep development guidelines** — code standards, design principles, testing
   conventions, logging patterns, and contribution workflow are valuable for
   OSS contributors
3. **Delete `CLAUDE.md`** — it duplicates `AGENTS.md` content
4. **Move stripped operational details** to a private runbook (separate repo,
   wiki, or git-ignored file) for maintainers only
5. **Decide on git history rewrite** — even after sanitizing HEAD, old versions
   with full operational details remain in git history. See #178 for tradeoff
   analysis.
