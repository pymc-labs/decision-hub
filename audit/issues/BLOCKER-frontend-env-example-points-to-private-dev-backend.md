# BLOCKER: Frontend `.env.example` points to private maintainer dev backend

## Category

OSS release blocker

## Summary

`frontend/.env.example` currently sets:

```env
VITE_API_URL=https://lfiaschi--api-dev.modal.run
```

This is a maintainer-specific/dev-specific backend endpoint.

## Evidence

- `frontend/.env.example:3` hardcodes `https://lfiaschi--api-dev.modal.run`.

## Why this blocks OSS release

For an open-source release, examples should be neutral and safe. A maintainer-owned dev API URL in default config can cause external contributors/users to unintentionally point local apps at internal/shared infrastructure.

## Risk if released as-is

- Unintended traffic/load on maintainer dev environment
- Data pollution and confusing bug reports from mixed environments
- Potential accidental write operations against non-user-owned backend

## Required remediation before release

1. Change `frontend/.env.example` to a neutral default, e.g.:
   - `VITE_API_URL=` (blank), or
   - `VITE_API_URL=http://localhost:8000`
2. Add explicit setup note in frontend README explaining how to set a custom remote API URL intentionally.

