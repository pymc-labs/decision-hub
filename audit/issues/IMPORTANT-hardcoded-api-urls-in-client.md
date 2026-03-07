# IMPORTANT: CLI Default API URLs Point to Hosted Service

## Summary

The CLI client defaults to the PyMC Labs hosted service API URLs. Under the
"hosted product + open code" release contract, this is **intentional behavior**
— the CLI is the client for the hosted product.

## Affected Files

- `client/src/dhub/cli/config.py:15-18`

```python
_DEFAULT_API_URLS: dict[str, str] = {
    "dev": "https://pymc-labs--api-dev.modal.run",
    "prod": "https://pymc-labs--api.modal.run",
}
```

## Why This Is Important (Not a Blocker)

Under the hosted product model, these defaults are correct — users who install
`dhub` via `pip install dhub-cli` should connect to the hosted service.

The `DHUB_API_URL` environment variable already provides a runtime override
for contributors and anyone running their own server.

## Recommended Improvement

Document the `DHUB_API_URL` override prominently in CONTRIBUTING.md so
contributors know how to point the CLI at a local development server.

## Deferral Rationale

This is the intended default for the hosted product. The override mechanism
exists. Documentation improvement only.
