"""Shared helpers for the golf tests: import path, a disposable PostgreSQL database per test and
an in-process client that drives the WSGI app exactly like nginx would."""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
import uuid
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "golf" / "api"))

import security  # noqa: E402

security.PBKDF2_ITERATIONS = 1_000  # keep account creation fast in tests

TEST_DSN = os.environ.get("GOLF_TEST_DATABASE_URL")
ORIGIN = "https://brettsbox.com"
_template: str | None = None


def _admin():
    import psycopg
    return psycopg.connect(TEST_DSN, autocommit=True)


def _dsn_for(name: str) -> str:
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    params = conninfo_to_dict(TEST_DSN)
    params["dbname"] = name
    return make_conninfo(**params)


def template_database() -> str:
    """Migrate one template per test run; every test copies it (fast) instead of re-migrating."""
    global _template
    if _template is None:
        import migrate
        name = f"golf_tpl_{uuid.uuid4().hex[:10]}"
        with _admin() as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
        migrate.migrate(_dsn_for(name), quiet=True)
        _template = name
    return _template


def drop_template() -> None:
    if _template:
        with _admin() as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{_template}" WITH (FORCE)')


class Client:
    def __init__(self, origin: str | None = ORIGIN, golf_header: bool = True):
        self.token: str | None = None
        self.origin = origin
        self.golf_header = golf_header

    def call(self, method: str, path: str, body: dict | None = None, query: str = "") -> tuple[int, dict]:
        import app
        raw = json.dumps(body).encode() if body is not None else b""
        environ = {"REQUEST_METHOD": method, "PATH_INFO": f"/api/golf{path}", "QUERY_STRING": query,
                   "CONTENT_LENGTH": str(len(raw)), "CONTENT_TYPE": "application/json", "wsgi.input": io.BytesIO(raw)}
        if self.golf_header:
            environ["HTTP_X_GOLF_CLIENT"] = "1"
        if self.origin:
            environ["HTTP_ORIGIN"] = self.origin
        if self.token:
            environ["HTTP_COOKIE"] = f"golf_session={self.token}"
        seen = {}

        def start_response(status, headers):
            seen["status"] = int(status.split()[0])
            seen["headers"] = headers

        payload = json.loads(b"".join(app.application(environ, start_response)))
        for key, value in seen["headers"]:
            if key == "Set-Cookie":
                self.token = value.split(";")[0].split("=", 1)[1] or None
        return seen["status"], payload

    def get(self, path, query=""):
        return self.call("GET", path, query=query)

    def post(self, path, body=None):
        return self.call("POST", path, body or {})

    def put(self, path, body=None):
        return self.call("PUT", path, body or {})

    def delete(self, path):
        return self.call("DELETE", path)

    def ok(self, method, path, body=None, query=""):
        status, payload = self.call(method, path, body, query)
        if status >= 400:
            raise AssertionError(f"{method} {path} -> {status}: {payload}")
        return payload


@unittest.skipUnless(TEST_DSN, "set GOLF_TEST_DATABASE_URL to a PostgreSQL server where the user can create databases")
class GolfDatabaseTest(unittest.TestCase):
    """Each test gets its own database copied from the migrated template."""

    STAFF_EMAIL = "pro@example.com"

    def setUp(self):
        template = template_database()
        self.db_name = f"golf_t_{uuid.uuid4().hex[:12]}"
        with _admin() as conn:
            conn.execute(f'CREATE DATABASE "{self.db_name}" TEMPLATE "{template}"')
        self.dsn = _dsn_for(self.db_name)
        self._env = {key: os.environ.get(key) for key in ("GOLF_DATABASE_URL", "GOLF_BOOTSTRAP_STAFF_EMAIL", "GOLF_ALLOWED_ORIGINS")}
        os.environ["GOLF_DATABASE_URL"] = self.dsn
        os.environ["GOLF_BOOTSTRAP_STAFF_EMAIL"] = self.STAFF_EMAIL
        os.environ["GOLF_ALLOWED_ORIGINS"] = ORIGIN
        self.staff = self.signup("Pat Pro", self.STAFF_EMAIL)
        app_info = self.staff.ok("GET", "/app")
        self.today = app_info["today"]
        self.tomorrow = self.day(1)

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        with _admin() as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{self.db_name}" WITH (FORCE)')

    def day(self, offset: int) -> str:
        from datetime import date
        return (date.fromisoformat(self.today) + timedelta(days=offset)).isoformat()

    def signup(self, name: str, email: str | None = None, **extra) -> Client:
        client = Client()
        email = email or f"{name.split()[0].lower()}-{uuid.uuid4().hex[:6]}@example.com"
        client.ok("POST", "/auth/register", {"email": email, "password": "correct horse battery", "full_name": name, **extra})
        client.email = email
        client.me = client.ok("GET", "/app")["user"]
        return client

    def db(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row)

    def sql(self, query: str, params=()):
        with self.db() as conn:
            cur = conn.execute(query, params)
            return cur.fetchall() if cur.description else None

    def book(self, client: Client, time: str = "09:00", date: str | None = None, **body):
        return client.call("POST", "/bookings", {"date": date or self.tomorrow, "time": time, **body})

    def sheet_slot(self, client: Client, time: str, date: str | None = None) -> dict:
        sheet = client.ok("GET", "/tee-sheet", query=f"date={date or self.tomorrow}")
        return next(slot for slot in sheet["slots"] if slot["time"] == time)

    def set_counts(self, **counts):
        self.staff.ok("PUT", "/settings", counts)
