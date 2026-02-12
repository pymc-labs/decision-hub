# PR #31 — Optimize Skill Index Query with LATERAL Join

## Overview

Replace the `ROW_NUMBER()` window function in `fetch_all_skills_for_index` with a `LATERAL` subquery join. The current query computes `ROW_NUMBER() OVER (PARTITION BY skill_id ORDER BY semver_major DESC, semver_minor DESC, semver_patch DESC)` across all version rows, then filters to `rn = 1`. This requires scanning and ranking every version row even though we only need the top-1 per skill.

A `LATERAL` join instead performs one index lookup per skill using the existing `idx_versions_skill_semver_parts` composite index, grabbing the single highest-semver version directly. For a registry with many skills and many versions per skill, this is significantly more efficient.

## Archived Branch

- Branch: `claude/optimize-skill-versions-duCUi`
- Renamed to: `REIMPLEMENTED/claude/optimize-skill-versions-duCUi`
- Original PR: #31

## Schema Changes

None. This optimization leverages the existing `idx_versions_skill_semver_parts` index created by migration `008_add_semver_int_columns.sql`.

## API Changes

None. The query returns the same columns in the same format. This is a transparent performance optimization.

## CLI Changes

None.

## Implementation Details

### Current query (ROW_NUMBER approach)

```python
latest_version = (
    sa.select(
        versions_table.c.skill_id,
        versions_table.c.semver,
        versions_table.c.eval_status,
        versions_table.c.created_at,
        versions_table.c.published_by,
        sa.func.row_number()
        .over(
            partition_by=versions_table.c.skill_id,
            order_by=[
                versions_table.c.semver_major.desc(),
                versions_table.c.semver_minor.desc(),
                versions_table.c.semver_patch.desc(),
            ],
        )
        .label("rn"),
    )
).subquery("ranked")

# ...joined with: skills_table.c.id == latest_version.c.skill_id AND latest_version.c.rn == 1
```

### Proposed query (LATERAL approach)

```python
latest_version = (
    sa.select(
        versions_table.c.semver,
        versions_table.c.eval_status,
        versions_table.c.created_at,
        versions_table.c.published_by,
    )
    .where(versions_table.c.skill_id == skills_table.c.id)
    .order_by(
        versions_table.c.semver_major.desc(),
        versions_table.c.semver_minor.desc(),
        versions_table.c.semver_patch.desc(),
    )
    .limit(1)
    .lateral("latest_version")
)

# ...joined with: sa.literal(True) (the correlation is in the WHERE clause)
```

### Why LATERAL is better

- **ROW_NUMBER**: Scans ALL version rows, assigns a rank per partition, then filters. PostgreSQL cannot short-circuit after finding the top row.
- **LATERAL**: For each skill, performs a single index-range scan on `idx_versions_skill_semver_parts(skill_id, semver_major DESC, semver_minor DESC, semver_patch DESC)` and stops after 1 row. Cost is O(skills) instead of O(versions).
- The existing composite index is already ordered correctly for this pattern.

### Callers affected

- `GET /v1/skills` (`registry_routes.list_skills`)
- `GET /v1/search` (`search_routes.search_skills`)
- All tests that mock `fetch_all_skills_for_index`

## Files to Create/Modify

| Action | File |
|--------|------|
| Modify | `server/src/decision_hub/infra/database.py` (`fetch_all_skills_for_index`) |

## Notes for Re-implementation

1. **Single-file change**: This PR only modifies `database.py`. No migrations, no API changes, no CLI changes.

2. **Visibility filtering**: The current `fetch_all_skills_for_index` on main includes `user_org_ids` filtering for private skills. The original branch was based on an older main without this. The reimplementation must preserve the visibility `WHERE` clause while switching to a LATERAL join.

3. **`sa.literal(True)` join condition**: When using LATERAL, the correlation is inside the subquery's WHERE clause (`versions_table.c.skill_id == skills_table.c.id`), so the outer join condition is just `True`. This is standard SQLAlchemy LATERAL usage.

4. **No `skill_id` in LATERAL select**: The subquery doesn't need to select `skill_id` since the correlation is implicit — each lateral result is already scoped to the current skill row.

5. **Test compatibility**: All existing tests mock `fetch_all_skills_for_index` at the call site, so no test changes should be needed. The function signature and return shape are identical.

6. **Combine with PR #30 pagination**: If implementing pagination (PR #30) at the same time, the LATERAL join + `LIMIT`/`OFFSET` on the outer query compose cleanly. The LATERAL executes once per skill row in the result page, not for all skills.
