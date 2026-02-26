# Local Deployment Mode — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `make deploy-local` to run the full Decision Hub stack locally with isolated Postgres + MinIO, for fast development iteration without touching dev/prod.

**Architecture:** Docker Compose provides Postgres (pgvector) and MinIO (S3-compatible). FastAPI runs via uvicorn with `--reload`. Vite dev server proxies API calls to the local backend. Evals spawn to the deployed dev Modal app.

**Tech Stack:** Docker Compose, pgvector/pgvector:pg16, minio/minio, uvicorn, Vite proxy

**Design doc:** `docs/plans/2026-02-25-local-deployment-design.md`

---

### Task 1: Add `s3_endpoint_url` to Settings

**Files:**
- Modify: `server/src/decision_hub/settings.py:16-20`

**Step 1: Add the field**

In `server/src/decision_hub/settings.py`, add `s3_endpoint_url` after the existing S3 fields (after line 20):

```python
    # S3 Storage
    s3_bucket: str
    aws_region: str = "us-east-1"
    aws_access_key_id: str
    aws_secret_access_key: str
    s3_endpoint_url: str = ""  # Set to MinIO URL for local dev (e.g. http://localhost:9000)
```

**Step 2: Run existing tests to verify no regression**

Run: `cd /Users/lfiaschi/workspace/decision-hub2 && uv run --package decision-hub-server --extra dev pytest server/tests/ -v -x -q 2>&1 | tail -5`
Expected: All existing tests still pass.

**Step 3: Commit**

```bash
git add server/src/decision_hub/settings.py
git commit -m "feat: add s3_endpoint_url setting for local S3-compatible storage"
```

---

### Task 2: Update `create_s3_client` to support endpoint URL

**Files:**
- Modify: `server/src/decision_hub/infra/storage.py:19-35`

**Step 1: Update the function signature and implementation**

Replace the existing `create_s3_client` in `server/src/decision_hub/infra/storage.py`:

```python
def create_s3_client(
    region: str,
    access_key_id: str,
    secret_access_key: str,
    endpoint_url: str = "",
) -> BaseClient:
    """Create an S3 client with explicit credentials.

    Args:
        region: AWS region name (e.g. 'us-east-1').
        access_key_id: AWS access key ID.
        secret_access_key: AWS secret access key.
        endpoint_url: Optional endpoint URL for S3-compatible services (e.g. MinIO).

    Returns:
        A configured boto3 S3 client.
    """
    kwargs: dict = {
        "region_name": region,
        "aws_access_key_id": access_key_id,
        "aws_secret_access_key": secret_access_key,
    }
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)
```

**Step 2: Run existing tests**

Run: `cd /Users/lfiaschi/workspace/decision-hub2 && uv run --package decision-hub-server --extra dev pytest server/tests/ -v -x -q 2>&1 | tail -5`
Expected: All tests pass (no callers pass endpoint_url yet, default is empty string).

**Step 3: Commit**

```bash
git add server/src/decision_hub/infra/storage.py
git commit -m "feat: add endpoint_url param to create_s3_client for S3-compatible backends"
```

---

### Task 3: Pass `endpoint_url` at all 4 call sites

**Files:**
- Modify: `server/src/decision_hub/api/app.py:110-114`
- Modify: `server/src/decision_hub/scripts/crawler/processing.py:115-119`
- Modify: `server/src/decision_hub/api/registry_service.py:571-575`
- Modify: `server/src/decision_hub/domain/tracker_service.py:530-534`

**Step 1: Update `app.py`**

In `server/src/decision_hub/api/app.py`, change lines 110-114 from:

```python
    s3_client = create_s3_client(
        settings.aws_region,
        settings.aws_access_key_id,
        settings.aws_secret_access_key,
    )
```

to:

```python
    s3_client = create_s3_client(
        settings.aws_region,
        settings.aws_access_key_id,
        settings.aws_secret_access_key,
        settings.s3_endpoint_url,
    )
```

**Step 2: Update `crawler/processing.py`**

In `server/src/decision_hub/scripts/crawler/processing.py`, change the call (~line 115) from:

```python
        s3_client = create_s3_client(
            region=settings.aws_region,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
        )
```

to:

```python
        s3_client = create_s3_client(
            region=settings.aws_region,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
            endpoint_url=settings.s3_endpoint_url,
        )
```

**Step 3: Update `registry_service.py`**

In `server/src/decision_hub/api/registry_service.py`, change the call (~line 571) from:

```python
            s3_client = create_s3_client(
                region=settings.aws_region,
                access_key_id=settings.aws_access_key_id,
                secret_access_key=settings.aws_secret_access_key,
            )
```

to:

```python
            s3_client = create_s3_client(
                region=settings.aws_region,
                access_key_id=settings.aws_access_key_id,
                secret_access_key=settings.aws_secret_access_key,
                endpoint_url=settings.s3_endpoint_url,
            )
```

