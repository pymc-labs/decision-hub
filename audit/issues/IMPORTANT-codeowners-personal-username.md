# IMPORTANT: CODEOWNERS Uses Personal Username

## Summary

The `CODEOWNERS` file references `@lfiaschi` as the sole code owner for
critical paths (migrations, CI workflows). This should be updated to a
team/org handle for the OSS release.

## Affected Files

- `.github/CODEOWNERS`

```
server/migrations/                              @lfiaschi
server/src/decision_hub/infra/database.py       @lfiaschi
.github/workflows/                              @lfiaschi
```

## Recommended Fix

Update to an org team handle (e.g., `@pymc-labs/decision-hub-maintainers`)
or add multiple maintainers.

## Deferral Rationale

CODEOWNERS still works with a personal handle. Can be updated as the
maintainer team grows.
