# PR #33 — Sync GitHub Org Metadata on Login

## Overview

Enrich organization profiles with metadata from the GitHub API: avatar URL, email, description, and blog. This data is synced during the OAuth login flow (best-effort, non-blocking) and cached with a 24-hour refresh window. A new `GET /v1/orgs/{slug}` detail endpoint exposes the full org profile.

## Archived Branch

- Branch: `claude/sync-org-github-data-C1YDS`
- Renamed to: `REIMPLEMENTED/claude/sync-org-github-data-C1YDS`
- Original PR: #33

## Schema Changes

### SQL Migration

Create a timestamp-based migration file (e.g. `YYYYMMDD_HHMMSS_add_org_github_metadata.sql`):

```sql
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS avatar_url TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS blog TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS github_synced_at TIMESTAMPTZ;
```

### SQLAlchemy Model Updates

Add five nullable columns to `organizations_table` in `database.py`:

```python
Column("avatar_url", Text, nullable=True),
Column("email", Text, nullable=True),
Column("description", Text, nullable=True),
Column("blog", Text, nullable=True),
Column("github_synced_at", DateTime(timezone=True), nullable=True),
```

### Dataclass Updates

Add five fields to `Organization` in `models.py`:

```python
avatar_url: str | None = None
email: str | None = None
description: str | None = None
blog: str | None = None
github_synced_at: datetime | None = None
```

Update `_row_to_organization` in `database.py` to map the new columns.

## API Changes

### Modified: `GET /v1/orgs`

`OrgSummary` response gains `avatar_url` and `is_personal` fields:

```python
class OrgSummary(BaseModel):
    id: str
    slug: str
    avatar_url: str | None = None
    is_personal: bool = False
```

### New: `GET /v1/orgs/{slug}`

Returns full org profile:

```python
class OrgDetail(BaseModel):
    id: str
    slug: str
    is_personal: bool
    avatar_url: str | None = None
    email: str | None = None
    description: str | None = None
    blog: str | None = None
    github_synced_at: datetime | None = None
```

Requires authentication. Returns 404 if org not found.

### New database function

```python
def update_org_github_metadata(
    conn: Connection,
    org_id: UUID,
    *,
    avatar_url: str | None = None,
    email: str | None = None,
    description: str | None = None,
    blog: str | None = None,
) -> None:
    """Update GitHub-sourced metadata and set github_synced_at = now()."""
```

## Auth Flow Changes

In `auth_routes.py`, after `sync_user_orgs` completes:

```python
try:
    await sync_org_github_metadata(conn, gh_token, org_slugs, username)
except Exception:
    logger.opt(exception=True).warning(
        "Failed to sync GitHub metadata for {}; continuing", username,
    )
```

This is **best-effort**: failures are logged but never block login.

## Domain Logic

### `sync_org_github_metadata` (in `domain/orgs.py`)

For each org slug:
1. Skip if `github_synced_at` is within the last 24 hours.
2. If slug matches the personal namespace (username), call `fetch_user_metadata`.
3. Otherwise call `fetch_org_metadata`.
4. Persist via `update_org_github_metadata`.

### GitHub API Functions (in `infra/github.py`)

```python
async def fetch_org_metadata(access_token: str, org_login: str) -> dict:
    """GET https://api.github.com/orgs/{org_login}"""
    # Returns: {avatar_url, email, description, blog}

async def fetch_user_metadata(access_token: str, username: str) -> dict:
    """GET https://api.github.com/users/{username}"""
    # Returns: {avatar_url, email, description (from 'bio'), blog}
```

Note: For users, the description field maps to the GitHub `bio` field.

## CLI Changes

None.

## Frontend Changes

None in this PR, but the `OrgSummary` and `OrgDetail` responses enable future org profile pages.

## Files to Create/Modify

| Action | File |
|--------|------|
| Create | `server/migrations/YYYYMMDD_HHMMSS_add_org_github_metadata.sql` |
| Modify | `server/src/decision_hub/infra/database.py` |
| Modify | `server/src/decision_hub/models.py` |
| Modify | `server/src/decision_hub/infra/github.py` |
| Modify | `server/src/decision_hub/domain/orgs.py` |
| Modify | `server/src/decision_hub/api/auth_routes.py` |
| Modify | `server/src/decision_hub/api/org_routes.py` |
| Create | `server/tests/test_api/test_org_routes.py` (extend existing) |
| Create | `server/tests/test_domain/test_orgs.py` (extend existing) |
| Create | `server/tests/test_infra/test_github.py` (extend existing) |

## Notes for Re-implementation

1. **Migration filename collision**: The original branch used `009_add_org_github_metadata.sql` which conflicts with `009_add_search_logs.sql` on main. Use timestamp-based naming.

2. **Async in sync context**: `sync_org_github_metadata` is async (uses `httpx.AsyncClient`). The auth route (`exchange_token`) is already async, so `await` works directly. If called from a sync context, use `asyncio.run()` or restructure.

3. **Rate limiting**: GitHub API rate limits are 5,000 requests/hour for authenticated users. With the 24-hour cache, a user logging in daily syncs metadata for ~5-10 orgs, well within limits.

4. **`is_personal` on OrgSummary**: The original PR also added `is_personal` to the list response. This is already available on the `Organization` model.

5. **Test the happy path and error resilience**: Ensure tests verify that metadata sync failure does NOT break login (the `try/except` in auth_routes).
