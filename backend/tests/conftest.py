"""Shared pytest fixtures.

The whole suite runs offline. Before any application module is imported the
environment is pinned to an in-memory SQLite database and a local Redis URL
(never actually connected to — the client objects are replaced by fakeredis),
and the S3 helpers are monkeypatched so no MinIO round-trip is attempted.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("FUSIONCLIP_SECRET_KEY", "unit-test-master-key")

import fakeredis  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base  # noqa: E402
from app.deps import get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402

# Importing models registers every table on Base.metadata.
import app.models  # noqa: E402,F401


@pytest.fixture()
def engine():
    """A single-connection in-memory SQLite engine with the full schema."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(bind=eng)
        eng.dispose()


@pytest.fixture()
def db_session(engine):
    """A SQLAlchemy session bound to the in-memory schema."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def fake_redis():
    """An in-process Redis replacement."""
    return fakeredis.FakeStrictRedis()


@pytest.fixture()
def stub_storage(monkeypatch):
    """Replace every S3 helper used by the routers with in-memory stubs.

    Returns the dict of uploaded objects so tests can assert on writes.
    """
    uploaded: dict = {}
    deleted: list = []

    def _upload_object(data, object_name, content_type="application/octet-stream"):
        uploaded[object_name] = {"data": data, "content_type": content_type}
        return True

    def _generate_url(object_name, expires_in=3600):
        return f"http://test-minio/{object_name}"

    def _delete_object(object_name):
        deleted.append(object_name)
        uploaded.pop(object_name, None)
        return True

    def _list_workspace_files(prefix=""):
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        return {"current_dir": prefix, "directories": [], "files": []}

    for module in ("app.storage", "app.routers.storage", "app.routers.generate", "app.routers.media"):
        for name, impl in (
            ("upload_object", _upload_object),
            ("generate_url", _generate_url),
            ("delete_object", _delete_object),
            ("list_workspace_files", _list_workspace_files),
        ):
            monkeypatch.setattr(f"{module}.{name}", impl, raising=False)

    return {"uploaded": uploaded, "deleted": deleted}


@pytest.fixture()
def stub_redis(monkeypatch, fake_redis):
    """Point the router and Celery task modules at fakeredis."""
    monkeypatch.setattr("app.routers.tasks.redis_client", fake_redis, raising=False)
    monkeypatch.setattr("app.tasks.redis_client", fake_redis, raising=False)
    return fake_redis


@pytest.fixture()
def client(db_session, stub_storage, stub_redis):
    """TestClient with get_db overridden onto the in-memory session.

    The lifespan handler is deliberately not run (TestClient is used without a
    context manager), so no live Postgres or MinIO connection is attempted.
    """

    def _override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
