# Internal Documentation & Sensitive Info Committed

## Description
The repository contains internal documentation that should not be part of a public release:
- `PRD.md`: Internal Product Requirements Document.
- `tasks.md`: Internal task tracking.
- `CLAUDE.md` / `AGENTS.md`: Contains internal operational details, including Modal secret names (`decision-hub-secrets-dev`), GitHub App IDs, and deployment workflows specific to PyMC Labs.

## Impact
**BLOCKER**. 
1. `PRD.md` and `tasks.md` expose internal strategy and unpolished notes.
2. `CLAUDE.md` exposes infrastructure details that reduce the reconnaissance effort for attackers targeting the PyMC Labs deployment.

## Recommendation
- Remove `PRD.md` and `tasks.md` from the repo.
- Sanitize `CLAUDE.md` to remove specific secret names and IDs, or move it to a git-ignored location (`.cursor/rules`) if it's only for internal dev use.
