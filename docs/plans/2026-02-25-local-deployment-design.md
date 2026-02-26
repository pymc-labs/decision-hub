# Local Deployment Mode

## Goal

Add `make deploy-local` to run the full Decision Hub stack locally for development, using Docker Compose for infrastructure (Postgres + MinIO) and local processes for the app (uvicorn + Vite). The local stack is fully isolated from dev/prod databases and S3 buckets. Evals still execute on Modal cloud via the deployed dev app.

## Architecture

```
docker-compose-local.yml (persistent, started once)
  postgres (pgvector/pgvector:pg16)   port 5432
  minio    (minio/minio)              port 9000 (S3 API), 9001 (console UI)

Local processes (started per session)
  uvicorn  (FastAPI, --reload)        port 8000
  vite     (React HMR)               port 5173 -> proxies /v1/ to :8000
```

```
Browser :5173  -->  Vite (HMR + proxy /v1/)  -->  FastAPI :8000
                                                    |         |
                                              Postgres :5432  MinIO :9000
                                                    |
                                              Modal cloud (evals via fn.spawn)
```

## Decisions

- **Database**: Docker Postgres with pgvector (not Supabase CLI). Persistent volume survives restarts; reset manually with `docker compose down -v`.
- **S3**: MinIO in Docker Compose. S3-compatible, same boto3 client with `endpoint_url` override. Reusable in CI/CD.
- **Frontend**: Vite dev server with proxy to local FastAPI. No build step needed for dev.
- **Evals**: Spawn to already-deployed dev Modal app via `modal.Function.from_name("decision-hub-dev", ...)`. Requires `make deploy-dev` to have been run at least once.
- **Cron jobs**: Don't run locally. Tracker polling and nightly crawl stay on Modal.
- **`DHUB_ENV=local`**: No new flag logic. `create_settings()` already loads `.env.{DHUB_ENV}`, so `local` just loads `.env.local`. No conditionals needed.

## Files to Create

### `docker-compose-local.yml` (repo root)

Two services:
- **postgres**: `pgvector/pgvector:pg16`, port 5432, named volume `dhub-pg-data`, creates `decision_hub` database
- **minio**: `minio/minio`, ports 9000 (S3 API) + 9001 (web console), named volume `dhub-minio-data`, command `server /data --console-address ":9001"`

### `server/.env.local` (gitignored)

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/decision_hub
S3_BUCKET=decision-hub-local
S3_ENDPOINT_URL=http://localhost:9000
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
GITHUB_CLIENT_ID=<from .env.dev>
JWT_SECRET=<generate fresh>
JWT_ALGORITHM=HS256
JWT_EXPIRY_HOURS=8760
FERNET_KEY=<generate fresh>
MODAL_APP_NAME=decision-hub-dev
GOOGLE_API_KEY=<from .env.dev>
GEMINI_MODEL=gemini-2.5-flash
LOG_LEVEL=DEBUG
```

## Files to Modify

### `server/src/decision_hub/settings.py`

Add one field:
```python
s3_endpoint_url: str = ""
```

Empty string (default) means real AWS S3. Set to `http://localhost:9000` for MinIO.

### `server/src/decision_hub/infra/storage.py`

Update `create_s3_client()` to accept and pass `endpoint_url`:
```python
def create_s3_client(region, access_key_id, secret_access_key, endpoint_url=""):
    kwargs = dict(region_name=region, aws_access_key_id=access_key_id, aws_secret_access_key=secret_access_key)
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)
```

### `server/src/decision_hub/api/app.py`

Update `create_s3_client()` call to pass `settings.s3_endpoint_url`.

### `frontend/vite.config.ts`

Add dev server proxy so `/v1/` requests forward to the local FastAPI:
```ts
server: {
  proxy: {
    "/v1": "http://localhost:8000",
    "/cli": "http://localhost:8000",
    "/auth": "http://localhost:8000",
  }
}
```

### `Makefile`

New targets:
- `local-up`: `docker compose -f docker-compose-local.yml up -d` + create MinIO bucket + run migrations
- `local-down`: `docker compose -f docker-compose-local.yml down`
- `local-reset`: `docker compose -f docker-compose-local.yml down -v` (destroys data)
- `local-server`: `cd server && DHUB_ENV=local uv run --package decision-hub-server uvicorn decision_hub.api.app:create_app --host 0.0.0.0 --port 8000 --reload`
- `local-frontend`: `cd frontend && npm run dev`

### `.gitignore`

Add `.env.local` entry.

## CI/CD Reuse

The same `docker-compose-local.yml` can be used in GitHub Actions for integration tests:
```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    env: { POSTGRES_PASSWORD: postgres, POSTGRES_DB: decision_hub }
    ports: ["5432:5432"]
  minio:
    image: minio/minio
    ports: ["9000:9000"]
```

## What Does NOT Change

- All API routes, middleware, auth, logging
- Database schema and migrations (same SQL)
- Frontend application code (only vite.config.ts proxy)
- Modal integration for evals
- Dev and prod deployments
