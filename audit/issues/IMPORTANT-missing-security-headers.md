# IMPORTANT: Missing HTTP Security Headers

## Summary

The application does not set standard security headers (HSTS, CSP,
X-Frame-Options, X-Content-Type-Options). While Modal's proxy may add some
of these, the application itself does not enforce them.

## Context

Standard security headers to consider:

- `Strict-Transport-Security` (HSTS) — enforce HTTPS
- `Content-Security-Policy` (CSP) — prevent XSS
- `X-Frame-Options` — prevent clickjacking
- `X-Content-Type-Options: nosniff` — prevent MIME sniffing
- `Referrer-Policy` — control referer header

## Recommended Fix

Add a security headers middleware:

```python
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
```

## Deferral Rationale

Low urgency — the application is served over HTTPS via Modal, and the
attack surface is limited. Good practice but not a release requirement.
