# Hardcoded "decision.ai" URLs in Frontend and CLI

## Description
There are multiple hardcoded references to `decision.ai` and `hub.decision.ai` throughout the codebase:

- **Frontend**:
  - `frontend/src/hooks/useSEO.ts`: `BASE_URL = "https://hub.decision.ai"`
  - `frontend/index.html`: Canonical links and OG tags.
  - `frontend/src/pages/HomePage.tsx`: Hardcoded URL.
- **CLI**:
  - `client/src/dhub/cli/config.py`: Links in error messages point to `hub.decision.ai`.
- **Documentation**:
  - `README.md`: Multiple links.

## Impact
If someone forks and deploys the project, their frontend will still point canonical tags and links to the original `decision.ai` domain, which is confusing and incorrect for a fork. It also harms SEO for the fork and potentially the original site.

## Recommendation
- Replace hardcoded URLs with configuration variables.
- For the frontend, use `VITE_` environment variables (e.g., `VITE_APP_BASE_URL`) injected at build time.
- For the CLI, use the configured API URL or a general project URL setting.
