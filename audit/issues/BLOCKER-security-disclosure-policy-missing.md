# BLOCKER: Missing Security Disclosure Policy (SECURITY.md)

## Summary

The repository has no `SECURITY.md` or equivalent security disclosure policy.
Without a clear private reporting channel, the first vulnerability discovered
by an external researcher will likely be disclosed as a public GitHub issue,
exposing the production deployment before a fix is available.

## Evidence

- No `SECURITY.md` at repository root
- No security contact in `README.md`
- No GitHub private vulnerability reporting configured
- The project has active production infrastructure at `hub.decision.ai`

## Why This Is a Blocker

This is the single highest-risk governance gap for an OSS release with live
production infrastructure. The moment the repo is public:

1. Security researchers can discover the codebase
2. Without a private reporting path, responsible disclosure defaults to
   public issue filing
3. A public vulnerability report for a live service creates a 0-day window

The risk is not theoretical — it's the default behavior of researchers who
follow standard OSS practices.

## Recommended Fix

Create `SECURITY.md` with:

```markdown
# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly.

**DO NOT** open a public GitHub issue for security vulnerabilities.

Instead, please email **security@pymc-labs.com** (or appropriate contact)
with:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

We will acknowledge receipt within 48 hours and provide a timeline for
a fix within 5 business days.

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest  | Yes       |
```

Additionally, enable GitHub's private vulnerability reporting feature in
repository settings.

## Effort Estimate

15-30 minutes. No code changes required.
