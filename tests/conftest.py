import os

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from recall_lens.db.migrate import migrate


@pytest.fixture(scope="session")
def database_url():
    """A throwaway database created next to DATABASE_URL and dropped after the session."""
    base = os.environ.get("DATABASE_URL")
    if not base:
        pytest.skip("DATABASE_URL is not set")
    name = f"recall_lens_test_{os.getpid()}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield make_conninfo(base, dbname=name)
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def conn(database_url):
    """A migrated connection whose data is truncated after each test."""
    migrate(database_url)
    with psycopg.connect(database_url) as connection:
        yield connection
        connection.rollback()
        connection.execute("TRUNCATE recalls, ingestion_runs RESTART IDENTITY CASCADE")
        connection.commit()
