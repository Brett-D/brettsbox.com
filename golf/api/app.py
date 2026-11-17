"""WSGI entry point for the golf API (gunicorn app:application, bound to 127.0.0.1 only).

nginx relays https://brettsbox.com/api/golf/* here. Writes need the X-Golf-Client header (which a
cross-site form cannot send without a CORS preflight this API never grants) and, when the browser
sends one, an Origin from GOLF_ALLOWED_ORIGINS.
"""
from __future__ import annotations

import json
import os
import re
import sys
import traceback
from datetime import date, datetime, time
from http.cookies import CookieError, SimpleCookie
from urllib.parse import parse_qs

import psycopg

import domain
import service
from domain import RuleError
from service import ApiError

COOKIE_NAME = "golf_session"
COOKIE_PATH = "/api/golf"
MAX_BODY_BYTES = 64 * 1024
STATUS_TEXT = {200: "OK", 201: "Created", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
               404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large",
               415: "Unsupported Media Type", 500: "Internal Server Error", 503: "Service Unavailable"}


def env_origins() -> set[str]:
    raw = os.environ.get("GOLF_ALLOWED_ORIGINS", "https://brettsbox.com,https://www.brettsbox.com")
    return {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}


def bootstrap_email() -> str:
    return os.environ.get("GOLF_BOOTSTRAP_STAFF_EMAIL", "").strip().lower()


