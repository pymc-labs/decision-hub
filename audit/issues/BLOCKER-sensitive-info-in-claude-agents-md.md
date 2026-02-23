# BLOCKER: Sensitive Internal Information in CLAUDE.md and AGENTS.md

## Summary

`CLAUDE.md` and `AGENTS.md` contain specific infrastructure identifiers,
internal deployment procedures, and operational details that should not be
public. These files are loaded as AI agent instructions and will be immediately
visible to anyone who clones the repo.

## Sensitive Content

### GitHub App IDs and Installation IDs

```
Dev: App ID 2887189, Installation ID 111380021
Prod: App ID 2887208, Installation ID 111379955
```

While not secrets themselves, these allow targeting the project's GitHub Apps
for abuse (e.g., flooding webhook events, social engineering GitHub support).

### Modal Secret Names

```
decision-hub-db-dev, decision-hub-secrets-dev, decision-hub-aws-dev
decision-hub-github-app-dev, decision-hub-github-app
```

Knowing the exact Modal secret names helps an attacker who gains partial access
to the Modal workspace.

### Internal Deployment Details

- GitHub Environment names and secret keys
- Specific deploy workflows and environment variables
- PEM file naming conventions and paths
- Internal troubleshooting procedures with specific app names

### Personal Identifiers

- `@lfiaschi` username in CODEOWNERS and documentation
- Internal email addresses

## Affected Files

- `/workspace/CLAUDE.md` (~450 lines)
- `/workspace/AGENTS.md` (duplicates CLAUDE.md content)

## Why This Is a Blocker

These files are the first thing any developer (or AI agent) will read.
Publishing them exposes the full operational topology of the production
deployment, making targeted attacks easier.

## Recommended Fix

**Sanitize, don't delete.** CLAUDE.md contains valuable content (code
standards, design principles, testing conventions) alongside the sensitive
operational details. The right approach is:

1. **Strip operational identifiers** — remove GitHub App IDs, Installation IDs,
   Modal secret names, PEM file paths, and troubleshooting commands that
   reference specific infrastructure
2. **Keep development guidelines** — code standards, design principles, testing
   conventions, logging patterns, and contribution workflow are valuable for
   OSS contributors
3. **Delete `AGENTS.md`** — it's a duplicate of CLAUDE.md content
4. **Move stripped operational details** to a private runbook (separate repo,
   wiki, or git-ignored file) for maintainers only

This preserves the AI-assisted development experience while removing the
reconnaissance risk.
