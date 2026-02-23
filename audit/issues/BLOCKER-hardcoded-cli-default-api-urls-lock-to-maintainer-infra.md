# BLOCKER: CLI default API URLs are hardcoded to maintainer infrastructure

## Category

OSS release blocker

## Summary

The CLI defaults are hardcoded to PyMC Labs Modal endpoints:

```python
_DEFAULT_API_URLS = {
    "dev": "https://pymc-labs--api-dev.modal.run",
    "prod": "https://pymc-labs--api.modal.run",
}
```

## Evidence

- `client/src/dhub/cli/config.py:15-18` defines maintainer-owned default API hosts.
- `get_api_url()` falls back to this default when users have not explicitly configured `DHUB_API_URL`.

## Why this blocks OSS release

This creates a "fork tax": external users/installers are silently pointed at maintainer infrastructure rather than their own deployment. For OSS self-hostability, defaults must be neutral or explicit.

## Risk if released as-is

- Confusing auth/permission failures for external users.
- Unintended traffic to maintainer production/dev backends.
- Difficult-to-debug behavior for fork maintainers.

## Required remediation before release

1. Replace defaults with neutral values (e.g., blank/unset + explicit setup flow), or use project-owned neutral domain not tied to a maintainer account.
2. Force first-run configuration when API URL is missing.
3. Document default behavior in `README` and CLI docs.

