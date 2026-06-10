"""Database engine/session helpers and schema creation."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

load_dotenv()


def get_engine(echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine from the DATABASE_URL environment variable."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (copy .env.example to .env).")
    return create_engine(url, echo=echo, pool_pre_ping=True)


def init_db(engine: Engine) -> None:
    """Create all tables, indexes, and generated columns if they do not exist."""
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Provide a transactional session scope that commits or rolls back."""
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
