"""Promote or demote a golf account.

    GOLF_DATABASE_URL=postgresql://... python golf/api/manage_staff.py promote pro@example.com
    GOLF_DATABASE_URL=postgresql://... python golf/api/manage_staff.py demote pro@example.com
"""
from __future__ import annotations

import os
import sys

import psycopg


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("promote", "demote"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    dsn = os.environ.get("GOLF_DATABASE_URL")
    if not dsn:
        print("GOLF_DATABASE_URL is required", file=sys.stderr)
        return 1
    role = "staff" if argv[0] == "promote" else "user"
    email = argv[1].strip().lower()
    with psycopg.connect(dsn) as conn:
        row = conn.execute("UPDATE golf_users SET role = %s WHERE email = %s RETURNING email", (role, email)).fetchone()
    if not row:
        print(f"No golf account for {email}; they need to sign up in the app first", file=sys.stderr)
        return 1
    print(f"{email} is now {'course staff' if role == 'staff' else 'a regular player'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
