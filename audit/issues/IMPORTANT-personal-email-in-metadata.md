# IMPORTANT: Personal Email Address in Package Metadata

## Summary

The CLI package metadata uses a personal Gmail address instead of an
organizational email.

## Affected Files

- `client/pyproject.toml:8`

```toml
authors = [
    { name = "Luca Fiaschi", email = "luca.fiaschi@gmail.com" },
]
```

## Context

The LICENSE file uses `luca.fiaschi@pymc-labs.com` while the package metadata
uses a personal Gmail. For an organizational OSS release, using a personal
email:
- Creates a "bus factor" appearance
- May result in spam to the individual
- Is inconsistent with the LICENSE copyright attribution

## Recommended Fix

Update to an organizational or maintainer-specific email:

```toml
authors = [
    { name = "Luca Fiaschi", email = "luca.fiaschi@pymc-labs.com" },
]
```

Or add a generic maintainer address.

## Deferral Rationale

Cosmetic metadata issue. Does not affect functionality or security.
The next PyPI release will pick up the change.
