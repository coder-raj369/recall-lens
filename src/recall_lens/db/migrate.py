"""Apply SQL migrations in filename order, each exactly once.

Usage: DATABASE_URL=postgresql://... python -m recall_lens.db.migrate
"""

import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Arbitrary constant; serializes concurrent runners (e.g. several app replicas starting at once).
_LOCK_ID = 7265_1001


def migrate(conninfo: str) -> list[str]:
    """Apply pending migrations and return the versions applied by this call."""
    applied: list[str] = []
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_ID,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version text PRIMARY KEY,"
            " applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.stem in done:
                continue
            # Each migration and its bookkeeping row commit together or not at all.
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
            applied.append(path.stem)
    return applied


def main() -> None:
    conninfo = os.environ.get("DATABASE_URL")
    if not conninfo:
        sys.exit("DATABASE_URL is not set")
    applied = migrate(conninfo)
    print(f"Applied: {', '.join(applied)}" if applied else "Database is up to date.")


if __name__ == "__main__":
    main()
