# BLOCKER: Hardcoded Production API URLs in CLI Client

## Summary

The CLI client hardcodes the PyMC Labs Modal workspace API URLs, making it
impossible for anyone else to self-host or fork the project without modifying
source code.

## Affected Files

- `client/src/dhub/cli/config.py:15-18`

```python
_DEFAULT_API_URLS: dict[str, str] = {
    "dev": "https://pymc-labs--api-dev.modal.run",
    "prod": "https://pymc-labs--api.modal.run",
}
```

## Why This Is a Blocker

The CLI is the primary user-facing component published to PyPI. Every `dhub`
command routes traffic to PyMC Labs' infrastructure by default. Anyone forking
the project cannot use the CLI without code changes — there is no way to
configure the default API URL at build time or via environment variable without
first modifying the source.

While `DHUB_API_URL` env var overrides at runtime, the compiled defaults still
point to a private deployment, creating confusion for OSS users.

## Recommended Fix

Make the default API URLs configurable at build time or clearly document the
`DHUB_API_URL` override mechanism. Consider using placeholder URLs in the
defaults (e.g., `http://localhost:8000`) with clear setup instructions.

## Impact

- Every fork/self-host will hit PyMC Labs' servers by default
- PyPI package contains hardcoded third-party infrastructure URLs
- Confusing for contributors trying to run against local/their own server
