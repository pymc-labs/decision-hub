# IMPORTANT: `pymc-labs` References Throughout Codebase

## Summary

The string `pymc-labs` appears in 50+ locations across the codebase. Under
the "hosted product + open code" release contract, these references fall
into three categories — all acceptable for release:

## Category A: Branding (Acceptable — Keep)

These references are standard OSS practice. Projects like Next.js (Vercel),
Terraform (HashiCorp), and PyTorch (Meta) all maintain maintainer branding.

| File | Context | Action |
|------|---------|--------|
| `frontend/src/components/Layout.tsx:78` | GitHub repo link | Keep (correct repo URL) |
| `frontend/src/components/Layout.tsx:112` | Footer: "PyMC Labs" | Keep (maintainer credit) |
| `README.md` | GitHub badges/links | Keep |
| `client/pyproject.toml:46-48` | Repository URLs | Keep |
| `frontend/src/pages/TermsPage.tsx` | Legal operator | Keep (accurate ToS) |
| `frontend/src/pages/PrivacyPage.tsx` | Legal operator | Keep (accurate privacy policy) |
| Test files (50+ refs) | Example org data | Keep (harmless test fixtures) |

## Category B: Infrastructure Lock-in (Must Fix)

These prevent independent deployment and are tracked in separate BLOCKER
issues.

| File | Context | Tracked In |
|------|---------|------------|
| `client/src/dhub/cli/config.py:16-17` | Default API URLs | `BLOCKER-hardcoded-api-urls-in-client.md` |
| `server/modal_app.py:65` | Custom domains | `BLOCKER-hardcoded-custom-domains-in-modal.md` |
| `scripts/deploy.sh:53,55` | Deploy URL echo | Below |

## Category C: Cosmetic Coupling (Should Fix)

Not infrastructure blockers, but make forks feel like second-class citizens.

| File | Context | Action |
|------|---------|--------|
| `frontend/src/constants/featuredOrgs.ts:2` | `pymc-labs` in featured list | Make configurable |
| `frontend/src/pages/HomePage.tsx:302-309` | Example: `pymc-labs/pymc-modeling` | Use generic example |
| `frontend/src/pages/HowItWorksPage.tsx` | 14 refs in example commands | Use generic examples |
| `frontend/src/components/AnimatedTerminal.tsx` | Example output | Use generic examples |
| `server/.env.example:34` | Example org restriction | Use placeholder |
| `scripts/deploy.sh:53,55` | Hardcoded Modal URL echo | Derive dynamically |

## Recommended Fix

Under the hosted product model:
1. **Category A** — no changes needed (intentional branding)
2. **Category B** — CLI defaults and deploy scripts point to the hosted
   product, which is intentional. Document `DHUB_API_URL` override for
   contributors in CONTRIBUTING.md. Modal custom domains tracked separately.
3. **Category C** — cosmetic; can be improved post-release if desired

## Deferral Rationale

All categories are acceptable under the hosted product release contract.
The code is the hosted product's codebase, and branding reflects this.
Category C improvements are nice-to-have for contributor experience.
