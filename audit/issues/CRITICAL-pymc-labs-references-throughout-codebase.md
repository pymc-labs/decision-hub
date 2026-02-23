# CRITICAL: `pymc-labs` Organization Hardcoded Throughout Codebase

## Summary

The string `pymc-labs` appears in 50+ locations across the codebase, including
user-facing frontend pages, example terminal output, and legal pages. This
tightly couples the open-source project to a specific company's identity.

## Affected Areas

### Frontend (user-visible)

| File | Context |
|------|---------|
| `frontend/src/components/Layout.tsx:78` | GitHub repo link: `github.com/pymc-labs/decision-hub` |
| `frontend/src/components/Layout.tsx:112` | Footer: links to `pymc-labs.com` |
| `frontend/src/constants/featuredOrgs.ts:2` | `pymc-labs` in featured orgs list |
| `frontend/src/pages/HomePage.tsx:302-309` | Example output shows `pymc-labs/pymc-modeling` |
| `frontend/src/pages/HowItWorksPage.tsx` | 14 references in example commands |
| `frontend/src/components/AnimatedTerminal.tsx` | Example output |
| `frontend/src/pages/TermsPage.tsx:102` | Contact: `info@pymc-labs.com` |
| `frontend/src/pages/PrivacyPage.tsx:101,125` | Contact: `info@pymc-labs.com` |

### Backend / CLI

| File | Context |
|------|---------|
| `client/src/dhub/cli/config.py:16-17` | Modal workspace in API URLs |
| `scripts/deploy.sh:53,55` | Deploy URL echo |
| `server/.env.example:34` | Example org restriction |

### Documentation

| File | Context |
|------|---------|
| `README.md:1` | GitHub badges/links |
| `client/pyproject.toml:46-48` | Repository URLs |

### Tests (50+ references)

Test files use `pymc-labs` as example org data throughout.

## Why This Is Critical

While not a security issue, having the original company's identity baked into
every user-facing surface makes the project feel proprietary rather than
community-owned. It undermines the credibility of the OSS release.

## Recommended Fix

1. **Frontend**: Replace hardcoded company references with configurable
   constants or environment variables
2. **Examples**: Use generic org names (e.g., `acme-corp`, `my-org`)
3. **Legal pages**: Parameterize the operator name/email
4. **Tests**: Acceptable to keep `pymc-labs` in test fixtures (it's just data)
5. **Client config**: Make Modal workspace configurable (see BLOCKER issue)

## Deferral Rationale

This is cosmetic/branding rather than functional. The project works correctly
with these references. However, addressing the user-visible instances (frontend,
README) should happen within days of the OSS release.
