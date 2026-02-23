# IMPORTANT: CORS policy is not explicitly configured

## Category

Important issue (deferrable, but should be clarified for OSS self-hosting)

## Summary

The FastAPI app does not explicitly configure CORS middleware. This is fine for same-origin deployments, but OSS adopters commonly run split-origin setups (frontend and API on different hosts), where implicit CORS behavior causes avoidable integration failures.

## Evidence

- No `CORSMiddleware` usage found under `server/src/decision_hub`.
- App factory (`server/src/decision_hub/api/app.py`) sets routers and middleware for logging/CLI version only.

## Impact

- Self-hosters may hit browser CORS failures in common deployment topologies.
- Increased support burden from "API works in curl but fails in browser" reports.
- Security posture ambiguity if CORS is handled ad hoc at proxies.

## Why this is IMPORTANT (not CRITICAL/BLOCKER)

This does not break first-party same-origin runtime and can be mitigated at reverse-proxy level, but explicit policy in docs/app config reduces onboarding friction significantly.

## Recommended fix

1. Document supported CORS topologies (same-origin vs split-origin).
2. Add explicit CORS config knobs (allowed origins, methods, credentials) or document required proxy config.
3. Add at least one integration test or docs validation for split-origin mode.

