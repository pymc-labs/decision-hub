# IMPORTANT: SEO and Canonical URLs Hardcoded to Hosted Product Domains

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

## Why This Is Important (Not Critical)

Under the "hosted product + open code" release contract, these domains are
the hosted product's canonical URLs. This is intentional behavior.

For anyone who does self-host, the impact would be:
- Canonical URLs pointing to the hosted product's domain
- Search engines may favor the hosted instance (which is the intent)
- Sitemap generation uses the hosted product's domain

## Recommended Fix

1. Move `BASE_URL` to an environment variable (`VITE_BASE_URL` for frontend,
   `BASE_URL` for backend settings)
2. Default to empty string or localhost for development
3. Document the configuration in deployment guide

## Deferral Rationale

Only affects self-hosters who care about SEO. The project works correctly
without this fix. However, it should be addressed soon to establish the right
pattern.
