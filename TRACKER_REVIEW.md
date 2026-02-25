# GitHub Tracker Feature — Full Review

**Date:** 2026-02-19

---

## 1. Scalability to 100k+ repos

**Current architecture: won't scale.** The design works fine for tens-to-hundreds of trackers but has fundamental bottlenecks at 100k+:

| Priority | Issue | Detail |
|----------|-------|--------|
| **P0** | **Serial single-container processing** | `check_trackers` cron runs every 5 min in a single Modal function, processes trackers in a `for` loop sequentially. At batch_size=100, cycling through 100k trackers would take ~35 days. |
| **P0** | **GitHub REST rate limit** | Each tracker check = 1 `GET /repos/{o}/{r}/commits/{branch}` call. 5,000 req/hr limit -> would exhaust the budget in 3 minutes at 100k scale. |
| **P1** | **Zero rate-limit awareness** | Unlike the crawler's `GitHubClient` (which tracks `x-ratelimit-remaining` and sleeps), `tracker.py` creates a **new `httpx.Client` per call**, never reads rate-limit headers, has no backoff. When you hit 403, all remaining trackers in the batch also fail. |
| **P1** | **No fan-out** | No use of Modal's `.map()` or `.starmap()` to parallelize tracker processing across containers. |
| **P2** | **Due-check query not fully indexable** | `claim_due_trackers` filters on `last_checked_at + poll_interval_minutes * INTERVAL '1 minute' < now()` -- the arithmetic expression can't use the partial index efficiently at scale. |
| **P3** | **Full `git clone` on every change** | No incremental fetch, sparse checkout, or caching. |

**GraphQL opportunity:** The GitHub GraphQL API allows batching multiple repo queries in a single request:

```graphql
query {
  repo1: repository(owner: "o1", name: "r1") {
    ref(qualifiedName: "refs/heads/main") { target { oid } }
  }
  repo2: repository(owner: "o2", name: "r2") {
    ref(qualifiedName: "refs/heads/main") { target { oid } }
  }
  # ... up to ~100 aliases per request
}
```

This would turn 100 REST calls into 1-2 GraphQL calls. GraphQL rate limit is 5,000 points/hr (each field = 1 point), so same budget, but **dramatically fewer HTTP round-trips** and you could detect rate limits once per batch rather than per-tracker.

**Biggest win at scale:** Switch from polling to **GitHub webhooks** (push events). Eliminates the polling problem entirely.

---

## 2. Currently enabled on prod/dev?

**The cron is running, but the CLI to create trackers is broken.**

- `check_trackers` Modal cron runs every 5 min on **both** dev and prod. If the table is empty, it logs `"Found 0 due tracker(s)"` and exits.
- There are **two paths** to create trackers:
  1. **`dhub track add`** -- fully implemented in `client/src/dhub/cli/track.py`, but **the `track_app` is never registered** in `client/src/dhub/cli/app.py`. The command is **unreachable dead code**. Users cannot run `dhub track add`.
  2. **Auto-tracking on `dhub publish`** -- when you `dhub publish` from a GitHub URL, `_ensure_tracker()` in `registry.py:369-423` auto-creates a tracker. This path **does work**.
- The crawler does **not** create trackers (confirmed by CLAUDE.md: "Crawled skills are not auto-tracked").
- There are no seed data or migration scripts inserting tracker rows.

**To confirm whether any trackers actually exist, query the DB:**
```sql
SELECT repo_url, branch, enabled, last_checked_at, last_error, created_at
FROM skill_trackers ORDER BY created_at DESC;
```

---

## 3. Reporting on failures and sync times

**Functional but minimal -- no proactive alerting.**

| Capability | Status |
|------------|--------|
| `last_error` stored in DB | Yes -- truncated to 500 chars, cleared on success |
| `last_checked_at` (when polled) | Yes -- updated every cycle |
| `last_published_at` (when new version created) | Yes -- only on successful publish |
| SHA not advanced on total failure (auto-retry) | Yes -- failed commits are retried next cycle |
| Contextual error hints in CLI | Yes -- `dhub track status` suggests adding a GitHub token for 403/404 errors |
| Structured/JSON logging | No -- plain-text loguru messages with `{}` placeholders |
| Admin cross-user view | No -- `GET /v1/trackers` is user-scoped only |
| Alerting (email/Slack/webhook) | No |
| Health dashboard | No |

The only admin path is raw SQL or grepping Modal logs:
```bash
modal app logs decision-hub-dev 2>&1 | grep -i "tracker\|check_trackers"
```

---

## 4. Frontend presentation

**The frontend is almost completely unaware of trackers.**

| What | Status |
|------|--------|
| GitHub source link on skill detail page | **Yes** -- `source_repo_url` renders a GitHub icon + "Source" link on `SkillDetailPage.tsx:223-232`. But this is set for **any** GitHub-sourced skill, not just tracked ones. |
| "Published by tracker" indicator | **No** -- the `author` field contains `"tracker:<uuid>"` which renders as-is (ugly raw UUID). No friendly badge or label. |
| Last sync time | **No** -- not shown anywhere in the UI. |
| Sync failure status | **No** -- not shown anywhere in the UI. |
| Tracker management page | **No** -- no `/trackers` or `/admin` routes. Zero frontend components for tracker CRUD. |
| "Auto-synced" badge on skill cards | **No** |

The frontend API client (`frontend/src/api/client.ts`) has **zero tracker-related functions**. The TypeScript types (`frontend/src/types/api.ts`) have **no `Tracker` interface**.

---

## Summary of critical findings

1. **`dhub track` CLI is dead code** -- `track_app` never registered in `app.py`. Only auto-tracking via `dhub publish` works.
2. **Won't scale past ~1,200 trackers/hour** -- serial processing, no rate-limit awareness, no fan-out, no GraphQL batching.
3. **No admin observability** -- user-scoped API only, no cross-user dashboards, no alerting.
4. **Frontend shows `tracker:<uuid>` as the author** -- no clean UX for tracked skills (no sync badge, no last-sync time, no failure indicators).
