# Hardcoded Custom Domains in Modal App

## Description
The `server/modal_app.py` file contains hardcoded custom domains for the Modal application:

```python
custom_domains = ["hub.decision.ai"] if env == "prod" else ["hub-dev.decision.ai"]
```

## Impact
This prevents any other user or organization from deploying the server to their own Modal account without modifying the source code. If they try to deploy, Modal will fail because they do not own the `decision.ai` domain.

## Recommendation
- Move the custom domain configuration to an environment variable (e.g., `MODAL_CUSTOM_DOMAIN`).
- If the environment variable is not set, default to `None` (no custom domain) or let Modal generate a default URL.
- Update `server/src/decision_hub/settings.py` to include this setting if needed, though `modal_app.py` runs at deploy time so it might just need `os.environ`.
