# CRITICAL: Public Auth Endpoints Missing Rate Limits

## Summary

The public authentication endpoints `/auth/github/code` and
`/auth/github/token` have no rate-limiting dependencies, unlike all other
public endpoints which use per-IP sliding-window limiters.

## Evidence

- `server/src/decision_hub/api/auth_routes.py` — neither `start_device_flow`
  nor `exchange_token` has a rate-limit dependency
- `server/src/decision_hub/api/app.py:146` — `auth_router` included without
  rate-limit dependencies (contrast with other routers)
- `server/src/decision_hub/settings.py` — no `auth_rate_limit` /
  `auth_rate_window` settings defined

All other public endpoints have rate limiters:
- `/v1/search` → `_enforce_search_rate_limit`
- `/v1/skills` → `_enforce_list_skills_rate_limit`
- `/v1/resolve` → `_enforce_resolve_rate_limit`
- `/v1/skills/{...}/download` → `_enforce_download_rate_limit`

## Impact

- **Denial of Service:** An attacker can flood `/auth/github/code` to exhaust
  the project's GitHub OAuth API rate budget
- **Resource exhaustion:** `/auth/github/token` performs DB upserts, GitHub
  API calls, and JWT signing — all without throttling
- **Abuse amplification:** Once the repo is public, the endpoint URLs and
  `GITHUB_CLIENT_ID` are discoverable from the codebase

## Mitigating Factors

- GitHub's own device flow endpoints have rate limits, so the upstream
  GitHub API provides some protection
- Modal's infrastructure may have edge-level rate limiting
- Write operations require a valid `device_code` from a real GitHub flow

## Recommended Fix

Follow the existing rate-limit pattern:

1. Add settings in `settings.py`:
   ```python
   auth_rate_limit: int = 20
   auth_rate_window: int = 300
   ```

2. Add enforcement function in `auth_routes.py`:
   ```python
   def _enforce_auth_rate_limit(request: Request, settings: Settings = Depends(get_settings)):
       enforce_rate_limit(request, "auth", settings.auth_rate_limit, settings.auth_rate_window)
   ```

3. Wire via dependencies on the router or individual endpoints.

## Deferral Rationale

The mitigating factors (GitHub's upstream rate limits, Modal's edge protection)
reduce the immediate risk. This can be deferred briefly if the team commits to
deploying the fix within the first week post-release, but it should be
prioritized over other CRITICAL items.
