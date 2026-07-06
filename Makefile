PYTHON ?= 3.12
HOST ?= 127.0.0.1
PORT ?= 8000
COMPOSE := docker compose

.PHONY: help sync sync-dev run test clean init-env up up-tunnel down restart ps logs logs-app logs-tunnel

help:
	@echo "Available targets:"
	@echo "  make sync              Install runtime dependencies with uv"
	@echo "  make sync-dev          Install runtime and dev dependencies with uv"
	@echo "  make run               Start the server directly on $(HOST):$(PORT)"
	@echo "  make init-env          Create .env from .env.example if it does not exist"
	@echo "  make up                Start the local container stack on 127.0.0.1:18000"
	@echo "  make up-tunnel         Start the stack plus a named Cloudflare Tunnel"
	@echo "  make down              Stop and remove the compose stack"
	@echo "  make restart           Restart the local container stack"
	@echo "  make ps                Show compose service status"
	@echo "  make logs              Follow logs for all services"
	@echo "  make logs-app          Follow logs for the app service"
	@echo "  make logs-tunnel       Follow logs for the cloudflared service"
	@echo "  make test              Run test suite"
	@echo "  make clean             Remove local runtime/test artifacts"

sync:
	uv sync --python $(PYTHON)

sync-dev:
	uv sync --python $(PYTHON) --extra dev

run:
	YAHOO_SHOPPING_MCP_HOST=$(HOST) YAHOO_SHOPPING_MCP_PORT=$(PORT) uv run yahoo-shopping-mcp

init-env:
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from .env.example"; else echo ".env already exists"; fi

up:
	$(COMPOSE) up -d --build

up-tunnel:
	$(COMPOSE) --profile tunnel up -d --build

down:
	$(COMPOSE) down

restart: down up

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

logs-app:
	$(COMPOSE) logs -f app

logs-tunnel:
	$(COMPOSE) logs -f cloudflared

test:
	uv run pytest

clean:
	rm -rf .pytest_cache .local
