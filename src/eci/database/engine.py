"""Engine/session factory. SQLite by default; any SQLAlchemy-compatible Postgres DSN works
by setting ECI_DATABASE_URL, with zero code changes (section 28: "compatible con PostgreSQL")."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from eci.config import PROJECT_ROOT, get_settings
from eci.database.models import Base


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    connect_args = {}
    if url.startswith("sqlite"):
        # Resolve relative sqlite paths against the project root, and make sure the parent dir exists.
        db_path = url.replace("sqlite:///", "", 1)
        if not db_path.startswith("/") and ":" not in db_path[:2]:
            full_path = PROJECT_ROOT / db_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{full_path}"
        connect_args = {"check_same_thread": False}
    return create_engine(url, connect_args=connect_args, future=True)


def init_db() -> None:
    """Creates all tables if they don't exist yet. Idempotent, safe to call every run."""
    Base.metadata.create_all(get_engine())


def get_session() -> Session:
    SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return SessionLocal()
