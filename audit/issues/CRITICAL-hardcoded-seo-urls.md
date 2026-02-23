# Hardcoded SEO and Branding URLs

## Description
There are multiple hardcoded references to `decision.ai` and `hub.decision.ai` in the frontend and documentation:
- `frontend/src/hooks/useSEO.ts`: `BASE_URL = "https://hub.decision.ai"`
- `frontend/index.html`: Canonical links and OG tags.
- `server/src/decision_hub/api/seo_routes.py`: `_PROD_HOSTS = {"hub.decision.ai", ...}`

## Impact
**CRITICAL**. Forks of the project will inadvertently point canonical SEO tags to the `decision.ai` domain. This confuses search engines and users, and harms the SEO of both the fork and the original project.

## Recommendation
- Inject the Base URL via environment variables (e.g., `VITE_APP_BASE_URL`) at build time.
- Update `seo_routes.py` to use configured domains.
