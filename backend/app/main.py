from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import init_db
from app.routers import competitors, insights, meta, posts, sources

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Competitor Content Intelligence", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    # Writes exist only for keywords. Their JSON bodies need a preflight, so a page from another
    # origin cannot change them from a browser.
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


for module in (meta, posts, competitors, insights, sources):
    app.include_router(module.router, prefix="/api")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def mount_frontend(application: FastAPI, dist: Path) -> bool:
    """Serve the built frontend at `/`, after the API routes so `/api/...` keeps winning.

    The UI keeps its state in the query string and has no routes of its own, so plain static
    files are enough. Without a build (`pnpm build`) the API runs alone, as in development.
    """
    if not (dist / "index.html").is_file():
        return False
    application.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return True


mount_frontend(app, FRONTEND_DIST)