def to_json(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return domain.hhmm(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


class Request:
    def __init__(self, environ: dict):
        self.environ = environ
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        self.path = environ.get("PATH_INFO", "") or "/"
        self.query = {key: values[0] for key, values in parse_qs(environ.get("QUERY_STRING", "")).items()}
        self.set_cookie: str | None = None
        self.token = None
        cookies = SimpleCookie()
        try:
            cookies.load(environ.get("HTTP_COOKIE", ""))
        except CookieError:
            pass
        if COOKIE_NAME in cookies:
            self.token = cookies[COOKIE_NAME].value
        self._body = None

    def body(self) -> dict:
        if self._body is not None:
            return self._body
        try:
            length = int(self.environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            raise ApiError(400, "Invalid Content-Length") from None
        if length > MAX_BODY_BYTES:
            raise ApiError(413, "Request is too large")
        raw = self.environ["wsgi.input"].read(length) if length else b""
        if not raw:
            self._body = {}
            return self._body
        if not self.environ.get("CONTENT_TYPE", "").startswith("application/json"):
            raise ApiError(415, "Send JSON")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "Request body must be valid JSON") from None
        if not isinstance(value, dict):
            raise ApiError(400, "Request body must be a JSON object")
        self._body = value
        return value


def session_cookie(token: str | None) -> str:
    parts = [f"{COOKIE_NAME}={token or ''}", f"Path={COOKIE_PATH}", "HttpOnly", "SameSite=Lax",
             f"Max-Age={service.SESSION_DAYS * 86400 if token else 0}"]
    if os.environ.get("GOLF_COOKIE_SECURE", "1") != "0":
        parts.append("Secure")
    return "; ".join(parts)


ROUTES: list[tuple[str, re.Pattern, str | None, object]] = []


def route(method: str, pattern: str, auth: str | None = None):
    """auth: None for public, 'user' for any signed-in account, 'staff' for course staff."""
    def register(handler):
        ROUTES.append((method, re.compile(f"^/api/golf{pattern}$"), auth, handler))
        return handler
    return register


ID = r"(\d{1,18})"


# --------------------------------------------------------------------------- app and accounts

@route("GET", "/app")
def get_app(req, conn, user):
    with conn.cursor() as cur:
        settings = service.load_settings(cur)
    return {"course": service.settings_json(settings), "today": service.course_today(settings),
            "now": service.now(), "user": service.public_user(user)}


@route("POST", "/auth/register")
def post_register(req, conn, user):
    token = service.register(conn, req.body(), bootstrap_email())
    req.set_cookie = session_cookie(token)
    return 201, {"user": service.public_user(service.user_for_token(conn, token))}


@route("POST", "/auth/login")
def post_login(req, conn, user):
    token = service.login(conn, req.body())
    req.set_cookie = session_cookie(token)
    return {"user": service.public_user(service.user_for_token(conn, token))}


@route("POST", "/auth/logout")
def post_logout(req, conn, user):
    service.logout(conn, req.token)
    req.set_cookie = session_cookie(None)
    return {"ok": True}


@route("GET", "/me", "user")
def get_me(req, conn, user):
    return service.player_profile(conn, user, user["player_id"])


@route("PUT", "/me", "user")
def put_me(req, conn, user):
    service.update_player(conn, user, user["player_id"], req.body(), staff=False)
    return service.player_profile(conn, user, user["player_id"])


# --------------------------------------------------------------------------- tee sheet

@route("GET", "/tee-sheet")
def get_tee_sheet(req, conn, user):
    return service.tee_sheet(conn, user, req.query.get("date", ""))


@route("POST", "/bookings", "user")
def post_booking(req, conn, user):
    return 201, {"booking_id": service.create_booking(conn, user, req.body())}


@route("POST", f"/bookings/{ID}/join", "user")
def post_join(req, conn, user, booking_id):
    service.join_booking(conn, user, int(booking_id), req.body())
    return {"ok": True}


@route("POST", f"/bookings/{ID}/leave", "user")
def post_leave(req, conn, user, booking_id):
    service.leave_booking(conn, user, int(booking_id))
    return {"ok": True}


@route("PUT", f"/bookings/{ID}/riding-carts", "user")
def put_riding_carts(req, conn, user, booking_id):
    service.set_riding_carts(conn, user, int(booking_id), req.body())
    return {"ok": True}


@route("DELETE", f"/bookings/{ID}", "staff")
def delete_booking(req, conn, user, booking_id):
    service.cancel_booking(conn, user, int(booking_id))
    return {"ok": True}


@route("PUT", f"/booking-players/{ID}", "user")
def put_booking_player(req, conn, user, booking_player_id):
    service.update_player_options(conn, user, int(booking_player_id), req.body())
    return {"ok": True}


@route("DELETE", f"/booking-players/{ID}", "user")
def delete_booking_player(req, conn, user, booking_player_id):
    service.remove_booking_player(conn, user, int(booking_player_id))
    return {"ok": True}


@route("POST", f"/booking-players/{ID}/check-in", "staff")
def post_check_in(req, conn, user, booking_player_id):
    service.check_in(conn, user, int(booking_player_id), req.body())
    return {"ok": True}


@route("DELETE", f"/booking-players/{ID}/check-in", "staff")
def delete_check_in(req, conn, user, booking_player_id):
    service.undo_check_in(conn, user, int(booking_player_id))
    return {"ok": True}


# --------------------------------------------------------------------------- rentals

@route("GET", "/inventory")
def get_inventory(req, conn, user):
    return service.inventory(conn, user)


@route("POST", "/rentals", "staff")
def post_rental(req, conn, user):
    return 201, service.rent_now(conn, user, req.body())


@route("POST", f"/rentals/{ID}/return", "staff")
def post_return(req, conn, user, rental_id):
    service.return_rental(conn, user, int(rental_id))
    return {"ok": True}


@route("PUT", f"/rental-units/{ID}", "staff")
def put_unit(req, conn, user, unit_id):
    service.update_unit(conn, user, int(unit_id), req.body())
    return {"ok": True}


# --------------------------------------------------------------------------- players and passes

@route("GET", "/players", "staff")
def get_players(req, conn, user):
    return {"players": service.search_players(conn, req.query.get("q", ""))}


@route("POST", "/players", "staff")
def post_player(req, conn, user):
    return 201, {"player_id": service.create_player(conn, user, req.body())}


@route("GET", f"/players/{ID}", "staff")
def get_player(req, conn, user, player_id):
    return service.player_profile(conn, user, int(player_id))


@route("PUT", f"/players/{ID}", "staff")
def put_player(req, conn, user, player_id):
    service.update_player(conn, user, int(player_id), req.body(), staff=True)
    return service.player_profile(conn, user, int(player_id))


@route("POST", f"/players/{ID}/player-code", "staff")
def post_player_code(req, conn, user, player_id):
    return 201, service.create_claim_code(conn, user, int(player_id))


@route("POST", f"/players/{ID}/passes", "staff")
def post_pass(req, conn, user, player_id):
    return 201, {"pass_id": service.issue_pass(conn, user, int(player_id), req.body())}


@route("POST", f"/passes/{ID}/adjust", "staff")
def post_adjust_pass(req, conn, user, pass_id):
    service.adjust_pass(conn, user, int(pass_id), req.body())
    return {"ok": True}


@route("POST", "/range-buckets", "staff")
def post_range_buckets(req, conn, user):
    service.sell_range_buckets(conn, user, req.body())
    return 201, {"ok": True}


# --------------------------------------------------------------------------- catalog and settings

@route("GET", "/products", "staff")
def get_products(req, conn, user):
    return {"products": service.list_products(conn)}


@route("POST", "/products", "staff")
def post_product(req, conn, user):
    return 201, {"product_id": service.create_product(conn, user, req.body())}


@route("PUT", f"/products/{ID}", "staff")
def put_product(req, conn, user, product_id):
    service.update_product(conn, user, int(product_id), req.body())
    return {"ok": True}


@route("GET", "/settings", "staff")
def get_settings(req, conn, user):
    with conn.cursor() as cur:
        return {"settings": service.settings_json(service.load_settings(cur))}


@route("PUT", "/settings", "staff")
def put_settings(req, conn, user):
    return {"settings": service.update_settings(conn, user, req.body())}


# --------------------------------------------------------------------------- WSGI plumbing

def respond(start_response, status: int, payload, cookie: str | None = None):
    body = json.dumps(payload, default=to_json, separators=(",", ":")).encode("utf-8")
    headers = [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body))),
               ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")]
    if cookie:
        headers.append(("Set-Cookie", cookie))
    start_response(f"{status} {STATUS_TEXT.get(status, 'OK')}", headers)
    return [body]


