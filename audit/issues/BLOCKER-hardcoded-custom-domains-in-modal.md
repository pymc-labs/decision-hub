# BLOCKER: Hardcoded Custom Domains in Modal Deployment

## Summary

The Modal deployment configuration hardcodes `hub.decision.ai` and
`hub-dev.decision.ai` as custom domains. Anyone deploying their own instance
will hit a Modal error because these domains are already claimed.

## Affected Files

- `server/modal_app.py:65`

```python
custom_domains = ["hub.decision.ai"] if env == "prod" else ["hub-dev.decision.ai"]
```

## Why This Is a Blocker

Modal custom domains are globally unique. When a new user runs
`modal deploy modal_app.py`, Modal will reject the deployment because these
domains belong to the original project. This makes the deploy script unusable
out of the box for anyone but PyMC Labs.

## Recommended Fix

1. Make `custom_domains` configurable via environment variable (e.g.,
   `CUSTOM_DOMAINS` in settings)
2. Default to an empty list (no custom domains) so Modal assigns its own URL
3. Document how to set up custom domains in the deployment guide

```python
raw = _read_env_value("CUSTOM_DOMAINS") or ""
custom_domains = [d.strip() for d in raw.split(",") if d.strip()]
```

## Impact

- Deployment fails for anyone who isn't PyMC Labs
- Blocks the basic "clone, configure, deploy" workflow
