import os
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL_ENV_VAR = "DATABASE_URL"


class Base(DeclarativeBase):
    """Base class for future SQLAlchemy models."""


def get_database_url() -> str:
    """Return the configured database URL or fail with a clear message."""
    database_url = os.getenv(DATABASE_URL_ENV_VAR)
    if not database_url:
        raise RuntimeError(
            f"{DATABASE_URL_ENV_VAR} is not set. "
            "Use a PostgreSQL URL such as "
            "postgresql+psycopg://user:password@localhost:5432/coursemate."
        )

    return database_url


@lru_cache
def get_engine() -> Engine:
    """Create and cache the application database engine."""
    return create_engine(get_database_url(), pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Create and cache the application's SQLAlchemy session factory."""
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        expire_on_commit=False,
    )


def get_db() -> Generator[Session, None, None]:
    """Provide a database session for a FastAPI dependency."""
    with get_session_factory()() as session:
        yield session
