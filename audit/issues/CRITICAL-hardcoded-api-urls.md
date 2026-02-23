# Hardcoded Default API URLs in CLI

## Description
The CLI configuration in `client/src/dhub/cli/config.py` hardcodes the default API URLs to the PyMC Labs infrastructure:

```python
_DEFAULT_API_URLS: dict[str, str] = {
    "dev": "https://pymc-labs--api-dev.modal.run",
    "prod": "https://pymc-labs--api.modal.run",
}
```

## Impact
Users who install the open-source CLI will default to connecting to the PyMC Labs instance. While this might be intended for the "official" client, it makes it difficult for users to use the CLI with a self-hosted instance without knowing exactly which environment variable (`DHUB_API_URL`) to override or how to configure it.

## Recommendation
- Make the default API URL configurable via a build-time variable or a clear configuration command.
- Consider defaulting to a placeholder or a local URL if the intention is for users to self-host.
- If the intention is for the OSS CLI to point to the hosted service by default, explicitly document how to point it to a self-hosted instance in the `README.md` or `CONTRIBUTING.md`.
