# Convenience wrapper around Docker Compose. The same commands work without
# make — see README.md. (On Windows, run the `docker compose ...` commands
# directly or use `make` from Git Bash / WSL.)

COMPOSE      := docker compose
DEV_COMPOSE  := docker compose -f docker-compose.yml -f docker-compose.dev.yml
ALLINONE_COMPOSE := docker compose -f docker-compose.allinone.yml

.PHONY: help up down dev dev-down allinone allinone-down build logs ps restart secrets clean test

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Start the full stack (build if needed), http://localhost:6200
	$(COMPOSE) up -d --build

down: ## Stop the stack (keep data volumes)
	$(COMPOSE) down

dev: ## Start with hot reload, UI http://localhost:6203, API http://localhost:6201
	$(DEV_COMPOSE) up --build

dev-down: ## Stop the dev stack
	$(DEV_COMPOSE) down

allinone: ## Start the single-container image (build if needed), http://localhost:6204, no signup
	$(ALLINONE_COMPOSE) up -d --build

allinone-down: ## Stop the all-in-one container (keep its data volume)
	$(ALLINONE_COMPOSE) down

build: ## Build images without starting
	$(COMPOSE) build

logs: ## Tail logs from all services
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

restart: ## Restart all services
	$(COMPOSE) restart

secrets: ## Print the auto-generated secrets (first start only)
	$(COMPOSE) logs backend | grep -A 6 "AUTO-GENERATED" || echo "No auto-generated secrets in logs."

clean: ## Stop and remove everything INCLUDING data volumes
	$(COMPOSE) down -v

test: ## Run backend tests inside a one-off container
	$(COMPOSE) run --rm --no-deps --entrypoint "" backend uv run pytest
