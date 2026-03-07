# Execution Plan -- PR #256 Review Fixes

## Group 1 (Parallel -- Non-overlapping files)

### Agent A: Database layer + Migrations
**Files:** `database.py`, `plugin_publish_pipeline.py`, 2 new migration files
**Items:** C1, C3, H1, H2, M1, M2, M3, M5 (function def only)

### Agent B: Server-side zip + Tracker service
**Files:** `repo_utils.py`, `tracker_service.py`, `crawler/processing.py`
**Items:** C2, L2, M5 (caller only)

### Agent C: Routes + CLI
**Files:** `search_routes.py`, `plugin_routes.py`, `client/registry.py`
**Items:** M4, M6, L1

## Group 2 (Sequential -- After merging Group 1)
- Merge all worktree branches
- Run linter + formatter
- Run tests
- Fix any issues

## Item Details

| Item | Severity | Files | Agent |
|------|----------|-------|-------|
| C1: search_vector trigger | Critical | New migration | A |
| C2: preserve_dot_dirs | Critical | repo_utils, tracker_service, processing | B |
| C3: org-scoped deprecation | Critical | database, pipeline | A |
| H1: org profiles visibility | High | database | A |
| H2: sort nulls_last + tiebreaker | High | database | A |
| M1: FK ON DELETE SET NULL | Medium | New migration + database | A |
| M2: summary columns | Medium | database | A |
| M3: versions LIMIT | Medium | database | A |
| M4: candidate_map key | Medium | search_routes | C |
| M5: mark_plugins_source_removed | Medium | database (def) + tracker_service (caller) | A+B |
| M6: kind field | Medium | plugin_routes | C |
| L1: private→org mapping | Low | client/registry | C |
| L2: VersionConflictError | Low | tracker_service | B |
