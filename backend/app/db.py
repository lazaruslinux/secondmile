"""Engine, session factory, and the per-request session dependency."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Every model subclasses this; SQLAlchemy collects their tables on
    Base.metadata, which is what the migration environment compares against."""


# pool_pre_ping spends one trivial query checking a pooled connection before
# handing it out, so a database restart hands the app a fresh connection rather
# than a dead socket and a 500.
engine: Engine | None = (
    create_engine(settings.database_url, pool_pre_ping=True) if settings.database_url else None
)

# expire_on_commit is off so a just-committed row can still be read without
# SQLAlchemy issuing another SELECT to refresh it.
SessionLocal = (
    sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    if engine is not None
    else None
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request, always closed."""
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is not set")
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