**Step 4: Update `tracker_service.py`**

In `server/src/decision_hub/domain/tracker_service.py`, change the call (~line 530) from:

```python
            s3_client = create_s3_client(
                region=settings.aws_region,
                access_key_id=settings.aws_access_key_id,
                secret_access_key=settings.aws_secret_access_key,
            )
```

to:

```python
            s3_client = create_s3_client(
                region=settings.aws_region,
                access_key_id=settings.aws_access_key_id,
                secret_access_key=settings.aws_secret_access_key,
                endpoint_url=settings.s3_endpoint_url,
            )
```

**Step 5: Run existing tests**

Run: `cd /Users/lfiaschi/workspace/decision-hub2 && uv run --package decision-hub-server --extra dev pytest server/tests/ -v -x -q 2>&1 | tail -5`
Expected: All tests pass (s3_endpoint_url defaults to "" in all mocked settings).

**Step 6: Commit**

```bash
git add server/src/decision_hub/api/app.py server/src/decision_hub/scripts/crawler/processing.py server/src/decision_hub/api/registry_service.py server/src/decision_hub/domain/tracker_service.py
git commit -m "feat: pass s3_endpoint_url through all create_s3_client call sites"
```

---

### Task 4: Add Vite dev server proxy

**Files:**
- Modify: `frontend/vite.config.ts`

**Step 1: Add proxy config**

In `frontend/vite.config.ts`, update the `defineConfig` to include a `server.proxy` section:

```ts
export default defineConfig({
  plugins: [react(), noindexPlugin()],
  server: {
    proxy: {
      "/v1": "http://localhost:8000",
      "/cli": "http://localhost:8000",
      "/auth": "http://localhost:8000",
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          "syntax-highlighter": ["react-syntax-highlighter"],
          vendor: ["react", "react-dom", "react-router-dom"],
        },
      },
    },
  },
});
```

**Step 2: Verify frontend builds**

Run: `cd /Users/lfiaschi/workspace/decision-hub2/frontend && npx tsc -b`
Expected: No type errors.

**Step 3: Commit**

```bash
git add frontend/vite.config.ts
git commit -m "feat: add Vite dev server proxy for local API forwarding"
```

---

### Task 5: Create `docker-compose-local.yml`

**Files:**
- Create: `docker-compose-local.yml` (repo root)

**Step 1: Create the file**

Create `docker-compose-local.yml` at the repo root:

```yaml
# Local development infrastructure.
# Start: docker compose -f docker-compose-local.yml up -d
# Stop:  docker compose -f docker-compose-local.yml down
# Reset: docker compose -f docker-compose-local.yml down -v
services:
  postgres:
    image: pgvector/pgvector:pg16
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: decision_hub
    volumes:
      - dhub-pg-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

  minio:
    image: minio/minio
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - dhub-minio-data:/data
    command: server /data --console-address ":9001"
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      timeout: 5s
      retries: 5

  # One-shot init container: creates the S3 bucket if it doesn't exist.
  minio-init:
    image: minio/mc
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 minioadmin minioadmin &&
      mc mb --ignore-existing local/decision-hub-local &&
      echo 'Bucket ready'
      "

volumes:
  dhub-pg-data:
  dhub-minio-data:
```

**Step 2: Verify Docker Compose config is valid**

Run: `cd /Users/lfiaschi/workspace/decision-hub2 && docker compose -f docker-compose-local.yml config --quiet`
Expected: No errors.

**Step 3: Commit**

```bash
git add docker-compose-local.yml
git commit -m "feat: add docker-compose-local.yml for local Postgres + MinIO"
```

---

### Task 6: Create `server/.env.local`

**Files:**
- Create: `server/.env.local` (gitignored by existing `.env.*` rule)

**Step 1: Generate fresh secrets**

Run these commands to generate values:
```bash
# JWT secret
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# Fernet key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Step 2: Extract reusable keys from .env.dev**

Read `GOOGLE_API_KEY` and `GITHUB_CLIENT_ID` from `server/.env.dev`.

**Step 3: Create the file**

Create `server/.env.local` with the values:

```env
# Local development environment
# Infrastructure: docker compose -f docker-compose-local.yml up -d

# Database (local Postgres from docker-compose-local.yml)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/decision_hub

# S3 Storage (local MinIO from docker-compose-local.yml)
S3_BUCKET=decision-hub-local
S3_ENDPOINT_URL=http://localhost:9000
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin

# GitHub OAuth (reuse dev app — callback works on any localhost port)
GITHUB_CLIENT_ID=<value from .env.dev>

# JWT (fresh local-only secret)
JWT_SECRET=<generated value>
JWT_ALGORITHM=HS256
JWT_EXPIRY_HOURS=8760

# Encryption (fresh local-only key)
FERNET_KEY=<generated value>

