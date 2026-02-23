# Missing Security Disclosure Policy

## Description
The repository lacks a `SECURITY.md` file.

## Impact
**BLOCKER**. Without a clear security policy, security researchers who find vulnerabilities (e.g., in the auth flow) have no defined channel to report them privately. This often leads to public disclosure in GitHub Issues, exposing the production environment to 0-day attacks before a fix is ready.

## Recommendation
Add a `SECURITY.md` file with:
- Supported versions.
- Reporting process (e.g., email `security@pymc-labs.com`).
- Response timeline expectations.
