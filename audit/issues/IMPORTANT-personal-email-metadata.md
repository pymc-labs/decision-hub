# Personal Email in Package Metadata

## Description
In `client/pyproject.toml`, the author email is set to a personal Gmail address:

```toml
authors = [
    { name = "Luca Fiaschi", email = "luca.fiaschi@gmail.com" },
]
```

## Impact
While not strictly a bug, using a personal email for an organizational project (PyMC Labs) in an open-source release can lead to spam for the individual and creates a "bus factor" appearance.

## Recommendation
Change the email to a generic maintainer email (e.g., `maintainers@pymc-labs.com`) or ensures the individual is comfortable with this being public in the OSS release.
