# IMPORTANT: Frontend `.env.example` points to maintainer dev backend

## Category

Important issue (deferrable, but should be fixed quickly)

## Summary

`frontend/.env.example` currently ships with:

```env
VITE_API_URL=https://lfiaschi--api-dev.modal.run
```

As an example template, this should be neutral to avoid accidental usage against maintainer infrastructure.

## Evidence

- `frontend/.env.example:3` hardcodes a maintainer-specific dev endpoint.

## Impact

- Contributors may accidentally target non-owned infrastructure.
- Bug reports may mix local/frontend issues with remote service behavior.
- Adds avoidable confusion during onboarding.

## Why this is IMPORTANT (not BLOCKER)

Unlike runtime defaults embedded in shipped binaries, `.env.example` is a template intended for editing. Still worth fixing immediately after blocker work.

## Recommended fix

1. Set example to a neutral value:
   - `VITE_API_URL=` or
   - `VITE_API_URL=http://localhost:8000`
2. Add a note in `frontend/README.md` describing when to use remote API URLs.

