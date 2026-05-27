# Owner: Mohammad

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


# Engine and session factory are initialised lazily by init_db() called at startup.
# They must not be created at import time because DATABASE_URL comes from Vault.
_engine = None
_session_factory = None


def init_db(database_url: str) -> None:
    """Initialise the engine from a URL fetched from Vault at startup."""
    global _engine, _session_factory
    _engine = create_engine(database_url, pool_pre_ping=True)
    _session_factory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    os.environ["DATABASE_URL"] = database_url  # make available to Alembic CLI


def SessionLocal() -> Session:
    """Return a new DB session. Must be called after init_db()."""
    if _session_factory is None:
        raise RuntimeError("Database not initialised — call init_db() at startup")
    return _session_factory()


def get_db():
    """FastAPI dependency: yields a DB session and closes it after the request."""
    if _session_factory is None:
        raise RuntimeError("Database not initialised — call init_db() at startup")
    db: Session = _session_factory()
    try:
        yield db
    finally:
        db.close()
