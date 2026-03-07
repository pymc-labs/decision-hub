# IMPORTANT: No Explicit CORS Middleware Configuration

## Summary

The FastAPI application has no explicit CORS middleware. It currently works
because the frontend is served from the same origin (bundled into the Modal
container). However, this breaks for any self-hosted deployment where the
frontend and API are on different origins.

## Affected Files

- `server/src/decision_hub/api/app.py` — no `CORSMiddleware` imported or added

## Context

The current architecture bundles `frontend/dist/` into the Modal container
and serves it alongside the API. This same-origin pattern avoids CORS entirely.
However, during local development or in deployments where the frontend is
served separately, cross-origin requests will be blocked.

## Recommended Fix

Add configurable CORS middleware:

```python
from fastapi.middleware.cors import CORSMiddleware

allowed_origins = settings.cors_allowed_origins  # comma-separated, from env

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)
```

## Deferral Rationale

Same-origin serving works today. This only affects self-hosters who separate
frontend/backend or developers running `vite dev` against a remote API.
Low urgency.
