# BLOCKER: Missing License Declarations in Sub-Packages

## Summary

While the root `LICENSE` file declares MIT, three of the four sub-packages
have no license field in their package metadata. This creates legal ambiguity
for consumers of these packages, particularly `dhub-core` which is published
to PyPI.

## Affected Files

- `server/pyproject.toml` — missing `license = "MIT"`
- `shared/pyproject.toml` — missing `license = "MIT"` (published to PyPI as `dhub-core`)
- `frontend/package.json` — missing `"license": "MIT"`

## Why This Is a Blocker

- `dhub-core` is published to PyPI. Without a license field, PyPI shows
  "License: UNKNOWN". Enterprises with license compliance tooling will flag
  this and may block installation.
- Standard OSS practice requires license metadata in every publishable
  package.
- The `client/pyproject.toml` already has `license = "MIT"` — the others
  are inconsistent.

## Recommended Fix

Add `license = "MIT"` to `[project]` in:
- `server/pyproject.toml`
- `shared/pyproject.toml`

Add `"license": "MIT"` to `frontend/package.json`.

## Impact

- Legal ambiguity for downstream consumers
- PyPI displays "License: UNKNOWN" for dhub-core
- Enterprise license scanners may block adoption
