# Scalability Review: 200k Skills

This document identifies bottlenecks that will break or degrade at 200k skills across the backend, frontend, CLI, and infrastructure layers. Issues are ordered by severity within each section.

---

## 1. CRITICAL: LLM Search Index (The #1 Blocker)

**Files:** `server/src/decision_hub/api/search_routes.py`, `server/src/decision_hub/infra/gemini.py`, `server/src/decision_hub/domain/search.py`

### What happens today

Every `dhub ask` call:
1. Runs `fetch_all_skills_for_index(conn)` — a SQL query that fetches **every skill** with a window function over all versions
2. Serializes all results to JSONL in memory (`serialize_index()`)
3. Sends the **entire JSONL index** as a single prompt to Gemini

### Why it breaks at 200k

Each JSONL line is ~170-350 chars depending on description length (measured from `serialize_index`). A typical line with a 1-sentence description is ~231 chars.

**Token estimate**: Gemini's tokenizer averages **~2.7 characters per token** for English text embedded in JSON markup (empirically measured by [GDELT across 400M tokens](https://blog.gdeltproject.org/gemini-at-scale-understanding-tokens-in-the-real-world-a-small-batch-analysis-of-400m-tokens/) — this is below Google's rough "~4 chars/token" guidance because JSON punctuation tokenizes at ~1 char/token). That gives **~86 tokens per skill line**.

| Skills | Raw size | Tokens (~86/skill) | Fits 1M context? |
|--------|----------|---------------------|-------------------|
| 1,000 | 0.2 MB | 86k | Yes |
| 5,000 | 1.2 MB | 428k | Yes |
| 10,000 | 2.3 MB | 856k | Yes (but slow + expensive) |
| **~11,700** | **2.7 MB** | **~1M** | **Breaking point** |
| 15,000 | 3.5 MB | 1.3M | No |
| 20,000 | 4.6 MB | 1.7M | No |
| 200,000 | 46 MB | 17.1M | **No (17x over limit)** |

Key concerns at scale:
- **Token limit**: Gemini 2.0 Flash has a 1M token context window. The index **breaks at ~11,700 skills** and at 200k is 17x over. The API call will fail outright.
- **Latency**: Near the context limit (e.g. at 10k skills = 856k tokens), inference takes many seconds per query.
- **Cost**: Every search query pays for the full index — at 10k skills that's ~856k input tokens per query.
- **Database load**: `fetch_all_skills_for_index` runs a `ROW_NUMBER()` window function over **all** version rows with 3× `split_part`/`CAST` per row. At 200k skills (~500k+ version rows), this is a full table scan on every search/list request.
- **Memory**: The server serializes the entire index in memory per request.

### Fix

Replace the LLM-over-full-index approach with a proper search architecture:
- **Option A (recommended)**: PostgreSQL full-text search (`tsvector`/`tsquery`) with `GIN` indexes on skill name + description. Fast, no external dependency, handles 200k easily. Use Gemini only for query reformulation or re-ranking the top-N results.
- **Option B**: Embedding-based search with `pgvector`. Compute embeddings at publish time, store in a vector column, query with cosine similarity. Better semantic matching than full-text search.
- **Option C**: External search service (Elasticsearch, Typesense, Meilisearch). Best search quality but adds operational complexity.

In all cases, the LLM should only see a small set of pre-filtered candidates (top 20-50), not the full index.

---

## 2. CRITICAL: Unpaginated List Endpoints

### Backend: `GET /v1/skills` returns ALL skills

**File:** `server/src/decision_hub/api/registry_routes.py:345-364`

```python
@public_router.get("/skills", response_model=list[SkillSummary])
def list_skills(conn=Depends(get_connection)) -> list[SkillSummary]:
    rows = fetch_all_skills_for_index(conn)  # ALL skills
    return [SkillSummary(...) for row in rows]
```

This endpoint is called by:
- `dhub list` (CLI)
- The frontend SkillsPage, HomePage, OrgDetailPage, OrgsPage, SkillDetailPage (5 separate pages)

At 200k skills, this returns a ~40MB+ JSON response, which will:
- Timeout on the server (serializing 200k Pydantic models)
- Blow up client memory (CLI and browser both hold entire list)
- Saturate the network for every page load

