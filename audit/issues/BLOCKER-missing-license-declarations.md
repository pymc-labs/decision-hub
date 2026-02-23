# Missing License Declarations in Sub-packages

## Description
While the root `LICENSE` file exists (MIT), the `pyproject.toml` files for sub-packages do not consistently declare the license:
- `client/pyproject.toml`: Declares "MIT".
- `server/pyproject.toml`: Missing `license` field.
- `shared/pyproject.toml`: Missing `license` field.

## Impact
**BLOCKER**. Packages published to PyPI (like `dhub-core`) will show "License: UNKNOWN". This causes automated license compliance tools in enterprise environments to reject the package, blocking adoption.

## Recommendation
Add `license = "MIT"` to `server/pyproject.toml` and `shared/pyproject.toml`.
