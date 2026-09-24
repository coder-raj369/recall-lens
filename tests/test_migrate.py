import os

import psycopg
import pytest

from recall_lens.db.migrate import MIGRATIONS_DIR, migrate

DATABASE_URL = os.environ.get("DATABASE_URL")
requires_db = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not set")


def test_migration_versions_are_unique_and_ordered():
    versions = [p.stem for p in sorted(MIGRATIONS_DIR.glob("*.sql"))]
    prefixes = [v.split("_", 1)[0] for v in versions]
    assert versions, "no migrations found"
    assert all(p.isdigit() and len(p) == 4 for p in prefixes)
    assert len(set(prefixes)) == len(prefixes)


@requires_db
def test_migrate_creates_schema_and_is_idempotent():
    migrate(DATABASE_URL)
    assert migrate(DATABASE_URL) == []

    with psycopg.connect(DATABASE_URL) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
        }
        extensions = {row[0] for row in conn.execute("SELECT extname FROM pg_extension")}

    assert {"recalls", "recall_identifiers", "recall_chunks", "schema_migrations"} <= tables
    assert "vector" in extensions


@requires_db
def test_recall_upsert_key_and_full_text_search():
    migrate(DATABASE_URL)
    with psycopg.connect(DATABASE_URL) as conn:  # every write is rolled back explicitly
        insert = (
            "INSERT INTO recalls (agency, source_id, title, hazard, raw, content_hash)"
            " VALUES ('cpsc', 'TEST-1', 'Space heater recall', 'Fire hazard', '{}', 'h')"
        )
        conn.execute(insert)
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(insert)
        conn.rollback()

        conn.execute(insert)
        hit = conn.execute(
            "SELECT source_id FROM recalls WHERE search_tsv @@ plainto_tsquery('english', 'fire')"
        ).fetchone()
        assert hit == ("TEST-1",)
        conn.rollback()
