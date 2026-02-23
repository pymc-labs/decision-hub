## PLAN — Numbered key decisions with rationale.

1. **Incorporate critique convergence before revising findings.**  
   Read all agent critiques and adopted recurring high-confidence gaps that I previously underweighted: hardcoded Modal custom domains, hardcoded CLI API defaults, and package license metadata consistency.

2. **Re-center blocker criteria on external deployability + legal clarity.**  
   Upgraded issues that directly prevent third-party deployment or legal adoption to `BLOCKER` (custom domains, CLI defaults, package license metadata, missing `SECURITY.md`).

3. **Differentiate runtime blockers from template/docs friction.**  
   Reclassified `frontend/.env.example` from `BLOCKER` to `IMPORTANT` because it is a template (editable), unlike shipped runtime defaults that affect users immediately.

4. **Preserve abuse-resistance/security process findings as urgent.**  
   Kept auth endpoint rate-limit gap and missing automated dependency monitoring as `CRITICAL`, and added hardcoded public-domain coupling as `CRITICAL` due to high fork confusion risk.

5. **Expand checklist coverage while keeping evidence links explicit.**  
   Revised checklist now covers legal/package metadata, forkability, domain coupling, endpoint security, supply chain, governance, and metadata ownership with direct links to issue files.

## CHANGES — Unified diff or precise change descriptions.

- **Rewrote** `audit/oss-release-checklist.md` into a round-01 revision with updated sections and status outcomes:
  - legal/package licensing,
  - deployability/forkability,
  - public-domain coupling,
  - endpoint abuse resistance,
  - secrets hygiene,
  - supply-chain automation,
  - governance readiness,
  - ownership metadata,
  - CI/release controls.

- **Added blocker issue files**:
  - `audit/issues/BLOCKER-hardcoded-modal-custom-domains-break-third-party-deploys.md`
  - `audit/issues/BLOCKER-hardcoded-cli-default-api-urls-lock-to-maintainer-infra.md`
  - `audit/issues/BLOCKER-missing-license-metadata-in-shared-and-server-packages.md`

- **Added critical issue file**:
  - `audit/issues/CRITICAL-hardcoded-public-domains-in-seo-and-ux.md`

- **Added important issue files**:
  - `audit/issues/IMPORTANT-frontend-env-example-points-to-private-dev-backend.md` (reclassified from blocker)
  - `audit/issues/IMPORTANT-personal-email-in-package-metadata.md`

- **Updated existing issue**:
  - `audit/issues/IMPORTANT-internal-ops-runbook-exposed-in-public-docs.md`  
    Expanded evidence to include `PRD.md`, `tasks.md`, and `.claude/commands/*`.

- **Deleted obsolete file**:
  - `audit/issues/BLOCKER-frontend-env-example-points-to-private-dev-backend.md`

