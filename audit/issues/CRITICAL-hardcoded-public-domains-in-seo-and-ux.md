# CRITICAL: Hardcoded public domains in SEO and user-facing surfaces

## Category

Urgent issue (can be deferred briefly with clear fork guidance)

## Summary

Multiple user/SEO surfaces hardcode `hub.decision.ai` / `decisionhub.dev` / maintainer endpoints. Forks and self-hosted deployments will present canonical links and UX hints that point to someone else's domain.

## Evidence

- `frontend/src/hooks/useSEO.ts:4` sets `BASE_URL = "https://hub.decision.ai"`.
- `frontend/index.html` canonical and OG URL are hardcoded to `https://hub.decision.ai/`.
- `server/src/decision_hub/api/seo_routes.py` hardcodes `_BASE_URL = "https://decisionhub.dev"` and prod hosts.
- `client/src/dhub/cli/config.py:176` upgrade message links to `https://hub.decision.ai`.
- `scripts/deploy.sh` prints hardcoded `pymc-labs--api...modal.run` URLs.

## Impact

- Incorrect canonical/OG tags for forks (SEO and trust issues).
- User confusion from links pointing to maintainer-hosted services.
- Poor white-label/self-host experience.

## Why this is CRITICAL (not BLOCKER)

Deploy/runtime functionality can still work after core blockers are fixed, but leaving this unresolved creates immediate operational confusion and branding/domain leakage for external adopters.

## Acceptable temporary defer conditions

Only defer if:

1. Release notes clearly state these are maintainer defaults.
2. Self-host docs include an explicit "rename/replace domains" checklist.
3. A short-term patch milestone is committed.

## Recommended fix

1. Move public URL/canonical host settings to configuration.
2. Use deployment-time variables for frontend and SEO routes.
3. Remove maintainer-specific URLs from generic deployment script output.