def check_write_allowed(req: Request) -> None:
    if req.method in ("GET", "HEAD"):
        return
    if req.environ.get("HTTP_X_GOLF_CLIENT") != "1":
        raise ApiError(403, "Missing X-Golf-Client header")
    origin = req.environ.get("HTTP_ORIGIN")
    if origin and origin.rstrip("/") not in env_origins():
        raise ApiError(403, "Requests from this site are not allowed")


def handle(req: Request):
    allowed_methods = set()
    for method, pattern, auth, handler in ROUTES:
        match = pattern.match(req.path)
        if not match:
            continue
        if method != req.method:
            allowed_methods.add(method)
            continue
        check_write_allowed(req)
        conn = service.connect()
        try:
            user = service.user_for_token(conn, req.token)
            if auth and user is None:
                raise ApiError(401, "Please sign in")
            if auth == "staff" and not service.is_staff(user):
                raise ApiError(403, "Course staff only")
            result = handler(req, conn, user, *match.groups())
        finally:
            conn.close()
        return result if isinstance(result, tuple) else (200, result)
    if allowed_methods:
        raise ApiError(405, "Method not allowed")
    raise ApiError(404, "Not found")


def application(environ, start_response):
    req = Request(environ)
    try:
        status, payload = handle(req)
        return respond(start_response, status, payload, req.set_cookie)
    except ApiError as exc:
        return respond(start_response, exc.status, {"error": exc.message})
    except RuleError as exc:
        return respond(start_response, 400, {"error": str(exc)})
    except psycopg.errors.RaiseException as exc:
        # Course rules raised by the database triggers (capacity, overlaps, pass balance and validity).
        return respond(start_response, 409, {"error": exc.diag.message_primary or "That breaks a course rule"})
    except psycopg.errors.CheckViolation:
        return respond(start_response, 409, {"error": "That change would break a course rule"})
    except psycopg.errors.UniqueViolation:
        return respond(start_response, 409, {"error": "That already exists"})
    except psycopg.errors.ForeignKeyViolation:
        return respond(start_response, 409, {"error": "That record is in use or no longer exists"})
    except psycopg.OperationalError:
        traceback.print_exc(file=sys.stderr)
        return respond(start_response, 503, {"error": "The tee sheet is temporarily unavailable. Try again shortly."})
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return respond(start_response, 500, {"error": "Something went wrong. Please try again."})
