# Reimplementation Analysis — Shortest Path from Current Main

## Branch Status

The previous implementation (`claude/github-login-skills-hjoZB`) was **151 commits
behind main**. Main has had major changes since the branch diverged:

- **Denormalized skills table** — eliminated LATERAL subqueries (commit `a0ee7f3`)
- **`_SKILL_SUMMARY_COLUMNS`** — shared column list used everywhere
- **Infinite scroll** replaced pagination on frontend pages
- **New pages**: Terms, Privacy, HowItWorks, AskModal
- **Feature flags**: `SHOW_GITHUB_BUTTONS`, `LINK_TO_MANIFEST`
- **New routes**: `seo_routes`, `taxonomy_routes`, `tracker_routes`, `org_routes`
- **`SkillSummary`** model gained many new fields (github_stars, manifest_path, etc.)
- **Layout.tsx** completely different (mobile menu, Ask button, Star on GitHub)
- **SkillDetailPage** rewritten (tabs, FileBrowser, retry logic, SEO, 532 lines)
- **client.ts** expanded with many new functions
- **types/api.ts** expanded with ~15 new interfaces

**Verdict: A merge/rebase is not viable.** The conflicts would touch nearly every
file. Reimplementation from scratch against current main is the right approach.

---

## What Can Be Reused (Copy Verbatim or Near-Verbatim)

These files from the old branch are **pure additions** with no dependency on
old main state — they can be recreated with minimal changes:

### Server (3 small changes)

| Change | Lines | Difficulty | Reuse |
|---|---|---|---|
| `settings.py` — add `github_client_secret: str = ""` | 1 line | trivial | exact |
| `github.py` — add `exchange_code_for_token()` | ~20 lines | trivial | exact copy |
| `auth_routes.py` — extract helper + add 2 endpoints + schemas | ~170 lines | medium | **needs adaptation** — old branch had `gh_user.get("avatar_url")` and the helper shape is right, but base file changed slightly |
| `registry_routes.py` — add `GET /skills/mine` | ~15 lines | trivial | needs adaptation to use `_SKILL_SUMMARY_COLUMNS` pattern |
| `database.py` — add `fetch_skills_for_orgs()` | ~40 lines | easy | **must rewrite** — old branch used LATERAL joins, main uses denormalized columns |

### Frontend — New Files (copy as-is)

These are **brand new files** that don't conflict with anything on main:

| File | Lines | Reuse |
|---|---|---|
| `contexts/AuthContext.tsx` | ~100 | exact copy |
| `components/ProtectedRoute.tsx` | ~20 | exact copy |
| `components/UserMenu.tsx` + `.module.css` | ~100 | exact copy |
| `components/ConfirmModal.tsx` + `.module.css` | ~100 | exact copy |
| `pages/AuthCallbackPage.tsx` + `.module.css` | ~80 | exact copy |
| `pages/DashboardPage.tsx` + `.module.css` | ~200 | minor adaptation (SkillSummary type changed) |
| `pages/UploadSkillPage.tsx` + `.module.css` | ~200 | exact copy |
| `pages/SettingsPage.tsx` + `.module.css` | ~150 | exact copy |

### Frontend — Modified Files (must redo against new base)

| File | Adaptation needed |
|---|---|
| `App.tsx` | Different — now has Terms/Privacy/NotFound routes. Just add `AuthProvider` wrapper + 4 new routes |
| `Layout.tsx` | **Significantly different** — now has mobile menu, AskModal, Star button, `headerRight` div. Need to integrate auth area into existing `headerRight` |
| `Layout.module.css` | Add `.authArea` and `.loginBtn` styles to existing 282-line file |
| `SkillDetailPage.tsx` | **Completely different** (532 lines, tabs, FileBrowser). Add owner toolbar in the right spot |
| `SkillDetailPage.module.css` | Add owner bar styles to existing 572-line file |
| `types/api.ts` | Add new auth types to existing ~140-line file |
| `api/client.ts` | Add auth functions to existing ~130-line file |

---

## Shortest Reimplementation Plan

### Phase 1: Server (30 min) — 4 files, ~230 lines

1. **`settings.py`** — Add 1 line: `github_client_secret: str = ""`
2. **`infra/github.py`** — Add `exchange_code_for_token()` function (~20 lines)
3. **`api/auth_routes.py`** — Extract `_authenticate_github_user()` helper from
   existing inline code. Add `WebCodeRequest`, `MeResponse` schemas.
   Add `POST /auth/github/web` and `GET /auth/me` endpoints.
   Add `avatar_url` to `TokenResponse`. (~170 lines of changes)
4. **`api/registry_routes.py`** + **`infra/database.py`** — Add
   `fetch_skills_for_orgs()` using denormalized columns (no LATERAL) and
   `GET /v1/skills/mine` endpoint (~55 lines total)

### Phase 2: Frontend — New Files (30 min) — 14 new files, ~950 lines

All pure additions, no conflicts possible:

1. `contexts/AuthContext.tsx`
2. `components/ProtectedRoute.tsx`
3. `components/UserMenu.tsx` + `.module.css`
4. `components/ConfirmModal.tsx` + `.module.css`
5. `pages/AuthCallbackPage.tsx` + `.module.css`
6. `pages/DashboardPage.tsx` + `.module.css`
7. `pages/UploadSkillPage.tsx` + `.module.css`
8. `pages/SettingsPage.tsx` + `.module.css`

### Phase 3: Frontend — Integrate into Existing Files (20 min) — 7 files

1. **`types/api.ts`** — Append auth types (~20 lines)
2. **`api/client.ts`** — Add token management + auth API functions (~80 lines)
3. **`App.tsx`** — Wrap with `AuthProvider`, add 4 routes (~15 lines)
4. **`Layout.tsx`** — Add `useAuth()`, login button / UserMenu in `headerRight`
   div, "Dashboard" nav link (~20 lines of changes)
5. **`Layout.module.css`** — Add auth area styles (~30 lines)
6. **`SkillDetailPage.tsx`** — Add owner toolbar after header div (~50 lines)
7. **`SkillDetailPage.module.css`** — Add owner bar styles (~50 lines)

### Phase 4: Quality Gates (10 min)

1. Run `make lint && make fmt`
2. Run TypeScript check: `cd frontend && npx tsc --noEmit`
3. Run ESLint: `cd frontend && npx eslint src/`
4. Run server tests: `make test-server`
5. Run client tests: `make test-client`

---

## Critical Differences from Old Implementation

### `database.py` — `fetch_skills_for_orgs()`

The old implementation used a LATERAL subquery to join skills with their latest
version. Main has since **denormalized** the latest version columns onto the
`skills_table` directly (`latest_semver`, `latest_eval_status`,
`latest_published_at`, etc.). The new implementation should use
`_SKILL_SUMMARY_COLUMNS` and the same pattern as `fetch_all_skills_for_index`:

```python
def fetch_skills_for_orgs(conn: Connection, org_ids: list[UUID]) -> list[dict]:
    """Fetch all skills belonging to the given orgs (no visibility filter)."""
    tracker_exists = (
        sa.select(sa.literal(True))
        .where(sa.and_(
            skill_trackers_table.c.repo_url == skills_table.c.source_repo_url,
            skill_trackers_table.c.enabled.is_(True),
        ))
        .correlate(skills_table)
        .exists()
        .label("has_tracker")
    )
    stmt = (
        sa.select(*_SKILL_SUMMARY_COLUMNS, tracker_exists)
        .select_from(skills_table.join(
            organizations_table, skills_table.c.org_id == organizations_table.c.id
        ))
        .where(skills_table.c.latest_semver.isnot(None))
        .where(skills_table.c.org_id.in_(org_ids))
        .order_by(skills_table.c.latest_published_at.desc())
    )
    rows = conn.execute(stmt).fetchall()
    return [_row_to_skill_summary(row) for row in rows]
```

### `Layout.tsx` — Auth UI integration point

The old Layout was simple with `justify-content: space-between`. The new Layout
has `headerRight` div containing the Star button and mobile menu toggle.
The login button / UserMenu should be inserted into this `headerRight` div,
before the menu toggle:

```tsx
<div className={styles.headerRight}>
  {/* Auth area — NEW */}
  {isAuthenticated ? <UserMenu /> : <button onClick={login}>Sign in</button>}

  {/* Existing Star button */}
  {SHOW_GITHUB_BUTTONS && <a href="..." className={styles.starBtn}>...</a>}

  {/* Existing menu toggle */}
  <button className={styles.menuToggle}>...</button>
</div>
```

### `SkillDetailPage.tsx` — Owner toolbar insertion point

The old SkillDetailPage was ~300 lines. The new one is 532 lines with tabs.
The owner toolbar should go after the `<div className={styles.header}>` and
before `<div className={styles.tabs}>`.

### `SkillSummary` type — New fields

The frontend `SkillSummary` type now has fields that didn't exist before:
`source_repo_removed`, `github_stars/forks/watchers/is_archived/license`,
`is_auto_synced`, `manifest_path`. The `DashboardPage` and other components
using `SkillSummary` will work fine since these are optional display fields.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Layout integration breaks mobile menu | Medium | High | Test mobile view after changes |
| SkillDetailPage owner bar conflicts with tab layout | Low | Medium | Insert before tabs div |
| `_SKILL_SUMMARY_COLUMNS` changes again | Low | Low | Use shared helper `_row_to_skill_summary()` |
| ESLint strict mode issues (setState in effects) | High | Low | Use same patterns from old branch (lazy init, useMemo) |

---

## Summary

| Metric | Value |
|---|---|
| **New files** | 14 frontend + 0 server = 14 |
| **Modified files** | 7 frontend + 4 server = 11 |
| **Total lines added** | ~1,500 (vs 2,855 in old branch — trimmed by reusing existing patterns) |
| **Server test changes** | 0 existing tests break (only additions) |
| **Database migrations** | 0 |
| **New dependencies** | 0 |