### Backend: `GET /v1/skills/{org}/{name}/audit-log` returns ALL audit entries

**File:** `server/src/decision_hub/api/registry_routes.py:450-477`

`find_audit_logs()` has no LIMIT clause. A popular skill with many publishes will accumulate unbounded audit entries.

### Fix

- Add `offset`/`limit` (or cursor-based) pagination to `/v1/skills` and all list endpoints.
- Default to 50 results per page.
- Add server-side filtering: `?q=search&org=filter&grade=A&sort=downloads`.
- The CLI `dhub list` should paginate or default to a reasonable limit.

---

## 3. CRITICAL: `fetch_all_skills_for_index` Query Performance

**File:** `server/src/decision_hub/infra/database.py:952-1026`

This query is called by **both** `/v1/skills` and `/v1/search`:

```python
# Window function over ALL versions
sa.func.row_number().over(
    partition_by=versions_table.c.skill_id,
    order_by=[major.desc(), minor.desc(), patch.desc()],
)
```

### Problems

1. **No indexes on semver components**: The `split_part` + `CAST` expressions that parse semver into integer components are computed for every row. PostgreSQL cannot use indexes on these computed expressions.
2. **Full table scan**: The window function must read all version rows to compute `ROW_NUMBER()` per skill.
3. **Called twice per search**: Once in `/v1/search` and also reused by `/v1/skills`.
4. **No caching**: Results are recomputed on every request even though skills change infrequently (only on publish/delete).

### Fix

- Add a **materialized view** or **denormalized `latest_version` column** on the skills table that is updated on publish/delete. This eliminates the window function entirely.
- Alternatively, add **indexed computed columns** (or a generated column) for major/minor/patch integers on the versions table.
- Add **in-process TTL caching** (e.g. `cachetools.TTLCache`, no extra infra) for the skills list since it only changes on publish/delete. On Modal each container gets its own cache — that's fine, the goal is avoiding the DB round-trip on every request within a container. Invalidate on publish/delete.

---

## 4. HIGH: Missing Database Indexes

**File:** `server/src/decision_hub/infra/database.py`

### Current indexes

Only 3 explicit indexes exist (beyond PKs and unique constraints):
- `idx_audit_logs_skill` on `(org_slug, skill_name)`
- `idx_audit_logs_version` on `(version_id)`
- `idx_eval_reports_version_id` on `(version_id)`

### Missing indexes needed at 200k

| Table | Missing Index | Why |
|-------|--------------|-----|
| `versions` | `(skill_id, semver)` compound | `resolve_version` and `find_version` filter on both columns. The unique constraint provides this implicitly, but verify it's being used. |
| `versions` | `(skill_id, created_at DESC)` | The `fetch_all_skills_for_index` window function orders by semver parts. If you add integer columns, index those. |
| `skills` | `(org_id, name)` compound | Already has unique constraint, but verify index usage. |
| `eval_runs` | `(version_id, created_at DESC)` | `find_eval_runs_for_version` and `find_latest_eval_run_for_version` filter by version_id and sort by created_at. |
| `eval_runs` | `(user_id, created_at DESC)` | `find_active_eval_runs_for_user` filters by user_id and sorts by created_at. |
| `versions` | `(eval_status)` partial or filtered | `resolve_version` filters by `eval_status IN ('A', 'B', 'passed')`. A partial index on allowed statuses would help. |

---

## 5. HIGH: Frontend Fetches Everything, Filters Client-Side

**Files:** `frontend/src/pages/SkillsPage.tsx`, `frontend/src/hooks/useApi.ts`, `frontend/src/api/client.ts`

### Problems

1. **5 pages independently call `listSkills()`** — each navigation triggers a full fetch of all 200k skills.
2. **No request caching**: The `useApi` hook has no cache, deduplication, or stale-while-revalidate logic. React Query or SWR would solve this.
3. **Client-side filtering on every keystroke**: `SkillsPage.tsx` runs `O(n)` `.filter()` and `.sort()` on the full skills array for every search character typed.
4. **No virtual scrolling**: All filtered results render as DOM nodes simultaneously. 10k matching skills = 10k `<NeonCard>` components in the DOM.
5. **Full ZIP download for file browser**: `SkillDetailPage.tsx` downloads the entire skill ZIP and decompresses all files into memory just to display a file tree.

