from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import sessionmaker

from app.adapters.memory.seed import seed_all
from app.adapters.sql.repository import SqlRepository
from app.config import Settings
from app.container import Container, build_container
from app.db.session import create_db_engine, validate_url
from app.main import create_app
from app.models.tables import Base

# Set TEST_STORAGE=postgres and TEST_DATABASE_URL to run the whole suite
# against real PostgreSQL. Default (unset) keeps the self-contained
# in-memory backend so the suite runs anywhere without a database.
_PG_TEST_URL = os.getenv("TEST_DATABASE_URL", "").strip()
_PG_TEST = os.getenv("TEST_STORAGE", "").strip().lower() == "postgres" and bool(_PG_TEST_URL)
_PG_SCHEMA = "pytest_staging"


@pytest.fixture
def container() -> Iterator[Container]:
    settings = Settings(page_size_max=100, max_file_size_bytes=64)
    if not _PG_TEST:
        yield build_container(settings)
        return

    # PostgreSQL mode: the entire test runs inside one transaction that is
    # rolled back at the end, so the live database is never polluted.
    #  - A private schema is created first (transactional DDL) and used as
    #    the ONLY entry of search_path — no public fallback, otherwise
    #    create_all would see the real tables and skip building fresh ones,
    #    and writes would fall through to the demo data. The rollback
    #    discards schema, seed and every test write together.
    #  - Repository sessions join the outer transaction through savepoints
    #    (join_transaction_mode="create_savepoint").
    # The migration-0001 database triggers live in the public schema and are
    # not duplicated for the staging schema; the ORM guards (app.db.guards)
    # enforce the same Spec 10.2 rules on flush.
    engine = create_db_engine(validate_url(_PG_TEST_URL))
    connection = engine.connect()
    outer = connection.begin()
    try:
        connection.exec_driver_sql(f"DROP SCHEMA IF EXISTS {_PG_SCHEMA} CASCADE")
        connection.exec_driver_sql(f"CREATE SCHEMA {_PG_SCHEMA}")
        connection.exec_driver_sql(f"SET LOCAL search_path = {_PG_SCHEMA}")
        Base.metadata.create_all(connection)
        factory = sessionmaker(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        yield build_container(settings, repository=SqlRepository(factory))
    finally:
        outer.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture
def app(container: Container):
    return create_app(container)


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
