# BLOCKER: Internal Planning Documents Committed to Repository

**Tracking:** [#178](https://github.com/pymc-labs/decision-hub/issues/178) (combined with AGENTS.md sanitization)

## Summary

Several internal planning and task-tracking documents are committed to the
repository and would be publicly visible upon OSS release. These documents
expose internal product strategy and development priorities.

## Affected Files

- `PRD.md` — Full product requirements document with internal roadmap,
  sprint plans, and strategic priorities
- `tasks.md` — Active task tracking with completed/pending items
- `docs/skill-scanner-integration-analysis.md` — Internal technical analysis

## Recommended Fix

1. Remove `PRD.md` and `tasks.md` from the repository
2. Review `docs/skill-scanner-integration-analysis.md` and either remove or
   ensure it contains only technical content appropriate for public consumption
3. Add these patterns to `.gitignore` to prevent re-addition
4. If git history rewrite is chosen (see #178), include these files in the
   `git filter-repo` pass