### Fix

- Move filtering/sorting/search to server-side query parameters.
- Implement `useApi` caching (or adopt React Query).
- Add virtual scrolling (e.g., `react-window`) for lists.
- Lazy-load file contents (fetch individual files on click, not entire ZIP).

---

## 6. HIGH: Semver Sorting Is Computed at Query Time

**Files:** `server/src/decision_hub/infra/database.py:695-765, 768-811, 952-1026`

Every query that resolves "latest" version does:

```python
major = sa.cast(sa.func.split_part(versions_table.c.semver, ".", 1), sa.Integer)
minor = sa.cast(sa.func.split_part(versions_table.c.semver, ".", 2), sa.Integer)
patch = sa.cast(sa.func.split_part(versions_table.c.semver, ".", 3), sa.Integer)
```

This is repeated in 3 places: `resolve_version`, `resolve_latest_version`, `fetch_all_skills_for_index`. PostgreSQL executes `split_part` + `CAST` for every row on every query — these expressions cannot use B-tree indexes.

### Fix

Add `major`, `minor`, `patch` integer columns to the `versions` table. Populate them at insert time (in `insert_version`). Create an index on `(skill_id, major DESC, minor DESC, patch DESC)`. All semver ordering queries then become simple indexed lookups.

---

## 7. HIGH: `NullPool` + Per-Request Connections

**File:** `server/src/decision_hub/infra/database.py:284-301`

```python
return sa.create_engine(database_url, poolclass=NullPool, ...)
```

With `NullPool`, every request opens a new TCP connection to PgBouncer. This is appropriate for PgBouncer's transaction-mode pooling, but at high request volumes (e.g., many concurrent `dhub list` or `dhub ask` calls), PgBouncer's connection limit becomes the bottleneck. If 200k users are searching/listing, PgBouncer's default pool size (~20 connections) will queue requests.

### Fix

This is fine architecturally but ensure PgBouncer pool size is tuned. Monitor `pgbouncer SHOW POOLS` for queue depth. Consider increasing `default_pool_size` and `max_client_conn` as traffic grows.

---

## 8. MEDIUM: S3 Operations That Don't Scale

### `list_objects_v2` without pagination

**File:** `server/src/decision_hub/infra/storage.py:153-183`

```python
def list_eval_log_chunks(client, bucket, s3_prefix, after_seq=0):
    resp = client.list_objects_v2(Bucket=bucket, Prefix=s3_prefix)
    contents = resp.get("Contents", [])
```

`list_objects_v2` returns max 1000 objects per call. If an eval run produces >1000 log chunks, subsequent chunks are silently dropped (no pagination token handling).

### `delete_eval_logs` same issue

**File:** `server/src/decision_hub/infra/storage.py:196-216`

Same `list_objects_v2` without pagination. Also, `delete_objects` accepts max 1000 keys per call.

### Eval log fetching in `get_eval_run_logs`

**File:** `server/src/decision_hub/api/registry_routes.py:653-697`

