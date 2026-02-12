# PR #30 — Add Pagination to /v1/skills Endpoint

## Overview

Replace the unbounded `GET /v1/skills` response (returns all skills as a flat list) with offset-based pagination. As the registry grows, loading all skills in one request becomes slow for the CLI, frontend, and search index. This PR adds `page` and `page_size` query parameters to the server, updates the CLI `list` command with `--page` and `--page-size` flags, and adds pagination controls to the frontend.

## Archived Branch

- Branch: `claude/add-skills-pagination-ArNx0`
- Renamed to: `REIMPLEMENTED/claude/add-skills-pagination-ArNx0`
- Original PR: #30

## API Changes

### `GET /v1/skills`

**Before**: Returns `list[SkillSummary]` (all skills).

**After**: Returns `PaginatedSkillsResponse`:

```json
{
  "items": [SkillSummary, ...],
  "total": 150,
  "page": 1,
  "page_size": 20,
  "total_pages": 8
}
```

**New query parameters**:
- `page` (int, default=1, min=1): 1-indexed page number
- `page_size` (int, default=20, min=1, max=100): items per page

**Breaking change**: The response shape changes from a list to an object. The CLI and frontend must be updated simultaneously. The search endpoint (`GET /v1/search`) is NOT paginated — it still loads all skills to build the LLM search index.

### New Pydantic model

```python
class PaginatedSkillsResponse(BaseModel):
    items: list[SkillSummary]
    total: int
    page: int
    page_size: int
    total_pages: int
```

### New database function

```python
def count_all_skills(conn: Connection, *, user_org_ids: list[UUID] | None = None) -> int:
    """Count total skills visible to the user (for pagination metadata)."""
```

### Modified database function

`fetch_all_skills_for_index` gains `limit` and `offset` keyword parameters:

```python
def fetch_all_skills_for_index(
    conn: Connection,
    *,
    user_org_ids: list[UUID] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
```

## CLI Changes

`dhub list` gains two new flags:
- `--page` / `-p` (int, default=1): Page number
- `--page-size` / `-n` (int, default=20, min=1, max=100): Items per page

Output footer shows: `Page X of Y (Z total skills)`

The CLI parses the new `PaginatedSkillsResponse` shape: `data["items"]`, `data["total"]`, `data["total_pages"]`, `data["page"]`.

## Frontend Changes

### SkillsPage.tsx

- New state: `page` (default=1)
- Calls `listSkills(page, PAGE_SIZE)` with `PAGE_SIZE = 12`
- Displays pagination controls (Prev/Next buttons + "Page X of Y" label)
- Total skills count comes from `data.total` instead of `skills.length`

### api/client.ts

`listSkills()` returns `PaginatedSkillsResponse` instead of `SkillSummary[]`, passes `page` and `page_size` as query params.

### types/api.ts

New `PaginatedSkillsResponse` interface.

### Pagination CSS

New styles for `.pagination`, `.pageButton`, `.pageInfo` in `SkillsPage.module.css`.

## Files to Create/Modify

| Action | File |
|--------|------|
| Modify | `server/src/decision_hub/api/registry_routes.py` |
| Modify | `server/src/decision_hub/infra/database.py` |
| Modify | `server/tests/test_api/test_registry_routes.py` |
| Modify | `client/src/dhub/cli/registry.py` |
| Modify | `client/tests/test_cli/test_registry_cli.py` |
| Modify | `frontend/src/api/client.ts` |
| Modify | `frontend/src/types/api.ts` |
| Modify | `frontend/src/pages/SkillsPage.tsx` |
| Modify | `frontend/src/pages/SkillsPage.module.css` |

## Notes for Re-implementation

1. **Visibility filtering**: The current `fetch_all_skills_for_index` on main accepts `user_org_ids` for private skill visibility filtering. The original branch was based on an older main that lacked this parameter. The reimplementation must preserve visibility filtering in both the count and the paginated query.

2. **Search endpoint is unaffected**: `GET /v1/search` must continue to load ALL skills for the LLM index. Only the `GET /v1/skills` list endpoint gets paginated.

3. **Consider cursor-based pagination**: Offset pagination is simple but has well-known issues with large offsets (PostgreSQL must scan and discard rows). For now offset is fine, but if scale demands it, consider keyset/cursor pagination in the future.

4. **Frontend local filtering vs server filtering**: The original PR keeps client-side filtering (search, org, grade, sort) on the current page only. This means filters apply to the current page's items, not the full dataset. This is a known UX trade-off. A future improvement could move filtering to the server.

5. **The `list_command` in `client/src/dhub/cli/access.py`** is a different function (for access grants). Only modify the one in `registry.py`.
