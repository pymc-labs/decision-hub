# BLOCKER: Missing license metadata in shared/server package manifests

## Category

OSS release blocker

## Summary

The root repository is MIT licensed, but package metadata is inconsistent:

- `client/pyproject.toml` includes `license = "MIT"`.
- `shared/pyproject.toml` has no `license` metadata.
- `server/pyproject.toml` has no `license` metadata.

## Evidence

- `shared/pyproject.toml` and `server/pyproject.toml` contain no `project.license` declaration.
- `shared` package (`dhub-core`) is referenced as a distributable package and should carry explicit license metadata.

## Why this blocks OSS release

For an OSS release, package-level license clarity must be explicit for downstream consumers and compliance tooling. Ambiguous or missing metadata creates legal/compliance friction for adopters.

## Risk if released as-is

- Compliance tools may flag packages as unknown/unapproved.
- Enterprise adopters may block ingestion.
- Additional legal back-and-forth during initial adoption.

## Required remediation before release

1. Add explicit license metadata to `shared/pyproject.toml` and `server/pyproject.toml` (e.g., `license = "MIT"`).
2. Ensure package metadata in published artifacts reflects the same license as root `LICENSE`.
3. Optionally add classifiers for license in all published packages for consistency.

