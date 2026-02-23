# Hardcoded Default API URLs in CLI Client

## Description
The CLI configuration in `client/src/dhub/cli/config.py` hardcodes the default API URLs to the PyMC Labs infrastructure:

```python
_DEFAULT_API_URLS: dict[str, str] = {
    "dev": "https://pymc-labs--api-dev.modal.run",
    "prod": "https://pymc-labs--api.modal.run",
}
```

## Impact
**BLOCKER**. Users who install the open-source CLI via `pip` will default to connecting to the PyMC Labs instance. This creates a "Fork Tax" where every fork must modify source code to be usable, and risks sending user data to PyMC Labs unintentionally if users don't realize they are connecting to a hosted instance.

## Recommendation
- Make the default API URL generic or require configuration on first run.
- Document clearly how to point the CLI to a self-hosted instance via environment variables or `dhub config`.
