"""Apply golf database migrations in order. Safe to run repeatedly and from several places at once.

    GOLF_DATABASE_URL=postgresql://... python golf/api/migrate.py

Applied migrations are recorded in golf_schema_migrations and never run twice; each one runs in a
single transaction together with its record.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
LOCK_KEY = 4270000
# A database that already has the initial schema but no record of it (created before the record
# existed) gets the record instead of a second, failing run of the migration.
BASELINE = ("001_initial.sql", ("golf_settings", "golf_players", "golf_users", "golf_sessions", "golf_products",
                                "golf_entitlements", "golf_entitlement_uses", "golf_bookings", "golf_booking_players",
                                "golf_rental_units", "golf_rentals", "golf_ledger"))


def text(value) -> str:
    return value.decode("utf-8") if isinstance(value, (bytes, bytearray, memoryview)) else str(value)


def migrate(dsn: str, quiet: bool = False) -> list[str]:
    applied_now = []
    # UTF-8 even on an SQL_ASCII database, where text would otherwise come back as bytes and no
    # recorded filename would ever match.
    with psycopg.connect(dsn, autocommit=True, client_encoding="UTF8") as conn:
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
            done = {text(row[0]) for row in conn.execute("SELECT filename FROM golf_schema_migrations")}
            for path in sorted(MIGRATIONS.glob("*.sql")):
                if path.name in done:
                    continue
                if path.name == BASELINE[0] and record_existing_baseline(conn):
                    if not quiet:
                        print(f"{path.name}: schema already present, recorded as applied")
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


def record_existing_baseline(conn) -> bool:
    name, tables = BASELINE
    present = {text(row[0]) for row in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() AND tablename = ANY(%s)", (list(tables),))}
    if not present:
        return False
    missing = sorted(set(tables) - present)
    if missing:
        raise RuntimeError(f"The database has part of the golf schema but is missing {', '.join(missing)}; "
                           "restore it from a backup or recreate the database before migrating.")
    conn.execute("INSERT INTO golf_schema_migrations (filename) VALUES (%s) ON CONFLICT DO NOTHING", (name,))
    return True


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
