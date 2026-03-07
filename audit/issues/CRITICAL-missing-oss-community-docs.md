# CRITICAL: Missing Contributor & Governance Documents

## Summary

The repository is missing standard community governance documents expected
by the open-source community. Their absence signals an immature project and
may discourage contributions.

Note: `SECURITY.md` is tracked separately as a BLOCKER — see
`BLOCKER-security-disclosure-policy-missing.md`.

## Missing Documents

### CONTRIBUTING.md

No contributor guidelines exist. Developers who want to contribute have no
guidance on:
- Development environment setup
- Code style expectations
- PR process and review expectations
- Testing requirements
- How to report bugs

Currently, development guidance lives in `CLAUDE.md` (which is primarily
AI agent instructions and contains sensitive operational details).

### CODE_OF_CONDUCT.md

No code of conduct. This is a community expectation for OSS projects,
particularly those hosted on GitHub.

### Issue Templates (`.github/ISSUE_TEMPLATE/`)

No issue templates. Only a PR template exists. Without templates, bug reports
and feature requests will lack structure.

## Why This Is Critical

- **CONTRIBUTING.md** is needed to onboard the first external contributors
- **CODE_OF_CONDUCT.md** is a governance baseline
- **Issue templates** improve signal quality from community reports

## Recommended Fix

1. Extract sanitized development guidelines from `CLAUDE.md` into
   `CONTRIBUTING.md`
2. Add `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1 is standard)
3. Add `.github/ISSUE_TEMPLATE/bug_report.yml` and `feature_request.yml`

## Deferral Rationale

The project is functional without these files. They can follow within the
first week post-release without major consequences, as long as `SECURITY.md`
(tracked as a separate BLOCKER) is in place.
