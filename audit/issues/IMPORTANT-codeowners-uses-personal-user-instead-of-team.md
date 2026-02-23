# IMPORTANT: CODEOWNERS uses a personal username rather than a team alias

## Category

Important issue (governance resilience; deferrable)

## Summary

`CODEOWNERS` currently assigns critical paths to a single personal account (`@lfiaschi`). This is workable short-term but fragile for OSS governance continuity.

## Evidence

- `.github/CODEOWNERS` entries:
  - `server/migrations/ ... @lfiaschi`
  - `server/src/decision_hub/infra/database.py ... @lfiaschi`
  - `.github/workflows/ ... @lfiaschi`

## Impact

- Review bottlenecks and potential ownership gaps if availability changes.
- Reduced bus-factor for high-risk paths (migrations, CI).
- Harder contributor trust in long-term maintainership model.

## Why this is IMPORTANT (not CRITICAL/BLOCKER)

Does not directly break runtime/security on release day, but it is a meaningful governance risk that becomes more visible after OSS launch.

## Recommended fix

1. Introduce a GitHub team alias for critical ownership paths.
2. Use team + individual fallback if needed during transition.
3. Document maintainer/review ownership policy in CONTRIBUTING.

