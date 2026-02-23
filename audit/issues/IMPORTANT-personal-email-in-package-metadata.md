# IMPORTANT: Personal email in package metadata

## Category

Important issue (deferrable; governance/ownership clarity)

## Summary

The CLI package metadata uses a personal Gmail author address:

- `client/pyproject.toml` author email: `luca.fiaschi@gmail.com`

For a company-backed OSS release, maintainer contact identity should be intentional and documented.

## Evidence

- `client/pyproject.toml:8` contains a personal email in published metadata.

## Impact

- Ambiguous support/ownership expectations for enterprise adopters.
- Inconsistent branding if release is positioned as organizational OSS.

## Why this is IMPORTANT (not CRITICAL/BLOCKER)

This does not break security or deployability, but it can create avoidable governance/confidence friction during public adoption.

## Recommended fix

1. Confirm intended package ownership/contact policy.
2. Update metadata to organization-maintained contact where appropriate.
3. Mirror the same contact policy in `README`/support docs.