# Modal (spawn evals to deployed dev app)
MODAL_APP_NAME=decision-hub-dev

# Gemini (reuse dev API key)
GOOGLE_API_KEY=<value from .env.dev>
GEMINI_MODEL=gemini-2.5-flash

# Logging
LOG_LEVEL=DEBUG
```

**Step 4: Verify settings load**

Run: `cd /Users/lfiaschi/workspace/decision-hub2/server && DHUB_ENV=local uv run --package decision-hub-server python -c "from decision_hub.settings import create_settings; s = create_settings(); print(f'DB: {s.database_url[:30]}... S3: {s.s3_endpoint_url} Bucket: {s.s3_bucket}')"`
Expected: `DB: postgresql://postgres:postg... S3: http://localhost:9000 Bucket: decision-hub-local`

**Note:** This file is NOT committed (covered by `.env.*` in `.gitignore`).

---

### Task 7: Add Makefile targets

**Files:**
- Modify: `Makefile`

**Step 1: Add local dev targets**

Add a new section to the `Makefile` between the Deployment and Data maintenance sections:

```makefile
# ---------------------------------------------------------------------------
# Local development
# ---------------------------------------------------------------------------

local-up: ## Start local infra (Postgres + MinIO), run migrations, create bucket
	docker compose -f docker-compose-local.yml up -d
	@echo "Waiting for Postgres..."
	@until docker compose -f docker-compose-local.yml exec -T postgres pg_isready -U postgres > /dev/null 2>&1; do sleep 1; done
	cd server && DHUB_ENV=local uv run --package decision-hub-server python ../scripts/run_migrations.py
	@echo ""
	@echo "=== Local infra ready ==="
	@echo "  Postgres: localhost:5432"
	@echo "  MinIO S3: localhost:9000"
	@echo "  MinIO UI: http://localhost:9001 (minioadmin/minioadmin)"

local-down: ## Stop local infra (data preserved)
	docker compose -f docker-compose-local.yml down

local-reset: ## Stop local infra and destroy all data
	docker compose -f docker-compose-local.yml down -v

local-server: ## Start local FastAPI server with hot reload
	cd server && DHUB_ENV=local uv run --package decision-hub-server uvicorn decision_hub.api.app:create_app --host 0.0.0.0 --port 8000 --reload

local-frontend: ## Start Vite dev server (proxies API to localhost:8000)
	cd frontend && npm run dev
```

**Step 2: Update .PHONY**

Add the new targets to the `.PHONY` line at the top of the Makefile.

**Step 3: Verify make help**

Run: `cd /Users/lfiaschi/workspace/decision-hub2 && make help | grep local`
Expected: All 5 local targets appear with their descriptions.

**Step 4: Commit**

```bash
git add Makefile
git commit -m "feat: add make local-up/down/reset/server/frontend targets"
```

---

### Task 8: Smoke test the full local stack

**Step 1: Start infrastructure**

Run: `cd /Users/lfiaschi/workspace/decision-hub2 && make local-up`
Expected: Postgres + MinIO start, migrations apply, "Local infra ready" printed.

**Step 2: Start the server**

Run (in a separate terminal): `cd /Users/lfiaschi/workspace/decision-hub2 && make local-server`
Expected: uvicorn starts, shows "Decision Hub app ready (log_level=DEBUG)".

**Step 3: Test API health**

Run: `curl -s http://localhost:8000/v1/stats | python3 -m json.tool`
Expected: JSON response with registry stats (empty DB, so zeros).

**Step 4: Test MinIO connectivity**

Run: `curl -s http://localhost:8000/v1/skills | python3 -m json.tool`
Expected: JSON response with empty skills list (no S3 errors in server logs).

**Step 5: Start frontend**

Run (in a separate terminal): `cd /Users/lfiaschi/workspace/decision-hub2 && make local-frontend`
Expected: Vite starts on port 5173.

**Step 6: Test frontend proxy**

Run: `curl -s http://localhost:5173/v1/stats | python3 -m json.tool`
Expected: Same JSON as Step 3 (proxied through Vite).

**Step 7: Clean up**

Run: `cd /Users/lfiaschi/workspace/decision-hub2 && make local-down`
Expected: Containers stop, data preserved.

---

### Task 9: Update .env.example and design doc

**Files:**
- Modify: `server/.env.example`

**Step 1: Add `S3_ENDPOINT_URL` to .env.example**

Add after the `AWS_SECRET_ACCESS_KEY` line in `server/.env.example`:

```env
# S3-compatible endpoint URL (leave empty for real AWS S3, set for MinIO/LocalStack)
# S3_ENDPOINT_URL=http://localhost:9000
```

**Step 2: Commit**

```bash
git add server/.env.example
git commit -m "docs: add S3_ENDPOINT_URL to .env.example"
```
