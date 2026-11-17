"""Apply golf database migrations in order. Safe to run repeatedly and from several places at once.

    GOLF_DATABASE_URL=postgresql://... python golf/api/migrate.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
LOCK_KEY = 4270000


def migrate(dsn: str, quiet: bool = False) -> list[str]:
    applied_now = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS golf_schema_migrations (
                    filename text PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            done = {row[0] for row in conn.execute("SELECT filename FROM golf_schema_migrations")}
            for path in sorted(MIGRATIONS.glob("*.sql")):
                if path.name in done:
                    continue
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO golf_schema_migrations (filename) VALUES (%s)", (path.name,))
                applied_now.append(path.name)
                if not quiet:
                    print(f"Applied {path.name}")
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    return applied_now


def main() -> int:
    dsn = os.environ.get("GOLF_DATABASE_URL")
    if not dsn:
        print("GOLF_DATABASE_URL is required", file=sys.stderr)
        return 1
    applied = migrate(dsn)
    print("Golf database is up to date" if not applied else f"Golf database migrated ({len(applied)} file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
