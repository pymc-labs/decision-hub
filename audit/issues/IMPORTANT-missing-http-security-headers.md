# IMPORTANT: HTTP security headers are not explicitly enforced

## Category

Important issue (deferrable hardening)

## Summary

The application code does not explicitly set baseline HTTP security headers (e.g., HSTS, X-Content-Type-Options, CSP, Referrer-Policy). In hosted environments these may be set upstream, but for OSS self-hosters this is currently implicit and undocumented.

## Evidence

- No matches for common security headers in `server/src/decision_hub`:
  - `Strict-Transport-Security`
  - `X-Content-Type-Options`
  - `Content-Security-Policy`
  - `Referrer-Policy`
  - `X-Frame-Options`

## Impact

- Inconsistent security posture across deployments.
- Increased risk of insecure default reverse-proxy setups in forks.
- Harder security review/compliance sign-off for adopters.

## Why this is IMPORTANT (not CRITICAL/BLOCKER)

Not an immediate functional blocker; many deployments can enforce headers at the edge. Still a meaningful hardening gap that should be addressed soon after release.

## Recommended fix

1. Define a baseline header policy in docs (minimum required headers).
2. Enforce via app middleware or officially supported reverse-proxy templates.
3. Add a lightweight security-check test (or deployment checklist) that validates header presence.

