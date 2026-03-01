# GitHub Login & Skill Management — Feature Specification

## 1. Feature Overview

Add GitHub OAuth login to the frontend so authenticated users can manage their
skills directly from the browser. Today the frontend is read-only; all writes
go through the CLI (`dhub publish`, `dhub login`). This feature bridges that gap.

### User capabilities once logged in

| Capability | API endpoint (exists today) | Notes |
|---|---|---|
| View own skills | **NEW** `GET /v1/skills/mine` | Filtered by user's org membership |
| Delete a skill | `DELETE /v1/skills/{org}/{skill}` | Already auth-gated |
| Republish a skill | `POST /v1/publish` | Already auth-gated |
| Upload a new skill | `POST /v1/publish` | Already auth-gated |
| Toggle visibility | `PUT /v1/skills/{org}/{skill}/visibility` | Already auth-gated |
| Manage API keys | `GET/POST/DELETE /v1/keys` | Already auth-gated (keys_routes.py) |

**Key insight:** Almost all server endpoints already exist and are auth-gated.
The main work is frontend + one new server endpoint + one new auth flow.

---

## 2. Authentication Flow

### Current state (CLI only)

The CLI uses **GitHub Device Flow OAuth** — the user runs `dhub login`, gets a
device code, visits github.com to authorize, then the CLI polls until complete.
The server returns a JWT with `{sub, username, github_orgs}` claims.

### New: Web Application Flow (Authorization Code Grant)

The browser needs a redirect-based flow:

1. User clicks **"Sign in with GitHub"** in the header
2. Frontend redirects to:
   ```
   https://github.com/login/oauth/authorize?client_id={ID}&redirect_uri={CALLBACK_URL}&scope=read:org
   ```
3. User authorizes on GitHub
4. GitHub redirects back to `/auth/callback?code=XXXXX`
5. Frontend sends the `code` to **`POST /auth/github/web`** (new endpoint)
6. Server exchanges code for GitHub access token using `client_secret`
7. Server fetches user profile, syncs orgs (same as Device Flow)
8. Server returns JWT + username + orgs + avatar_url
9. Frontend stores JWT in localStorage, sets auth context

**Requires:** `GITHUB_CLIENT_SECRET` on the server (the same OAuth App already
has one — Device Flow only needs `client_id`, Web Flow needs both).

---

## 3. Server Changes Required

### 3.1 Settings (`settings.py`)

Add one field:

```python
github_client_secret: str = ""
```

### 3.2 GitHub infra (`infra/github.py`)

Add one function — `exchange_code_for_token()`:

```python
async def exchange_code_for_token(client_id: str, client_secret: str, code: str) -> str:
    """Exchange a GitHub authorization code for an access token (Web Flow)."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GITHUB_ACCESS_TOKEN_URL,
            data={"client_id": client_id, "client_secret": client_secret, "code": code},
            headers={"Accept": "application/json"},
        )
    response.raise_for_status()
    data = response.json()
    if "access_token" in data:
        return data["access_token"]
    error = data.get("error", "unknown_error")
    desc = data.get("error_description", "no description")
    raise RuntimeError(f"GitHub OAuth code exchange failed: {error} - {desc}")
```

### 3.3 Auth routes (`api/auth_routes.py`)

Three additions:

**a) Extract shared `_authenticate_github_user()` helper** — DRYs up the code
that's currently inline in `exchange_token()` (upsert user, sync orgs, create
JWT). Both Device Flow and Web Flow use it.

**b) `POST /auth/github/web`** — Accepts `{code: str}`, calls
`exchange_code_for_token()`, then `_authenticate_github_user()`.

**c) `GET /auth/me`** — Validates JWT, returns `{username, orgs, avatar_url}`.
Used by the frontend on page load to check if the stored token is still valid.

**d) Update `TokenResponse`** to include `avatar_url: str | None = None`.

### 3.4 Registry routes (`api/registry_routes.py`)

Add one endpoint — `GET /v1/skills/mine`:

```python
@router.get("/skills/mine", response_model=list[SkillSummary])
def list_my_skills(conn, current_user):
    user_org_ids = list_user_org_ids(conn, current_user.id)
    rows = fetch_skills_for_orgs(conn, user_org_ids)
    return [SkillSummary(...) for row in rows]
```

### 3.5 Database (`infra/database.py`)

Add one function — `fetch_skills_for_orgs(conn, org_ids)`:

Fetches all skills belonging to the given org IDs. Uses the existing
`_SKILL_SUMMARY_COLUMNS` and denormalized latest-version columns (no LATERAL
joins needed — main already eliminated those). No visibility filtering since
the user owns these orgs.

---

## 4. Frontend Changes Required

### 4.1 Auth Infrastructure (new files)

| File | Purpose |
|---|---|
| `contexts/AuthContext.tsx` | React context: `user`, `loading`, `isAuthenticated`, `login()`, `logout()`, `setUserFromToken()`. On mount: checks localStorage JWT, validates via `GET /auth/me` |
| `components/ProtectedRoute.tsx` | Wrapper that redirects to `/` if not authenticated |
| `components/UserMenu.tsx` | Dropdown: avatar, username, Dashboard link, Settings link, Sign Out |
| `components/ConfirmModal.tsx` | Reusable destructive-action modal with optional type-to-confirm |

