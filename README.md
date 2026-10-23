# Competitor Content Intelligence

Collects public content from life insurance agents and agencies (YouTube, Instagram, Reddit),
labels each post (topic, format, hook), ranks posts by performance, and highlights the best
content and strongest competitors.

| Part | Stack |
|---|---|
| `backend/` | Python 3.13, FastAPI, SQLAlchemy 2, SQLite, uv |
| `frontend/` | React + TypeScript (Vite), Pico.css, pnpm |

## Prerequisites
- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Node.js 22 and pnpm 10 (`corepack install -g pnpm@10`)

## Backend
```bash
cd backend
cp .env.example .env
uv sync
uv run python -m app.cli init-db
uv run fastapi dev app/main.py   # http://localhost:8000/docs
```
Tests and lint:
```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Frontend
```bash
cd frontend
pnpm install
pnpm dev     # http://localhost:5173 (proxies /api to :8000)
pnpm lint
pnpm build
```
