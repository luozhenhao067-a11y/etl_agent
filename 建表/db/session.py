"""Engine and session factory for the PostgreSQL control-plane database.

The connection string is read from the ``DATABASE_URL`` environment variable
only; no credentials are hardcoded (prom/make_sql.txt constraint). The URL
must use the psycopg 3 driver: a bare ``postgresql://`` prefix would make
SQLAlchemy select the uninstalled psycopg2 dialect.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:  # 评审目录（建表/）内直接运行
    from db.guards import register_guards
except ModuleNotFoundError:  # 合入 backendpoint/app/db/ 之后
    from app.db.guards import register_guards

_DRIVERS = ("postgresql://", "postgres://")


def database_url() -> str:
    """Return the validated DATABASE_URL, forcing the psycopg 3 dialect."""

    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is required, e.g. "
            "postgresql+psycopg://user:password@host:5432/etl_agent"
        )
    if url.startswith(_DRIVERS):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError(
            "DATABASE_URL must use the postgresql+psycopg:// driver prefix "
            "(psycopg 3); got: " + url.split("://", 1)[0] + "://"
        )
    return url


def create_db_engine():
    """Create the application engine with the immutability guards attached."""

    register_guards()
    return create_engine(database_url(), pool_pre_ping=True)


def make_session_factory(engine) -> sessionmaker:
    """Session factory for repository implementations (keeps rows as dicts)."""

    return sessionmaker(bind=engine, expire_on_commit=False)
