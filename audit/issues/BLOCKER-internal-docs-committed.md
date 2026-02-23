# BLOCKER: Internal Planning Documents Committed to Repository

## Summary

Several internal planning and task-tracking documents are committed to the
repository and would be publicly visible upon OSS release. These documents
expose internal product strategy and development priorities.

## Affected Files

- `PRD.md` — Full product requirements document with internal roadmap,
  sprint plans, and strategic priorities
- `tasks.md` — Active task tracking with completed/pending items
- `docs/skill-scanner-integration-analysis.md` — Internal technical analysis

## Why This Is a Blocker

- `PRD.md` exposes product strategy and prioritization decisions that may
  be competitively sensitive
- `tasks.md` reveals current development priorities and technical debt
- These create noise for external contributors who may confuse internal
  planning docs with contributor documentation

## Recommended Fix

1. Remove `PRD.md` from the repository (move to internal wiki/Notion)
2. Remove `tasks.md` from the repository
3. Review `docs/skill-scanner-integration-analysis.md` and either remove or
   ensure it contains only technical content appropriate for public consumption
4. Add these patterns to `.gitignore` to prevent re-addition:
   ```
   PRD.md
   tasks.md
   ```

## Impact

- Competitive intelligence exposure
- Contributor confusion (which docs are authoritative?)
- Cluttered repository root
