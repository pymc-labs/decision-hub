.PHONY: help lint lint-frontend fmt typecheck test test-client test-server check-migrations install-hooks deploy-dev deploy-prod publish

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

test: test-client test-server ## Run all tests

test-client: ## Run client tests
	uv run --package dhub-cli --extra dev pytest client/tests/ -v

test-server: ## Run server tests
	uv run --package decision-hub-server --extra dev pytest server/tests/ -v

# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

check-migrations: ## Check for duplicate migration sequence numbers
	python scripts/check_migrations.py

migrate-dev: ## Apply migrations to dev database
	cd server && DHUB_ENV=dev uv run --package decision-hub-server python -c "\
		from decision_hub.settings import create_settings; \
		from decision_hub.infra.database import create_engine, metadata; \
		settings = create_settings('dev'); \
		engine = create_engine(settings.database_url); \
		metadata.create_all(engine); \
		print('Dev migrations applied successfully')"

migrate-prod: ## Apply migrations to prod database (use with care)
	cd server && DHUB_ENV=prod uv run --package decision-hub-server python -c "\
		from decision_hub.settings import create_settings; \
		from decision_hub.infra.database import create_engine, metadata; \
		settings = create_settings('prod'); \
		engine = create_engine(settings.database_url); \
		metadata.create_all(engine); \
		print('Prod migrations applied successfully')"

# ---------------------------------------------------------------------------
# Deployment
# ---------------------------------------------------------------------------

deploy-dev: ## Build frontend + deploy to dev Modal
	DHUB_ENV=dev ./scripts/deploy.sh

deploy-prod: ## Build frontend + deploy to prod Modal
	DHUB_ENV=prod ./scripts/deploy.sh

publish: ## Build and publish dhub-cli to PyPI
	./scripts/publish.sh

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

install-hooks: ## Install pre-commit hooks
	uvx pre-commit install
