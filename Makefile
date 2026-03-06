.PHONY: help lint lint-frontend fmt typecheck test test-client test-server test-shared test-frontend test-slow check-migrations check-schema-drift install-hooks deploy-dev deploy-prod deploy-local local-down local-reset publish publish-cli backfill tracker-health

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------

lint: lint-frontend ## Run all linters (ruff + frontend)
	uvx ruff@0.15.3 check .
	uvx ruff@0.15.3 format --check .

typecheck: ## Run mypy type checks
	uvx mypy client/src/ server/src/ shared/src/

lint-frontend: ## Run frontend type check + ESLint
	cd frontend && npx tsc -b && npx eslint .

fmt: ## Auto-fix lint issues and format code
	uvx ruff@0.15.3 check --fix .
	uvx ruff@0.15.3 format .

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test: test-client test-server test-shared test-frontend ## Run all tests

test-client: ## Run client tests
	uv run --package dhub-cli --extra dev pytest client/tests/ -v --cov=dhub --cov-report=term-missing

test-server: ## Run server tests (excludes slow LLM regression tests)
	uv run --package decision-hub-server --extra dev pytest server/tests/ -v -m "not slow" --cov=decision_hub --cov-report=term-missing

test-shared: ## Run shared tests
	uv run --package dhub-core --extra dev pytest shared/tests/ -v

test-frontend: ## Run frontend tests
	cd frontend && npx vitest run

test-slow: ## Run slow LLM regression tests (requires GOOGLE_API_KEY in env or server/.env.dev)
	cd server && uv run --package decision-hub-server --extra dev pytest tests/ -v -m slow -s

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

deploy-local: ## Start local stack: Postgres + MinIO + API + frontend
	docker compose -f docker-compose-local.yml up -d
	@echo "Waiting for Postgres..."
	@until docker compose -f docker-compose-local.yml exec -T postgres pg_isready -U postgres > /dev/null 2>&1; do sleep 1; done
	cd server && DHUB_ENV=local uv run --package decision-hub-server python ../scripts/run_migrations.py
	@echo ""
	@echo "=== Starting servers ==="
	@trap 'kill 0' INT TERM; \
		(cd server && DHUB_ENV=local uv run --package decision-hub-server python -m uvicorn decision_hub.api.app:create_app --host 0.0.0.0 --port 8000 --reload) & \
		(cd frontend && npm run dev) & \
		sleep 3; \
		echo ""; \
		echo "=== Local deploy ready ==="; \
		echo "    URL: http://localhost:5173"; \
		echo "    API: http://localhost:8000"; \
		echo "    MinIO: http://localhost:9001 (minioadmin/minioadmin)"; \
		wait

local-down: ## Stop local stack (data preserved)
	@-lsof -ti:8000,5173 | xargs kill 2>/dev/null
	docker compose -f docker-compose-local.yml down

local-reset: ## Stop local stack and destroy all data
	@-lsof -ti:8000,5173 | xargs kill 2>/dev/null
	docker compose -f docker-compose-local.yml down -v

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
