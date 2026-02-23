# CRITICAL: Missing Standard OSS Community Documents

## Summary

The repository is missing several standard documents expected by the
open-source community. Their absence signals an immature project and may
discourage contributions.

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

### SECURITY.md

No security disclosure policy. With the project accepting community
contributions, there must be a clear channel for reporting vulnerabilities
privately (before public disclosure).

### CODE_OF_CONDUCT.md

No code of conduct. This is a community expectation for OSS projects,
particularly those hosted on GitHub.

### Issue Templates (`.github/ISSUE_TEMPLATE/`)

No issue templates. Only a PR template exists. Without templates, bug reports
and feature requests will lack structure.

## Why This Is Critical

- **SECURITY.md** is the most urgent — without it, vulnerability reporters
  may disclose publicly by default
- **CONTRIBUTING.md** is needed to onboard the first external contributors
- **CODE_OF_CONDUCT.md** is a governance baseline
- **Issue templates** improve signal quality from community reports

## Recommended Fix

1. Create `SECURITY.md` with responsible disclosure instructions
2. Extract sanitized development guidelines from `CLAUDE.md` into
   `CONTRIBUTING.md`
3. Add `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1 is standard)
4. Add `.github/ISSUE_TEMPLATE/bug_report.yml` and `feature_request.yml`

## Deferral Rationale

The project is functional without these files. However, `SECURITY.md` should
be added before release if at all possible. The others can follow within the
first week.
