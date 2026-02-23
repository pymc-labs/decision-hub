# Hardcoded Modal Custom Domains

## Description
The `server/modal_app.py` file contains hardcoded custom domains for the Modal application:

```python
custom_domains = ["hub.decision.ai"] if env == "prod" else ["hub-dev.decision.ai"]
```

## Impact
**BLOCKER**. This prevents any other user or organization from deploying the server to their own Modal account. If they try to deploy, Modal will fail immediately because they do not own the `decision.ai` domain. This effectively makes the software "source-available" but not "open source" in practice for deployment.

## Recommendation
- Move the custom domain configuration to an environment variable (e.g., `MODAL_CUSTOM_DOMAIN`).
- Default to `None` (letting Modal generate a `modal.run` URL) if the variable is not set.