The endpoint fetches **all** S3 chunks for a run, parses all events, then filters by cursor in memory. With many chunks this is wasteful — the cursor-based filtering should happen at the S3 level (fetch only chunks after the cursor's chunk sequence).

### Fix

- Add S3 pagination (handle `NextContinuationToken`).
- Use the cursor to skip S3 chunks that are entirely before the cursor position.
- Batch deletes in groups of 1000.

---

## 9. MEDIUM: Download Proxy Holds Full ZIP in Memory

**File:** `server/src/decision_hub/api/registry_routes.py:422-447`

```python
def download_skill(org_slug, skill_name, ...):
    data = download_zip_from_s3(s3_client, settings.s3_bucket, version.s3_key)
    return Response(content=data, media_type="application/zip")
```

The server downloads the entire ZIP from S3 into memory, then sends it to the client. With 50MB skill packages (the upload limit) and concurrent downloads, this is a memory bomb.

### Fix

Use `StreamingResponse` with S3's streaming body, or redirect clients directly to a pre-signed S3 URL (the `resolve_skill` endpoint already generates one — consider deprecating the proxy endpoint).

---

## 10. MEDIUM: Publish Endpoint Is a Sequential Pipeline

**File:** `server/src/decision_hub/api/registry_routes.py:207-342`

Each publish does, sequentially:
1. Read & validate ZIP (in memory, up to 50MB)
2. Parse SKILL.md
3. Run gauntlet safety checks (includes 2 LLM calls to Gemini for code + prompt safety)
4. Upload to S3
5. Insert DB records
6. Optionally spawn Modal eval

Steps 3 alone involves two synchronous HTTP calls to Gemini (code analysis + prompt analysis). Under load (many concurrent publishes), this ties up FastAPI threadpool workers for extended periods.

### Fix

- Consider making the gauntlet checks async, or running them in a background job.
- Rate-limit publish requests per user/org.
- The two Gemini calls could run in parallel (they're independent).

---

## 11. MEDIUM: CLI `dhub list` Fetches Everything

**File:** `client/src/dhub/cli/registry.py:408-459`

The CLI fetches all skills and renders them in a Rich table. At 200k skills, this will:
- Download a huge JSON response
- Render 200k rows in the terminal (unusable)

### Fix

- Add `--limit` and `--offset` CLI options.
- Default to showing the first 50 skills.
- Add `--search`, `--org`, `--sort` flags that pass server-side query parameters.

---

## 12. LOW: Single Gemini Client Per Request

**File:** `server/src/decision_hub/infra/gemini.py:9-18, 67`

```python
def create_gemini_client(api_key: str) -> dict:
    return {"api_key": api_key, "base_url": _GEMINI_API_URL}
```

A new `httpx.Client()` is created for every Gemini API call. At high volumes, this means constant TCP connection setup/teardown to Google's API.

### Fix

Use a module-level or app-level persistent `httpx.Client` with connection pooling. Close it on app shutdown.

---

## 13. LOW: Gauntlet Pipeline Creates New DB Engines

**File:** `server/src/decision_hub/api/registry_service.py:324, 398`

```python
engine = create_engine(settings.database_url)
```

Called inside `maybe_trigger_agent_assessment` and `run_assessment_background`. Each call creates a new SQLAlchemy engine (and with `NullPool`, a new connection). These should reuse the app's existing engine.

---

## Summary: Priority Ranking

| Priority | Issue | Impact at 200k |
|----------|-------|-----------------|
| **P0** | LLM search sends full index to Gemini | **Breaks at ~11.7k skills** (17x over at 200k) |
| **P0** | `/v1/skills` returns all skills unpaginated | **40MB+ responses**, server/client OOM |
| **P0** | `fetch_all_skills_for_index` full-table window function | **Seconds-long query** on every list/search |
| **P1** | No server-side search/filter/sort | Frontend unusable with client-side filtering |
| **P1** | Semver parsing at query time (no indexed columns) | Slow ORDER BY on every resolve |
| **P1** | Missing database indexes for common queries | Query degradation under load |
| **P1** | Frontend fetches all skills 5 times (no caching) | Network/memory waste |
| **P2** | S3 list/delete without pagination | Silent data loss after 1000 objects |
| **P2** | Download proxy holds full ZIP in server memory | Memory pressure under concurrent downloads |
| **P2** | Publish is a sequential blocking pipeline | Threadpool starvation under concurrent publishes |
| **P2** | `dhub list` CLI renders all skills | Unusable terminal output |
| **P3** | Gemini client created per request | Unnecessary TCP overhead |
| **P3** | New DB engine per background task | Resource waste |

---

## Recommended Implementation Order

1. **Add pagination** to `/v1/skills` (backend + CLI + frontend) — this unblocks everything else
2. **Replace LLM full-index search** with pg full-text search + LLM re-ranking of top-N
3. **Add integer semver columns** to versions table with indexes
4. **Add missing database indexes**
5. **Implement server-side filtering/sorting** on the list endpoint
6. **Add in-process TTL cache** (`cachetools.TTLCache`) for the skills list — no extra infra needed
7. **Implement frontend request caching** (React Query)
8. **Add virtual scrolling** to frontend lists
9. **Fix S3 pagination** for log chunks
10. **Stream downloads** instead of buffering full ZIPs