### 4.2 API Client additions (`api/client.ts`)

| Function | HTTP call |
|---|---|
| `getStoredToken()` / `setStoredToken()` / `clearStoredToken()` | localStorage get/set/remove |
| `getAuthHeaders()` | Returns `{Authorization: "Bearer <token>"}` or `{}` |
| `fetchAuthJSON<T>(path, init?)` | Like `fetchJSON` but injects auth header |
| `exchangeGitHubCode(code)` | `POST /auth/github/web` |
| `getCurrentUser()` | `GET /auth/me` |
| `getMySkills()` | `GET /v1/skills/mine` |
| `deleteSkill(org, skill)` | `DELETE /v1/skills/{org}/{skill}` |
| `updateSkillVisibility(org, skill, visibility)` | `PUT /v1/skills/{org}/{skill}/visibility` |
| `publishSkill(formData)` | `POST /v1/publish` |
| `listApiKeys()` | `GET /v1/keys` |
| `storeApiKey(name, value)` | `POST /v1/keys` |
| `deleteApiKey(name)` | `DELETE /v1/keys/{name}` |

### 4.3 New Pages

| Page | Route | Description |
|---|---|---|
| `AuthCallbackPage` | `/auth/callback` | Extracts `code` from URL, exchanges for JWT, redirects to `/dashboard` |
| `DashboardPage` | `/dashboard` | Lists user's skills via `/v1/skills/mine`. Per-skill actions: toggle visibility, republish (prefills Upload page), delete (with ConfirmModal) |
| `UploadSkillPage` | `/dashboard/upload` | Form: org dropdown, skill name, version, visibility toggle, drag-and-drop zip. Calls `POST /v1/publish` |
| `SettingsPage` | `/dashboard/settings` | Lists stored API keys (name + date). Add new key form (ANTHROPIC_API_KEY, GITHUB_TOKEN). Delete key |

### 4.4 Modified Files

| File | Changes |
|---|---|
| `App.tsx` | Wrap routes with `<AuthProvider>`. Add routes: `/auth/callback`, `/dashboard`, `/dashboard/upload`, `/dashboard/settings` (last 3 with `<ProtectedRoute>`) |
| `Layout.tsx` | Add auth-aware header: "Sign in" button when unauthenticated, `<UserMenu>` when authenticated. Add "Dashboard" nav link when logged in |
| `Layout.module.css` | Styles for `.authArea`, `.loginBtn` with neon glow effects |
| `SkillDetailPage.tsx` | Add owner toolbar when `user.orgs.includes(orgSlug)`: toggle visibility, republish, delete buttons |
| `SkillDetailPage.module.css` | Styles for `.ownerBar` and owner action buttons |
| `types/api.ts` | Add: `AuthUser`, `TokenResponse`, `MeResponse`, `KeySummary`, `PublishResponse` |
| `featureFlags.ts` | (optional) Add `SHOW_LOGIN = true` flag |

### 4.5 Environment Variables

| Variable | Where | Purpose |
|---|---|---|
| `GITHUB_CLIENT_SECRET` | Server `.env.dev` / `.env.prod` | Web OAuth code exchange |
| `VITE_GITHUB_CLIENT_ID` | Frontend `.env` | OAuth redirect URL construction |

---

## 5. User Flow

### Sign In
```
[Header: "Sign in with GitHub"] → GitHub authorize page → /auth/callback → /dashboard
```

### Dashboard
```
/dashboard
├── Your Skills list (cards with name, version, grade, visibility badge)
│   ├── [Toggle visibility] — inline "Public"/"Private" toggle
│   ├── [Republish] → /dashboard/upload?org=X&name=Y (prefilled)
│   └── [Delete] → ConfirmModal (type skill name to confirm)
├── [Upload New Skill] → /dashboard/upload
└── [Settings] → /dashboard/settings
```

### Skill Detail Page (owner view)
```
/skills/{org}/{skill}
└── Owner toolbar (shown only for org members)
    ├── [Make Public/Private]
    ├── [Republish] → /dashboard/upload?org=X&name=Y
    └── [Delete] → ConfirmModal
```

### Settings
```
/dashboard/settings
├── Stored API Keys table (name, date)
│   └── [Delete] each
├── Add Key form (dropdown: ANTHROPIC_API_KEY, GITHUB_TOKEN + value input)
└── Info card about Fernet encryption at rest
```

---

## 6. Styling Notes

The frontend uses the "neon 80s retro" theme: dark background, cyan/pink/purple/green
neon colors, Orbitron/Share Tech Mono/Rajdhani fonts. All new components must match
this aesthetic. Use CSS Modules (`.module.css`) for all new styles.

---

## 7. What Does NOT Need to Change

- **Device Flow** — untouched, CLI keeps working
- **JWT format/signing** — unchanged, same secret/algorithm
- **All existing API endpoints** — no modifications needed
- **Database schema** — no migrations needed (all tables exist)
- **Rate limiting** — existing limiters cover the endpoints
- **Test infrastructure** — existing patterns (respx mocks, conftest fixtures)
