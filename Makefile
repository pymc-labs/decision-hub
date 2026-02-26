.PHONY: help lint lint-frontend fmt typecheck test test-client test-server test-frontend check-migrations check-schema-drift install-hooks deploy-dev deploy-prod publish publish-cli local-up local-down local-reset local-server local-frontend backfill tracker-health

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------

lint: lint-frontend ## Run all linters (ruff + frontend)
	uvx ruff check .
	uvx ruff format --check .

typecheck: ## Run mypy type checks
	uvx mypy client/src/ server/src/ shared/src/

lint-frontend: ## Run frontend type check + ESLint
	cd frontend && npx tsc -b && npx eslint .

fmt: ## Auto-fix lint issues and format code
	uvx ruff check --fix .
	uvx ruff format .

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test: test-client test-server test-frontend ## Run all tests

test-client: ## Run client tests
	uv run --package dhub-cli --extra dev pytest client/tests/ -v

test-server: ## Run server tests
	uv run --package decision-hub-server --extra dev pytest server/tests/ -v

test-frontend: ## Run frontend tests
	cd frontend && npx vitest run

# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

check-migrations: ## Check for duplicate migration sequence numbers
	python scripts/check_migrations.py

migrate-dev: ## Apply SQL migrations to dev database
	cd server && DHUB_ENV=dev uv run --package decision-hub-server python ../scripts/run_migrations.py

migrate-prod: ## Apply SQL migrations to prod database (use with care)
	cd server && DHUB_ENV=prod uv run --package decision-hub-server python ../scripts/run_migrations.py

check-schema-drift: ## Check that SQL migrations match SQLAlchemy metadata (needs DATABASE_URL)
	uv run --package decision-hub-server python scripts/check_schema_drift.py

# ---------------------------------------------------------------------------
# Deployment
# ---------------------------------------------------------------------------

deploy-dev: ## Build frontend + deploy to dev Modal
	DHUB_ENV=dev ./scripts/deploy.sh

deploy-prod: ## Build frontend + deploy to prod Modal
	DHUB_ENV=prod ./scripts/deploy.sh

publish: ## Build and publish dhub-cli to PyPI (low-level, prefer publish-cli)
	./scripts/publish.sh

publish-cli: ## Publish CLI to PyPI (BUMP=patch|minor|major, BREAKING=1 to sync servers)
	./scripts/release-cli.sh $(or $(BUMP),patch) $(if $(BREAKING),--sync,)

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

# ---------------------------------------------------------------------------
# Data maintenance
# ---------------------------------------------------------------------------

backfill: ## Run all backfills: categories, embeddings, org metadata (needs DHUB_ENV)
	cd server && unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN && \
		DHUB_ENV=$(or $(DHUB_ENV),dev) uv run --package decision-hub-server \
		python scripts/backfill_categories.py
	cd server && unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN && \
		DHUB_ENV=$(or $(DHUB_ENV),dev) uv run --package decision-hub-server \
		python -m decision_hub.scripts.backfill_embeddings
	cd server && unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN && \
		DHUB_ENV=$(or $(DHUB_ENV),dev) uv run --package decision-hub-server \
		python -m decision_hub.scripts.backfill_org_metadata --github-token "$$(gh auth token)"

# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------

tracker-health: ## Show tracker health summary (dev by default, override with DHUB_ENV=prod)
	cd server && DHUB_ENV=$(or $(DHUB_ENV),dev) uv run --package decision-hub-server \
		python -m decision_hub.scripts.tracker_health

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

install-hooks: ## Install pre-commit hooks
	uvx pre-commit install
