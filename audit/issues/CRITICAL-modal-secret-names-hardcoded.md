# CRITICAL: Modal Secret Names Hardcoded in Deployment Configuration

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

## Why This Is Critical

Self-hosters must create secrets with the exact names `decision-hub-db`,
`decision-hub-secrets`, etc. This is not documented for external users and
the naming convention is project-specific.

## Recommended Fix

Make secret names configurable via environment variables with sensible defaults:

```python
db_secret = os.environ.get("MODAL_DB_SECRET", f"decision-hub-db{suffix}")
```

Or document the required Modal secrets in a deployment guide.

## Deferral Rationale

The current names work fine — they just require documentation. This is a
quality-of-life improvement for self-hosters, not a functional blocker.
