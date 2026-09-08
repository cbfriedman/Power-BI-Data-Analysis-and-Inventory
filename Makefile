# =============================================================================
# Task commands. Run `make help` for the list.
#
# Windows has no make by default - use the PowerShell equivalent instead:
#   .\tasks.ps1 <task>
# =============================================================================

COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml
BACKEND  := backend
FRONTEND := frontend

.DEFAULT_GOAL := help
.PHONY: help setup env backend-install frontend-install \
        format lint typecheck test check \
        frontend-lint frontend-typecheck frontend-build frontend-check \
        up down logs ps restart compose-config migrate revision shell-db clean

help: ## Show available tasks
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Setup -------------------------------------------------------------------

env: ## Create .env from .env.example if absent
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

setup: env backend-install frontend-install ## Full local setup

backend-install: ## Install backend dependencies into backend/.venv
	cd $(BACKEND) && python -m venv .venv \
		&& .venv/bin/python -m pip install --upgrade pip \
		&& .venv/bin/python -m pip install -e ".[dev]"

frontend-install: ## Install frontend dependencies
	cd $(FRONTEND) && npm install

# --- Backend quality gates ---------------------------------------------------

format: ## Format backend code
	cd $(BACKEND) && .venv/bin/ruff format .

lint: ## Lint backend code
	cd $(BACKEND) && .venv/bin/ruff check .

typecheck: ## Type-check backend code
	cd $(BACKEND) && .venv/bin/mypy

test: ## Run backend tests
	cd $(BACKEND) && .venv/bin/pytest

check: format lint typecheck test frontend-check compose-config ## Run every gate

# --- Frontend quality gates --------------------------------------------------

frontend-lint: ## Lint frontend code
	cd $(FRONTEND) && npm run lint

frontend-typecheck: ## Type-check frontend code
	cd $(FRONTEND) && npm run typecheck

frontend-build: ## Production build of the frontend
	cd $(FRONTEND) && npm run build

frontend-check: frontend-lint frontend-typecheck frontend-build ## All frontend gates

# --- Docker ------------------------------------------------------------------

compose-config: ## Validate the Compose file
	docker compose --env-file .env.example -f infra/docker-compose.yml config --quiet

up: env ## Build and start the stack
	$(COMPOSE) up --build -d

down: ## Stop the stack (keeps the database volume)
	$(COMPOSE) down

logs: ## Follow logs from all services
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

restart: down up ## Restart the stack

# --- Database ----------------------------------------------------------------

migrate: ## Apply migrations inside the api container
	$(COMPOSE) exec api alembic upgrade head

revision: ## Autogenerate a migration: make revision m="add vendor table"
	$(COMPOSE) exec api alembic revision --autogenerate -m "$(m)"

shell-db: ## Open psql against the running database
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-prms} -d $${POSTGRES_DB:-prms}

# --- Cleanup -----------------------------------------------------------------

clean: ## Remove caches and build output (leaves .env and storage/ intact)
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache \
	       $(BACKEND)/htmlcov $(BACKEND)/.coverage $(FRONTEND)/.next
	find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} +
