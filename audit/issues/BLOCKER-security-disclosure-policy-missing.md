# BLOCKER: Missing public security disclosure policy

## Category

OSS release blocker

## Summary

The repository does not include a `SECURITY.md` (or equivalent) defining how to report vulnerabilities privately, expected response SLAs, and supported version policy.

## Evidence

- No `SECURITY.md` found at repo root.
- No explicit private vulnerability reporting path in core onboarding docs (`README.md`).

## Why this blocks OSS release

Without a disclosure policy, security researchers and users have no safe channel for embargoed reports. In practice, that drives public issue disclosure or ad-hoc contact, increasing the chance of a 0-day being exposed before a fix is available.

## Risk if released as-is

- Public vulnerability disclosure before mitigation
- Inconsistent triage and response handling
- Reputation damage from perceived unpreparedness on security

## Required remediation before release

1. Add `SECURITY.md` at repo root with:
   - private reporting channel (email or security advisory intake),
   - expected acknowledgement/triage timelines,
   - supported versions,
   - coordinated disclosure expectations.
2. Link `SECURITY.md` from `README.md`.

