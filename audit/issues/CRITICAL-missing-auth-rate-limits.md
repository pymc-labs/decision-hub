# Missing Rate Limits on Auth Endpoints

## Description
The authentication endpoints in `server/src/decision_hub/api/auth_routes.py` (`/auth/github/code` and `/auth/github/token`) do not appear to have the `_enforce_*_rate_limit` dependencies applied to them, unlike other public endpoints.

## Impact
**CRITICAL**. These endpoints are public and trigger downstream calls to GitHub. They could be abused for:
- Denial of Service (DoS) against the application.
- Exhausting the application's GitHub API rate limits.
- Brute-force attempts (though mitigated by GitHub's own protections, defense-in-depth is required).

## Recommendation
Apply a strict rate limiter (e.g., `10/minute`) to these endpoints using the existing rate limit infrastructure.
