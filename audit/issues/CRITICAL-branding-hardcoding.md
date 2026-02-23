# Extensive "PyMC Labs" Branding Hardcoding

## Description
The string `pymc-labs` appears in 50+ locations, including hardcoded organization requirements in `settings.py` examples, frontend footers, and legal text.

## Impact
**CRITICAL**. While acknowledging authorship is good, hardcoding the organization name into logic (e.g., default orgs, API URLs) creates a high "Fork Tax". It makes the project feel proprietary rather than truly open source.

## Recommendation
- Refactor organization-specific strings into configuration or constants.
- Ensure the default experience (empty config) does not assume a `pymc-labs` context.
