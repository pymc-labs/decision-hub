# CRITICAL: Public auth endpoints are not rate-limited

## Category

Urgent issue (can be deferred only with explicit temporary controls)

## Summary

The public GitHub device-flow auth endpoints do not appear to use rate-limiting dependencies:

- `POST /auth/github/code`
- `POST /auth/github/token`

## Evidence

- `server/src/decision_hub/api/auth_routes.py` defines both routes without any `_enforce_*_rate_limit` dependency.
- `server/src/decision_hub/settings.py` contains rate-limit settings for search/list/resolve/download/audit/scan, but no auth endpoint rate-limit settings.

## Impact

These endpoints can be abused for:

- API quota exhaustion against GitHub device-flow endpoints
- request amplification and noisy logs
- avoidable infrastructure cost and operational instability

## Why this is CRITICAL (not BLOCKER)

This is a high-priority abuse-resistance gap, but it can be temporarily mitigated outside the app (edge WAF/CDN/IP throttling) for a short window if release timing is fixed.

## Acceptable temporary defer conditions

Only defer if all are true:

1. Edge-level rate limits for `/auth/*` are active and verified.
2. Alerting exists for spikes in 4xx/5xx and auth route volume.
3. Follow-up fix is scheduled immediately (next patch release).

## Recommended fix

1. Add auth rate limiter dependencies in `auth_routes.py`.
2. Add corresponding settings in `settings.py` (`auth_code_rate_limit`, etc.).
3. Add tests for 429 behavior and limiter initialization.

