# IMPORTANT: Modal Secret Names Hardcoded to Hosted Product Infrastructure

## Summary

The Modal secret names are hardcoded with the `decision-hub-` prefix in
`modal_app.py`. Self-hosters must create Modal secrets with these exact names,
which may conflict with their existing secret naming conventions.

## Affected Files

- `server/modal_app.py:48-52`

```python
secrets = [
    modal.Secret.from_name(f"decision-hub-db{suffix}"),
    modal.Secret.from_name(f"decision-hub-secrets{suffix}"),
    modal.Secret.from_name(f"decision-hub-aws{suffix}"),
    modal.Secret.from_name(f"decision-hub-github-app{suffix}"),
    ...
]
```

## Why This Is Important (Not Critical)

Under the "hosted product + open code" release contract, these secret names
are the hosted product's infrastructure naming. Self-hosting is not a
first-class use case, so this is a quality-of-life improvement rather than
a critical gap. Contributors who want to deploy their own instance can
follow the naming convention documented in `.env.example`.

## Recommended Fix

Make secret names configurable via environment variables with sensible defaults:

```python
db_secret = os.environ.get("MODAL_DB_SECRET", f"decision-hub-db{suffix}")
```

Or document the required Modal secrets in a deployment guide.

## Deferral Rationale

The current names work fine — they just require documentation. This is a
quality-of-life improvement for self-hosters, not a functional blocker.
