import os

# Keep tests away from the real database file (the app lifespan calls init_db()).
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (registers tables)
from app.config import Settings, get_settings
from app.db import Base, get_session
from app.main import app


@pytest.fixture
def session():
    # One shared in-memory database per test.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with TestingSession() as s:
        yield s
    engine.dispose()


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    # Never read the real .env in tests: it holds real keys.
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
