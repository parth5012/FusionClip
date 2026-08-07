"""Shared FastAPI dependencies.

`get_db` replaces the manual ``SessionLocal()`` / ``try`` / ``finally`` blocks
that were repeated in every handler of the original monolithic ``main.py``.
Tests swap it out through ``app.dependency_overrides[get_db]``.
"""

from typing import Generator

from sqlalchemy.orm import Session

from app.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session and guarantee it is closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
