# CRITICAL: Hardcoded Custom Domains in Modal Deployment

## Summary

The Modal deployment configuration hardcodes `hub.decision.ai` and
`hub-dev.decision.ai` as custom domains. Contributors who want to deploy
their own dev instance will hit a Modal error because these domains are
already claimed.

## Affected Files

- `server/modal_app.py:65`

```python
custom_domains = ["hub.decision.ai"] if env == "prod" else ["hub-dev.decision.ai"]
```

## Why This Is Critical

Modal custom domains are globally unique. When a contributor runs
`modal deploy modal_app.py`, Modal will reject the deployment because these
domains belong to PyMC Labs. This blocks the contributor development workflow.

Under the "hosted product + open code" model, this is not a release blocker
(the hosted service works fine), but it prevents contributors from deploying
their own dev instances for testing and development.

## Recommended Fix

1. Make `custom_domains` configurable via environment variable (e.g.,
   `CUSTOM_DOMAINS` in settings)
2. Default to an empty list (no custom domains) so Modal assigns its own URL
3. Document how to set up custom domains in CONTRIBUTING.md

```python
raw = _read_env_value("CUSTOM_DOMAINS") or ""
custom_domains = [d.strip() for d in raw.split(",") if d.strip()]
```

## Deferral Rationale

The hosted product's deployment works fine. This only affects contributors
who want to deploy their own instance. Should be fixed within the first week
to enable contributor development workflows.
