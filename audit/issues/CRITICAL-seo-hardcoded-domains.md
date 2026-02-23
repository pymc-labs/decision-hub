# CRITICAL: SEO and Canonical URLs Hardcoded to Production Domains

## Summary

Multiple frontend and backend files hardcode `hub.decision.ai` and
`decisionhub.dev` as canonical URLs. Self-hosters will serve pages with
incorrect canonical URLs, harming their SEO and confusing search engines.

## Affected Files

### Backend

- `server/src/decision_hub/api/seo_routes.py:16`
  ```python
  _BASE_URL = "https://decisionhub.dev"
  ```
- `server/src/decision_hub/api/seo_routes.py:87`
  ```python
  _PROD_HOSTS = {"hub.decision.ai", "decisionhub.dev"}
  ```

### Frontend

- `frontend/src/hooks/useSEO.ts:4`
  ```typescript
  const BASE_URL = "https://hub.decision.ai";
  ```
- `frontend/src/pages/HomePage.tsx:52`
  ```typescript
  url: "https://hub.decision.ai",
  ```
- `frontend/index.html:9,16`
  ```html
  <link rel="canonical" href="https://hub.decision.ai/" />
  <meta property="og:url" content="https://hub.decision.ai/" />
  ```

## Why This Is Critical

- Self-hosted instances will serve canonical URLs pointing to someone else's
  domain
- Search engines may de-index self-hosted instances in favor of the canonical
- Sitemap generation points to the wrong domain
- Open Graph metadata links to wrong URL when shared on social media

## Recommended Fix

1. Move `BASE_URL` to an environment variable (`VITE_BASE_URL` for frontend,
   `BASE_URL` for backend settings)
2. Default to empty string or localhost for development
3. Document the configuration in deployment guide

## Deferral Rationale

Only affects self-hosters who care about SEO. The project works correctly
without this fix. However, it should be addressed soon to establish the right
pattern.
