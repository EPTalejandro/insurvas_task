# Shortcuts for the whole project. `make help` lists them.
# Every command runs from the repository root.

.DEFAULT_GOAL := help
CLI = cd backend && uv run python -m app.cli

help: ## Show this list
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

setup: ## Install everything and create backend/.env and the database
	cd backend && uv sync
	cd frontend && pnpm install
	test -f backend/.env || cp backend/.env.example backend/.env
	$(CLI) init-db
	$(CLI) seed

build: ## Build the frontend (the API serves it from frontend/dist)
	cd frontend && pnpm build

run: build ## Build the frontend and serve app + API on http://localhost:8000
	cd backend && uv run fastapi run app/main.py --port 8000

dev-api: ## Backend only, with reload, on :8000 (docs at /docs)
	cd backend && uv run fastapi dev app/main.py

dev-web: ## Vite dev server on :5173, proxying /api to :8000
	cd frontend && pnpm dev

discover: ## Find competitors on YouTube (about 3,000 quota units)
	$(CLI) discover

refresh: ## Collect, label and rank (add DISCOVER=1 to discover first)
	$(CLI) refresh $(if $(DISCOVER),--discover)

reset: ## Delete ALL stored data, then seed the search terms again
	$(CLI) reset-db --yes
	$(CLI) seed

test: ## Backend tests, lint and format check, then frontend lint and build
	cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
	cd frontend && pnpm lint && pnpm build

.PHONY: help setup build run dev-api dev-web discover refresh reset test
