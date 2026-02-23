# BLOCKER: Hardcoded Modal custom domains break third-party deploys

## Category

OSS release blocker

## Summary

Modal deployment is hardcoded to maintainers' owned domains:

```python
custom_domains = ["hub.decision.ai"] if env == "prod" else ["hub-dev.decision.ai"]
```

This prevents most external adopters from deploying without code changes.

## Evidence

- `server/modal_app.py:65` hardcodes production and dev custom domains.
- `@modal.asgi_app(..., custom_domains=custom_domains)` binds deploy behavior to these values.

## Why this blocks OSS release

An OSS release should be deployable by non-maintainers with configuration changes, not source edits. Hardcoded claimed domains create immediate deploy failures for forks/self-hosters.

## Risk if released as-is

- Third-party `modal deploy` failures out of the box.
- High support burden ("why does deploy fail on my fork?").
- Perception that the project is not actually self-hostable.

## Required remediation before release

1. Move custom domains to configuration/env (e.g., optional `CUSTOM_DOMAINS` value).
2. Default to no custom domains for non-maintainer deployments.
3. Document domain setup in deployment docs.

