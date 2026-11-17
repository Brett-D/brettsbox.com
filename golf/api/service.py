"""Database operations for the golf API.

Connections run in autocommit mode and every write is wrapped in ``conn.transaction()``, so a
request either commits completely or not at all: a booking whose rental clubs cannot be reserved
leaves no booking behind. The database triggers in migrations/ enforce the same capacity and
credit rules again, which protects against races between concurrent requests.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
from psycopg.rows import dict_row

import domain
import security
from domain import RuleError

SESSION_DAYS = 30
CLAIM_CODE_DAYS = 14
ALLOCATION_LOCK = 4270001  # also taken by the golf_rentals_guard trigger
EARLY_CHECKOUT = timedelta(minutes=30)
RENTAL_PRODUCT_KIND = {"riding_cart": "riding_cart_rental", "pull_cart": "pull_cart_rental", "club_set": "club_rental"}
SETTINGS_COLUMNS = (
    "course_name", "time_zone", "opening_time", "closing_time", "tee_interval_minutes", "average_round_minutes",
    "booking_window_days", "riding_cart_count", "pull_cart_count", "club_sets_right", "club_sets_left",
)
COUNT_UNITS = {
    "riding_cart_count": ("riding_cart", None),
    "pull_cart_count": ("pull_cart", None),
    "club_sets_right": ("club_set", "right"),
    "club_sets_left": ("club_set", "left"),
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def now() -> datetime:
    return datetime.now(timezone.utc)


def connect(dsn: str | None = None) -> psycopg.Connection:
    dsn = dsn or os.environ.get("GOLF_DATABASE_URL")
    if not dsn:
        raise RuntimeError("GOLF_DATABASE_URL is not configured")
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row, connect_timeout=5)


def is_staff(user: dict | None) -> bool:
    return bool(user) and user["role"] == "staff"


def require(condition: bool, status: int, message: str) -> None:
    if not condition:
        raise ApiError(status, message)


# --------------------------------------------------------------------------- settings and time

def load_settings(cur, lock: str = "") -> dict:
    cur.execute(f"SELECT {', '.join(SETTINGS_COLUMNS)} FROM golf_settings WHERE singleton {lock}")
    settings = dict(cur.fetchone())
    settings["zone"] = ZoneInfo(settings["time_zone"])
    settings["round"] = timedelta(minutes=settings["average_round_minutes"])
    return settings


def settings_json(settings: dict) -> dict:
    return {key: domain.hhmm(value) if isinstance(value, time) else value
            for key, value in settings.items() if key not in ("zone", "round")}


def course_today(settings: dict) -> date:
    return now().astimezone(settings["zone"]).date()


def clock(value: datetime, settings: dict) -> str:
    local = value.astimezone(settings["zone"])
    return f"{local.strftime('%I:%M %p').lstrip('0')}"


def day_label(value: datetime, settings: dict) -> str:
    local = value.astimezone(settings["zone"])
    return f"{local.strftime('%a %b')} {local.day} at {clock(value, settings)}"


def resolve_tee_time(settings: dict, date_text: object, time_text: object) -> tuple[date, datetime]:
    day = domain.parse_date(date_text)
    slot = domain.parse_hhmm(time_text, "Tee time")
    slots = domain.tee_slots(settings["opening_time"], settings["closing_time"], settings["tee_interval_minutes"])
    if slot not in slots:
        raise RuleError(f"{domain.hhmm(slot)} is not a tee time on the sheet")
    return day, domain.local_tee_time(day, slot, settings["zone"])


def check_new_booking_time(settings: dict, user: dict, day: date, tee: datetime) -> None:
    today = course_today(settings)
    if is_staff(user):
        if day < today:
            raise RuleError("That day has already passed")
        return
    if tee <= now():
        raise RuleError("That tee time has already gone")
    if day > today + timedelta(days=settings["booking_window_days"]):
        raise RuleError(f"Tee times can be booked up to {settings['booking_window_days']} days ahead")


def check_can_change(user: dict, tee_time: datetime) -> None:
    if not is_staff(user) and tee_time <= now():
        raise ApiError(409, "This tee time has started. Ask the pro shop to make changes.")


# --------------------------------------------------------------------------- ledger

def add_ledger(cur, *, player_id: int | None, kind: str, description: str, user: dict | None = None,
               product_kind: str | None = None, product_id: int | None = None, quantity: int = 1,
               billing: str = "none", booking_id: int | None = None, rental_id: int | None = None,
               entitlement_id: int | None = None, booking_player_id: int | None = None) -> None:
    price = None
    if product_kind or product_id:
        column = "kind" if product_kind else "id"
        cur.execute(f"SELECT id, price_cents FROM golf_products WHERE {column} = %s", (product_kind or product_id,))
        product = cur.fetchone()
        if product:
            product_id, price = product["id"], product["price_cents"]
    cur.execute(
        """
        INSERT INTO golf_ledger (player_id, kind, description, product_id, quantity, unit_price_cents,
                                 billing_status, booking_id, booking_player_id, rental_id, entitlement_id,
                                 recorded_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (player_id, kind, description, product_id, quantity, price, billing, booking_id, booking_player_id,
         rental_id, entitlement_id, user["id"] if user else None),
    )


def void_charges(cur, note: str, *, rental_ids: list[int] | None = None, check_in_for: int | None = None) -> None:
    """Something that was going to be charged didn't happen (a reservation cancelled before it
    started, a check-in undone): its ledger entry stays as history but is no longer billable."""
    if rental_ids:
        cur.execute("UPDATE golf_ledger SET billing_status = 'none', description = description || %s "
                    "WHERE rental_id = ANY(%s) AND billing_status = 'unbilled'", (f" ({note})", rental_ids))
    if check_in_for is not None:
        cur.execute("UPDATE golf_ledger SET billing_status = 'none', description = description || %s "
                    "WHERE kind = 'check_in' AND booking_player_id = %s AND billing_status <> 'none'",
                    (f" ({note})", check_in_for))


# --------------------------------------------------------------------------- accounts

USER_SELECT = """
    SELECT u.id, u.email, u.role, u.player_id, p.full_name, p.phone
    FROM golf_users u JOIN golf_players p ON p.id = u.player_id
"""


def user_for_token(conn, token: str | None) -> dict | None:
    if not token:
        return None
    with conn.cursor() as cur:
        cur.execute(USER_SELECT + " JOIN golf_sessions s ON s.user_id = u.id WHERE s.token_hash = %s AND s.expires_at > now()",
                    (security.hash_token(token),))
        row = cur.fetchone()
    return dict(row) if row else None


def public_user(user: dict | None) -> dict | None:
    if not user:
        return None
    return {"id": user["id"], "email": user["email"], "role": user["role"], "is_staff": is_staff(user),
            "player_id": user["player_id"], "full_name": user["full_name"]}


def create_session(cur, user_id: int) -> str:
    token = security.new_session_token()
    cur.execute("DELETE FROM golf_sessions WHERE expires_at <= now()")
    cur.execute("INSERT INTO golf_sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + make_interval(days => %s))",
                (security.hash_token(token), user_id, SESSION_DAYS))
    return token


def register(conn, payload: dict, bootstrap_email: str) -> str:
    email = domain.clean_email(payload.get("email"))
    try:
        password = security.check_password_policy(payload.get("password"))
    except ValueError as exc:
        raise RuleError(str(exc)) from None
    full_name = domain.clean_text(payload.get("full_name"), "Name", 120)
    phone = domain.clean_text(payload.get("phone"), "Phone", 40, required=False)
    code = security.normalize_claim_code(payload.get("player_code"))
    password_hash = security.hash_password(password)
    try:
        with conn.transaction(), conn.cursor() as cur:
            # The bootstrap email only creates the *first* staff account; after that, staff are
            # promoted with manage_staff.py.
            role = "user"
            if bootstrap_email and email == bootstrap_email:
                cur.execute("SELECT pg_advisory_xact_lock(4270002)")
                cur.execute("SELECT NOT EXISTS (SELECT 1 FROM golf_users WHERE role = 'staff') AS first")
                role = "staff" if cur.fetchone()["first"] else "user"
            if code:
                cur.execute(
                    """
                    SELECT p.id FROM golf_players p
                    WHERE p.claim_code_hash = %s AND p.claim_code_expires_at > now()
                      AND NOT EXISTS (SELECT 1 FROM golf_users u WHERE u.player_id = p.id)
                    FOR UPDATE
                    """,
                    (security.hash_token(code),),
                )
                row = cur.fetchone()
                require(row is not None, 400, "That player code is not valid or has expired. Ask the pro shop for a new one.")
                player_id = row["id"]
                cur.execute(
                    """
                    UPDATE golf_players SET claim_code_hash = NULL, claim_code_expires_at = NULL,
                        email = COALESCE(email, %s), phone = COALESCE(phone, %s), updated_at = now()
                    WHERE id = %s
                    """,
                    (email, phone, player_id),
                )
            else:
                cur.execute("INSERT INTO golf_players (full_name, email, phone) VALUES (%s, %s, %s) RETURNING id",
                            (full_name, email, phone))
                player_id = cur.fetchone()["id"]
            cur.execute("INSERT INTO golf_users (email, password_hash, role, player_id) VALUES (%s, %s, %s, %s) RETURNING id",
                        (email, password_hash, role, player_id))
            user_id = cur.fetchone()["id"]
            add_ledger(cur, player_id=player_id, kind="account", description="Created an app account",
                       user={"id": user_id})
            return create_session(cur, user_id)
    except psycopg.errors.UniqueViolation:
        raise ApiError(409, "An account already exists for that email. Sign in instead.") from None


def login(conn, payload: dict) -> str:
    email = payload.get("email") if isinstance(payload.get("email"), str) else ""
    email = email.strip().lower()
    password = payload.get("password") if isinstance(payload.get("password"), str) else ""
    with conn.cursor() as cur:
        cur.execute("SELECT id, role, password_hash FROM golf_users WHERE email = %s", (email,))
        row = cur.fetchone()
    if row is None:
        security.verify_password(password, security.DUMMY_HASH)
        raise ApiError(401, "Email or password is incorrect")
    if not security.verify_password(password, row["password_hash"]):
        raise ApiError(401, "Email or password is incorrect")
    with conn.transaction(), conn.cursor() as cur:
        return create_session(cur, row["id"])


def logout(conn, token: str | None) -> None:
    if token:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM golf_sessions WHERE token_hash = %s", (security.hash_token(token),))


# --------------------------------------------------------------------------- rentals

FREE_UNIT_SQL = """
    SELECT u.id, u.label FROM golf_rental_units u
    WHERE u.kind = %(kind)s AND u.hand IS NOT DISTINCT FROM %(hand)s AND u.active AND u.in_service
      AND u.id <> ALL(%(exclude)s)
      AND NOT EXISTS (
          SELECT 1 FROM golf_rentals r
          WHERE r.unit_id = u.id AND r.returned_at IS NULL
            AND ((r.starts_at < %(due)s AND %(start)s < r.due_at) OR r.due_at <= %(now)s)
      )
    ORDER BY u.number
    LIMIT 1
"""


def find_free_unit(cur, kind: str, hand: str | None, starts_at: datetime, due_at: datetime,
                   exclude: list[int] | None = None) -> dict | None:
    """Lowest-numbered unit free for the whole window. Units out past their estimated return
    (overdue) are skipped until staff mark them returned."""
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (ALLOCATION_LOCK,))
    cur.execute(FREE_UNIT_SQL, {"kind": kind, "hand": hand, "start": starts_at, "due": due_at, "now": now(),
                                "exclude": exclude or []})
    return cur.fetchone()


def allocate(cur, settings: dict, user: dict | None, *, kind: str, hand: str | None, starts_at: datetime,
             holder_name: str, player_id: int | None, ledger_player_id: int | None,
             booking_id: int | None = None, booking_player_id: int | None = None) -> dict:
    due_at = starts_at + settings["round"]
    unit = find_free_unit(cur, kind, hand, starts_at, due_at)
    if unit is None:
        raise ApiError(409, f"No {domain.rental_description(kind, hand, plural=True)} are free at "
                            f"{clock(starts_at, settings)}")
    cur.execute(
        """
        INSERT INTO golf_rentals (unit_id, booking_id, booking_player_id, player_id, holder_name,
                                  starts_at, due_at, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (unit["id"], booking_id, booking_player_id, player_id, holder_name, starts_at, due_at,
         user["id"] if user else None),
    )
    rental_id = cur.fetchone()["id"]
    add_ledger(cur, player_id=ledger_player_id, kind="rental",
               description=f"{unit['label']} for {holder_name}, {day_label(starts_at, settings)}",
               user=user, product_kind=RENTAL_PRODUCT_KIND[kind], billing="unbilled",
               booking_id=booking_id, rental_id=rental_id)
    return {"id": rental_id, "label": unit["label"]}


def end_rental(cur, rental: dict) -> None:
    """Drop a reservation that has not started; a rental already out is marked returned instead."""
    if rental["starts_at"] > now():
        cur.execute("DELETE FROM golf_rentals WHERE id = %s", (rental["id"],))
        void_charges(cur, "cancelled", rental_ids=[rental["id"]])
    else:
        cur.execute("UPDATE golf_rentals SET returned_at = now() WHERE id = %s AND returned_at IS NULL", (rental["id"],))


def detach_rentals(cur, column: str, ids: list[int]) -> None:
    """Before booking rows are deleted: cancel reservations that have not started and keep the
    history of rentals that are out or returned (so units are never silently freed)."""
    assert column in ("booking_id", "booking_player_id")
    cur.execute(f"DELETE FROM golf_rentals WHERE {column} = ANY(%s) AND returned_at IS NULL AND starts_at > %s RETURNING id",
                (ids, now()))
    void_charges(cur, "cancelled", rental_ids=[row["id"] for row in cur.fetchall()])
    cur.execute(f"UPDATE golf_rentals SET booking_id = NULL, booking_player_id = NULL WHERE {column} = ANY(%s)", (ids,))


def reserve_player_rentals(cur, settings: dict, user: dict, *, booking_id: int, booking_player_id: int,
                           tee: datetime, name: str, player_id: int | None, ledger_player_id: int,
                           clubs: str, pull_cart: bool) -> None:
    if clubs != "none":
        allocate(cur, settings, user, kind="club_set", hand=clubs, starts_at=tee, holder_name=name,
                 player_id=player_id, ledger_player_id=ledger_player_id, booking_id=booking_id,
                 booking_player_id=booking_player_id)
    if pull_cart:
        allocate(cur, settings, user, kind="pull_cart", hand=None, starts_at=tee, holder_name=name,
                 player_id=player_id, ledger_player_id=ledger_player_id, booking_id=booking_id,
                 booking_player_id=booking_player_id)


# --------------------------------------------------------------------------- bookings

def lock_booking(cur, booking_id: int) -> dict:
    cur.execute(
        """
        SELECT b.id, b.tee_time, b.captain_player_id, p.full_name AS captain_name
        FROM golf_bookings b JOIN golf_players p ON p.id = b.captain_player_id
        WHERE b.id = %s FOR UPDATE OF b
        """,
        (booking_id,),
    )
    booking = cur.fetchone()
    require(booking is not None, 404, "That tee time booking no longer exists")
    return booking


def load_players(cur, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    cur.execute("SELECT id, full_name FROM golf_players WHERE id = ANY(%s)", (ids,))
    found = {row["id"]: row["full_name"] for row in cur.fetchall()}
    require(len(found) == len(set(ids)), 404, "Player not found")
    return found


def check_player_free(cur, settings: dict, player_id: int, tee: datetime, exclude_booking: int | None = None) -> None:
    cur.execute(
        """
        SELECT b.tee_time, p.full_name
        FROM golf_booking_players bp
        JOIN golf_bookings b ON b.id = bp.booking_id
        JOIN golf_players p ON p.id = bp.player_id
        WHERE bp.player_id = %s AND b.id IS DISTINCT FROM %s AND b.tee_time > %s AND b.tee_time < %s
        LIMIT 1
        """,
        (player_id, exclude_booking, tee - settings["round"], tee + settings["round"]),
    )
    row = cur.fetchone()
    if row:
        raise ApiError(409, f"{row['full_name']} already has a {clock(row['tee_time'], settings)} tee time")


def add_party(cur, settings: dict, user: dict, booking: dict, party: list[domain.PlayerChoice],
              names: dict[int, str], added_by: int) -> list[int]:
    added = []
    for choice in party:
        name = names[choice.player_id] if choice.player_id else choice.guest_name
        cur.execute(
            """
            INSERT INTO golf_booking_players (booking_id, player_id, guest_name, added_by_player_id, clubs, pull_cart)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (booking["id"], choice.player_id, choice.guest_name, added_by, choice.clubs, choice.pull_cart),
        )
        booking_player_id = cur.fetchone()["id"]
        reserve_player_rentals(cur, settings, user, booking_id=booking["id"], booking_player_id=booking_player_id,
                               tee=booking["tee_time"], name=name, player_id=choice.player_id,
                               ledger_player_id=choice.player_id or added_by, clubs=choice.clubs,
                               pull_cart=choice.pull_cart)
        added.append(booking_player_id)
    return added


def create_booking(conn, user: dict, payload: dict) -> int:
    staff = is_staff(user)
    party = domain.parse_party(payload.get("captain"), payload.get("guests"), allow_player_ids=staff)
    riding_carts = domain.clean_int(payload.get("riding_carts", 0), "Riding carts", 0, len(party))
    captain_id = user["player_id"]
    if staff and payload.get("captain_player_id") is not None:
        captain_id = domain.clean_int(payload["captain_player_id"], "Player", 1, 2**62)
    party[0] = domain.PlayerChoice(captain_id, None, party[0].clubs, party[0].pull_cart)
    ids = [choice.player_id for choice in party if choice.player_id]
    if len(ids) != len(set(ids)):
        raise RuleError("A player can only be in the group once")

    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur, "FOR SHARE")
        day, tee = resolve_tee_time(settings, payload.get("date"), payload.get("time"))
        check_new_booking_time(settings, user, day, tee)
        names = load_players(cur, ids)
        for player_id in ids:
            check_player_free(cur, settings, player_id, tee)
        try:
            with conn.transaction():
                cur.execute("INSERT INTO golf_bookings (tee_time, captain_player_id, created_by_user_id) "
                            "VALUES (%s, %s, %s) RETURNING id", (tee, captain_id, user["id"]))
                booking_id = cur.fetchone()["id"]
        except psycopg.errors.UniqueViolation:
            raise ApiError(409, "Someone just booked that tee time. Join their group if there is room.") from None
        booking = {"id": booking_id, "tee_time": tee}
        add_party(cur, settings, user, booking, party, names, added_by=captain_id)
        for _ in range(riding_carts):
            allocate(cur, settings, user, kind="riding_cart", hand=None, starts_at=tee, holder_name=names[captain_id],
                     player_id=captain_id, ledger_player_id=captain_id, booking_id=booking_id)
        when = day_label(tee, settings)
        add_ledger(cur, player_id=captain_id, kind="booking", user=user, booking_id=booking_id,
                   description=f"Booked {when} for {len(party)} player{'s' if len(party) > 1 else ''}")
        for player_id in ids[1:]:
            add_ledger(cur, player_id=player_id, kind="booking", user=user, booking_id=booking_id,
                       description=f"Added to {names[captain_id]}'s group, {when}")
    return booking_id


def join_booking(conn, user: dict, booking_id: int, payload: dict) -> None:
    """Join an open group. Players join themselves (optionally with guests); staff can add
    players from the player list or named guests without joining themselves."""
    staff = is_staff(user)
    include_me = payload.get("include_me", True) is not False or not staff
    party = domain.parse_party(payload.get("me"), payload.get("guests"), allow_player_ids=staff)
    if include_me:
        party[0] = domain.PlayerChoice(user["player_id"], None, party[0].clubs, party[0].pull_cart)
    else:
        party = party[1:]
        require(bool(party), 400, "Choose at least one player to add")
    ids = [choice.player_id for choice in party if choice.player_id]
    if len(ids) != len(set(ids)):
        raise RuleError("A player can only be in the group once")

    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur)
        booking = lock_booking(cur, booking_id)
        check_can_change(user, booking["tee_time"])
        cur.execute("SELECT player_id FROM golf_booking_players WHERE booking_id = %s", (booking_id,))
        current = cur.fetchall()
        require(len(current) + len(party) <= domain.MAX_PLAYERS, 409,
                f"This group has room for {domain.MAX_PLAYERS - len(current)} more player"
                f"{'' if domain.MAX_PLAYERS - len(current) == 1 else 's'}")
        members = {row["player_id"] for row in current if row["player_id"]}
        for player_id in ids:
            require(player_id not in members, 409,
                    "You're already in this group" if player_id == user["player_id"] else "That player is already in this group")
        names = load_players(cur, ids)
        for player_id in ids:
            check_player_free(cur, settings, player_id, booking["tee_time"], exclude_booking=booking_id)
        added_by = user["player_id"] if include_me else booking["captain_player_id"]
        add_party(cur, settings, user, booking, party, names, added_by=added_by)
        when = day_label(booking["tee_time"], settings)
        for player_id in ids:
            add_ledger(cur, player_id=player_id, kind="join", user=user, booking_id=booking_id,
                       description=f"Joined {booking['captain_name']}'s group, {when}")


def remove_players(cur, settings: dict, user: dict, booking: dict, booking_player_ids: list[int]) -> bool:
    """Remove players (and their reservations). Returns True when the group was empty and deleted."""
    detach_rentals(cur, "booking_player_id", booking_player_ids)
    cur.execute("DELETE FROM golf_booking_players WHERE id = ANY(%s)", (booking_player_ids,))
    cur.execute("SELECT id, player_id FROM golf_booking_players WHERE booking_id = %s ORDER BY id", (booking["id"],))
    remaining = cur.fetchall()
    known = [row["player_id"] for row in remaining if row["player_id"]]
    if not known:
        detach_rentals(cur, "booking_id", [booking["id"]])
        cur.execute("DELETE FROM golf_bookings WHERE id = %s", (booking["id"],))
        return True
    captain = booking["captain_player_id"] if booking["captain_player_id"] in known else known[0]
    cur.execute("UPDATE golf_bookings SET captain_player_id = %s WHERE id = %s", (captain, booking["id"]))
    cur.execute(
        """
        UPDATE golf_booking_players SET added_by_player_id = %s
        WHERE booking_id = %s AND player_id IS NULL
          AND added_by_player_id NOT IN (SELECT player_id FROM golf_booking_players WHERE booking_id = %s AND player_id IS NOT NULL)
        """,
        (captain, booking["id"], booking["id"]),
    )
    # The group's riding carts, and any charges still on someone who has left, move to the captain.
    cur.execute(
        """
        UPDATE golf_rentals r SET player_id = %(captain)s, holder_name = p.full_name
        FROM golf_players p
        WHERE p.id = %(captain)s AND r.booking_id = %(booking)s AND r.booking_player_id IS NULL
          AND r.returned_at IS NULL AND r.player_id IS DISTINCT FROM %(captain)s
        """,
        {"captain": captain, "booking": booking["id"]},
    )
    cur.execute(
        """
        UPDATE golf_ledger l SET player_id = %(captain)s
        FROM golf_rentals r
        WHERE l.rental_id = r.id AND r.booking_id = %(booking)s AND l.billing_status = 'unbilled'
          AND l.player_id IS DISTINCT FROM %(captain)s
          AND NOT EXISTS (SELECT 1 FROM golf_booking_players bp WHERE bp.booking_id = %(booking)s AND bp.player_id = l.player_id)
        """,
        {"captain": captain, "booking": booking["id"]},
    )
    # A group never keeps more riding carts than players.
    rides = riding_rentals(cur, booking["id"])
    for rental in rides[len(remaining):]:
        end_rental(cur, rental)
    return False


def riding_rentals(cur, booking_id: int) -> list[dict]:
    """The group's riding carts, carts already out first, so trimming the list cancels reservations
    that have not started before it touches a cart on the course."""
    cur.execute(
        """
        SELECT r.id, r.starts_at FROM golf_rentals r JOIN golf_rental_units u ON u.id = r.unit_id
        WHERE r.booking_id = %s AND r.booking_player_id IS NULL AND u.kind = 'riding_cart' AND r.returned_at IS NULL
        ORDER BY r.starts_at <= now() DESC, r.id
        """,
        (booking_id,),
    )
    return cur.fetchall()


def leave_booking(conn, user: dict, booking_id: int) -> None:
    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur)
        booking = lock_booking(cur, booking_id)
        check_can_change(user, booking["tee_time"])
        cur.execute(
            """
            SELECT id, player_id, checked_in_at FROM golf_booking_players
            WHERE booking_id = %s AND (player_id = %s OR (player_id IS NULL AND added_by_player_id = %s))
            """,
            (booking_id, user["player_id"], user["player_id"]),
        )
        rows = cur.fetchall()
        require(any(row["player_id"] == user["player_id"] for row in rows), 409, "You're not in this group")
        require(not any(row["checked_in_at"] for row in rows), 409,
                "You're checked in for this round. Ask the pro shop to make changes.")
        remove_players(cur, settings, user, booking, [row["id"] for row in rows])
        guests = len(rows) - 1
        add_ledger(cur, player_id=user["player_id"], kind="leave", user=user, booking_id=booking_id,
                   description=f"Left the {day_label(booking['tee_time'], settings)} group"
                               + (f" with {guests} guest{'s' if guests > 1 else ''}" if guests else ""))


def lock_booking_player(cur, booking_player_id: int) -> dict:
    cur.execute(
        """
        SELECT bp.id, bp.booking_id, bp.player_id, bp.guest_name, bp.added_by_player_id, bp.clubs, bp.pull_cart,
               bp.checked_in_at, bp.coverage, bp.entitlement_use_id, b.tee_time, b.captain_player_id,
               COALESCE(p.full_name, bp.guest_name) AS name, cp.full_name AS captain_name
        FROM golf_booking_players bp
        JOIN golf_bookings b ON b.id = bp.booking_id
        JOIN golf_players cp ON cp.id = b.captain_player_id
        LEFT JOIN golf_players p ON p.id = bp.player_id
        WHERE bp.id = %s
        FOR UPDATE OF b, bp
        """,
        (booking_player_id,),
    )
    row = cur.fetchone()
    require(row is not None, 404, "That player is no longer in the group")
    return row


def can_manage_player(user: dict, row: dict) -> bool:
    return (is_staff(user) or row["player_id"] == user["player_id"]
            or (row["player_id"] is None and row["added_by_player_id"] == user["player_id"]))


def update_player_options(conn, user: dict, booking_player_id: int, payload: dict) -> None:
    clubs, pull_cart = domain.parse_options(payload)
    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur)
        row = lock_booking_player(cur, booking_player_id)
        require(can_manage_player(user, row), 403, "You can only change your own options or your guests'")
        check_can_change(user, row["tee_time"])
        cur.execute(
            """
            SELECT r.id, r.starts_at, r.returned_at, u.kind FROM golf_rentals r JOIN golf_rental_units u ON u.id = r.unit_id
            WHERE r.booking_player_id = %s
            """,
            (booking_player_id,),
        )
        all_rentals = cur.fetchall()
        rentals = {rental["kind"]: rental for rental in all_rentals if rental["returned_at"] is None}
        had = {rental["kind"] for rental in all_rentals}  # includes gear already handed back
        ledger_player = row["player_id"] or row["added_by_player_id"]
        common = dict(booking_id=row["booking_id"], booking_player_id=booking_player_id, tee=row["tee_time"],
                      name=row["name"], player_id=row["player_id"], ledger_player_id=ledger_player)
        # Re-reserve only when the choice changes (or a reservation is missing altogether), never
        # because the clubs or cart were already returned.
        if clubs != row["clubs"] or (clubs != "none" and "club_set" not in had):
            if "club_set" in rentals:
                end_rental(cur, rentals["club_set"])
            reserve_player_rentals(cur, settings, user, clubs=clubs, pull_cart=False, **common)
        if pull_cart != row["pull_cart"] or (pull_cart and "pull_cart" not in had):
            if "pull_cart" in rentals:
                end_rental(cur, rentals["pull_cart"])
            reserve_player_rentals(cur, settings, user, clubs="none", pull_cart=pull_cart, **common)
        if (clubs, pull_cart) == (row["clubs"], row["pull_cart"]):
            return
        cur.execute("UPDATE golf_booking_players SET clubs = %s, pull_cart = %s WHERE id = %s",
                    (clubs, pull_cart, booking_player_id))
        wants = [{"right": "right-handed clubs", "left": "left-handed clubs"}.get(clubs), "a pull cart" if pull_cart else None]
        wants = [item for item in wants if item]
        add_ledger(cur, player_id=ledger_player, kind="options", user=user, booking_id=row["booking_id"],
                   description=f"{row['name']}, {day_label(row['tee_time'], settings)}: "
                               + (" and ".join(wants) if wants else "no rentals"))


def remove_booking_player(conn, user: dict, booking_player_id: int) -> None:
    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur)
        row = lock_booking_player(cur, booking_player_id)
        staff = is_staff(user)
        require(staff or (row["player_id"] is None and row["added_by_player_id"] == user["player_id"]), 403,
                "Only course staff can remove other players. To leave, use Leave.")
        check_can_change(user, row["tee_time"])
        require(row["checked_in_at"] is None, 409, "Undo this player's check-in first")
        booking = {"id": row["booking_id"], "tee_time": row["tee_time"], "captain_player_id": row["captain_player_id"]}
        remove_players(cur, settings, user, booking, [booking_player_id])
        add_ledger(cur, player_id=row["player_id"] or row["added_by_player_id"], kind="remove", user=user,
                   booking_id=row["booking_id"],
                   description=f"{row['name']} removed from the {day_label(row['tee_time'], settings)} group")


def set_riding_carts(conn, user: dict, booking_id: int, payload: dict) -> None:
    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur)
        booking = lock_booking(cur, booking_id)
        cur.execute("SELECT player_id FROM golf_booking_players WHERE booking_id = %s", (booking_id,))
        players = cur.fetchall()
        require(is_staff(user) or any(row["player_id"] == user["player_id"] for row in players), 403,
                "Only players in this group can change its carts")
        check_can_change(user, booking["tee_time"])
        wanted = domain.clean_int(payload.get("count"), "Riding carts", 0, len(players))
        rides = riding_rentals(cur, booking_id)
        for _ in range(wanted - len(rides)):
            allocate(cur, settings, user, kind="riding_cart", hand=None, starts_at=booking["tee_time"],
                     holder_name=booking["captain_name"], player_id=booking["captain_player_id"],
                     ledger_player_id=booking["captain_player_id"], booking_id=booking_id)
        for rental in rides[wanted:]:
            end_rental(cur, rental)
        if wanted != len(rides):
            add_ledger(cur, player_id=booking["captain_player_id"], kind="options", user=user, booking_id=booking_id,
                       description=f"Riding carts for {day_label(booking['tee_time'], settings)}: {wanted}")


def cancel_booking(conn, user: dict, booking_id: int) -> None:
    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur)
        booking = lock_booking(cur, booking_id)
        cur.execute("SELECT player_id FROM golf_booking_players WHERE booking_id = %s AND checked_in_at IS NOT NULL",
                    (booking_id,))
        require(cur.fetchone() is None, 409, "Undo the check-ins in this group before cancelling it")
        cur.execute("SELECT DISTINCT player_id FROM golf_booking_players WHERE booking_id = %s AND player_id IS NOT NULL",
                    (booking_id,))
        players = [row["player_id"] for row in cur.fetchall()]
        detach_rentals(cur, "booking_id", [booking_id])
        cur.execute("DELETE FROM golf_bookings WHERE id = %s", (booking_id,))
        for player_id in players:
            add_ledger(cur, player_id=player_id, kind="cancel", user=user, booking_id=booking_id,
                       description=f"The pro shop cancelled the {day_label(booking['tee_time'], settings)} tee time")


# --------------------------------------------------------------------------- check-in and passes

def pick_pass(cur, player_id: int, kind: str, used_for: str, used_on: date) -> dict | None:
    covers = ("round", "round_and_range") if used_for == "round" else ("range", "round_and_range")
    cur.execute(
        """
        SELECT id FROM golf_entitlements
        WHERE player_id = %s AND kind = %s AND status = 'active' AND covers = ANY(%s)
          AND valid_from <= %s AND (valid_until IS NULL OR valid_until >= %s)
          AND (kind = 'membership' OR punches_remaining > 0)
        ORDER BY valid_until NULLS LAST, id
        LIMIT 1
        """,
        (player_id, kind, list(covers), used_on, used_on),
    )
    return cur.fetchone()


def use_pass(cur, user: dict, *, player_id: int, kind: str | None, pass_id: object, used_for: str,
             used_on: date, punches: int = 1) -> tuple[int, dict]:
    """Record a pass use. The golf_entitlement_use_guard trigger enforces status, validity, coverage
    and the punch balance; this picks a pass when none is given and checks ownership."""
    if pass_id is not None:
        pass_id = domain.clean_int(pass_id, "Pass", 1, 2**62)
    else:
        require(kind is not None, 400, "Choose a pass")
        picked = pick_pass(cur, player_id, kind, used_for, used_on)
        label = "membership" if kind == "membership" else "punch card"
        require(picked is not None, 409, f"No valid {label} covers this for that player")
        pass_id = picked["id"]
    cur.execute("SELECT id, player_id, kind, name FROM golf_entitlements WHERE id = %s", (pass_id,))
    entitlement = cur.fetchone()
    require(entitlement is not None and entitlement["player_id"] == player_id, 404, "That pass doesn't belong to this player")
    if kind is not None:
        require(entitlement["kind"] == kind, 400, f"That pass is not a {'membership' if kind == 'membership' else 'punch card'}")
    cur.execute(
        """
        INSERT INTO golf_entitlement_uses (entitlement_id, used_for, used_on, punches, recorded_by_user_id)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
        """,
        (pass_id, used_for, used_on, punches, user["id"]),
    )
    use_id = cur.fetchone()["id"]
    cur.execute("SELECT id, kind, name, punches_remaining FROM golf_entitlements WHERE id = %s", (pass_id,))
    return use_id, cur.fetchone()


def pass_note(entitlement: dict) -> str:
    if entitlement["kind"] == "punch_card":
        return f"{entitlement['name']}, {entitlement['punches_remaining']} left"
    return entitlement["name"]


def check_in(conn, user: dict, booking_player_id: int, payload: dict) -> None:
    coverage = payload.get("coverage")
    require(coverage in ("membership", "punch_card", "pay_at_counter"), 400,
            "Choose membership, punch card or pay at the counter")
    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur)
        row = lock_booking_player(cur, booking_player_id)
        require(row["checked_in_at"] is None, 409, f"{row['name']} is already checked in")
        player_id = row["player_id"]
        if player_id is None and payload.get("link_player_id") is not None:
            player_id = domain.clean_int(payload["link_player_id"], "Player", 1, 2**62)
            load_players(cur, [player_id])
            cur.execute("SELECT 1 FROM golf_booking_players WHERE booking_id = %s AND player_id = %s",
                        (row["booking_id"], player_id))
            require(cur.fetchone() is None, 409, "That player is already in this group")
        elif player_id is None and payload.get("create_player") is True:
            cur.execute("INSERT INTO golf_players (full_name) VALUES (%s) RETURNING id", (row["guest_name"],))
            player_id = cur.fetchone()["id"]
            add_ledger(cur, player_id=player_id, kind="profile", user=user, description="Player record created at check-in")
        if player_id != row["player_id"]:
            cur.execute("UPDATE golf_booking_players SET player_id = %s, guest_name = NULL WHERE id = %s",
                        (player_id, booking_player_id))

        used_on = row["tee_time"].astimezone(settings["zone"]).date()
        use_id, note, billing, entitlement_id = None, "pay at the counter", "unbilled", None
        if coverage != "pay_at_counter":
            require(player_id is not None, 400, "Link this guest to a player record to use a pass")
            use_id, entitlement = use_pass(cur, user, player_id=player_id, kind=coverage, pass_id=payload.get("pass_id"),
                                           used_for="round", used_on=used_on)
            note, billing, entitlement_id = pass_note(entitlement), "covered", entitlement["id"]
        cur.execute("UPDATE golf_booking_players SET checked_in_at = now(), coverage = %s, entitlement_use_id = %s WHERE id = %s",
                    (coverage, use_id, booking_player_id))
        add_ledger(cur, player_id=player_id or row["added_by_player_id"], kind="check_in", user=user,
                   product_kind="green_fee", billing=billing, booking_id=row["booking_id"], entitlement_id=entitlement_id,
                   booking_player_id=booking_player_id,
                   description=f"{row['name']} checked in for {day_label(row['tee_time'], settings)} ({note})")


def undo_check_in(conn, user: dict, booking_player_id: int) -> None:
    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur)
        row = lock_booking_player(cur, booking_player_id)
        require(row["checked_in_at"] is not None, 409, f"{row['name']} is not checked in")
        cur.execute("UPDATE golf_booking_players SET checked_in_at = NULL, coverage = NULL, entitlement_use_id = NULL WHERE id = %s",
                    (booking_player_id,))
        if row["entitlement_use_id"]:
            cur.execute("DELETE FROM golf_entitlement_uses WHERE id = %s", (row["entitlement_use_id"],))
        void_charges(cur, "check-in undone", check_in_for=booking_player_id)
        add_ledger(cur, player_id=row["player_id"] or row["added_by_player_id"], kind="check_in_undo", user=user,
                   booking_id=row["booking_id"], booking_player_id=booking_player_id,
                   description=f"Check-in undone for {row['name']}, {day_label(row['tee_time'], settings)}"
                               + (" (punch restored)" if row["coverage"] == "punch_card" else ""))


# --------------------------------------------------------------------------- tee sheet

def tee_sheet(conn, user: dict | None, date_text: object) -> dict:
    day = domain.parse_date(date_text)
    staff, me = is_staff(user), user["player_id"] if user else None
    with conn.cursor() as cur:
        settings = load_settings(cur)
        zone = settings["zone"]
        start = datetime.combine(day, time(0), zone)
        end = datetime.combine(day + timedelta(days=1), time(0), zone)
        cur.execute(
            """
            SELECT b.id, b.tee_time, b.captain_player_id FROM golf_bookings b
            WHERE b.tee_time >= %s AND b.tee_time < %s ORDER BY b.tee_time
            """,
            (start, end),
        )
        bookings = cur.fetchall()
        ids = [booking["id"] for booking in bookings]
        players, rentals = [], []
        if ids:
            cur.execute(
                """
                SELECT bp.id, bp.booking_id, bp.player_id, bp.guest_name, bp.added_by_player_id, bp.clubs, bp.pull_cart,
                       bp.checked_in_at, bp.coverage, p.full_name
                FROM golf_booking_players bp LEFT JOIN golf_players p ON p.id = bp.player_id
                WHERE bp.booking_id = ANY(%s) ORDER BY bp.id
                """,
                (ids,),
            )
            players = cur.fetchall()
            cur.execute(
                """
                SELECT r.booking_id, r.booking_player_id, u.kind, u.label, r.returned_at
                FROM golf_rentals r JOIN golf_rental_units u ON u.id = r.unit_id
                WHERE r.booking_id = ANY(%s) ORDER BY u.kind, u.number
                """,
                (ids,),
            )
            rentals = cur.fetchall()

    current = now()
    today = course_today(settings)
    by_booking: dict[int, list] = {}
    for player in players:
        by_booking.setdefault(player["booking_id"], []).append(player)
    gear: dict[tuple, list] = {}
    for rental in rentals:
        key = ("player", rental["booking_player_id"]) if rental["booking_player_id"] else ("booking", rental["booking_id"])
        gear.setdefault(key, []).append(rental)

    def player_json(player: dict, booking: dict, past: bool) -> dict:
        mine = me is not None and player["player_id"] == me
        my_guest = player["player_id"] is None and me is not None and player["added_by_player_id"] == me
        full = player["full_name"] or player["guest_name"]
        if user is None:
            name = "Booked"
        elif staff or mine or my_guest:
            name = full
        else:
            name = domain.short_name(full)
        can_change = staff or not past
        out = {
            "id": player["id"], "name": name, "is_guest": player["player_id"] is None, "is_me": mine,
            "is_captain": player["player_id"] is not None and player["player_id"] == booking["captain_player_id"],
            "checked_in": player["checked_in_at"] is not None,
            "can_edit": user is not None and can_change and (staff or mine or my_guest),
            "can_remove": user is not None and can_change and not mine and (staff or my_guest),
        }
        if user is not None:
            out.update(clubs=player["clubs"], pull_cart=player["pull_cart"])
        if staff:
            out.update(player_id=player["player_id"], coverage=player["coverage"],
                       gear=[g["label"] + (" (returned)" if g["returned_at"] else "") for g in gear.get(("player", player["id"]), [])])
        return out

    def booking_json(booking: dict, past: bool) -> dict:
        group = by_booking.get(booking["id"], [])
        is_member = me is not None and any(p["player_id"] == me for p in group)
        rides = [g for g in gear.get(("booking", booking["id"]), []) if g["kind"] == "riding_cart" and not g["returned_at"]]
        open_spots = domain.MAX_PLAYERS - len(group)
        can_change = staff or not past
        out = {
            "id": booking["id"], "players": [player_json(p, booking, past) for p in group], "open_spots": open_spots,
            "riding_carts": len(rides) if user is not None else None, "is_member": is_member,
            "can_join": user is not None and not is_member and open_spots > 0 and can_change,
            "can_leave": is_member and can_change,
            "can_manage_carts": user is not None and can_change and (staff or is_member),
            "can_cancel": staff,
        }
        if staff:
            out["riding_cart_labels"] = [g["label"] for g in rides]
        return out

    by_time = {domain.hhmm(b["tee_time"].astimezone(zone).time()): b for b in bookings}
    grid = [domain.hhmm(slot) for slot in domain.tee_slots(settings["opening_time"], settings["closing_time"],
                                                           settings["tee_interval_minutes"])]
    slots = []
    window_end = today + timedelta(days=settings["booking_window_days"])
    for label in sorted(set(grid) | set(by_time)):
        tee = domain.local_tee_time(day, domain.parse_hhmm(label), zone)
        past = tee <= current
        booking = by_time.get(label)
        bookable = (booking is None and label in grid and user is not None
                    and (day >= today if staff else (not past and day <= window_end)))
        slots.append({"time": label, "starts_at": tee, "past": past, "bookable": bookable,
                      "booking": booking_json(booking, past) if booking else None})
    return {"date": day.isoformat(), "today": today.isoformat(), "booking_window_days": settings["booking_window_days"],
            "slots": slots}


# --------------------------------------------------------------------------- inventory

def inventory(conn, user: dict | None) -> dict:
    current = now()
    with conn.cursor() as cur:
        settings = load_settings(cur)
        cur.execute(
            """
            SELECT u.id, u.kind, u.hand, u.number, u.label, u.active, u.in_service, u.notes,
                   cr.id AS cur_id, cr.starts_at AS cur_start, cr.due_at AS cur_due, cr.holder_name AS cur_holder,
                   nr.id AS next_id, nr.starts_at AS next_start, nr.due_at AS next_due, nr.holder_name AS next_holder,
                   (SELECT count(*) FROM golf_rentals r
                    WHERE r.unit_id = u.id AND r.returned_at IS NULL AND r.starts_at > %(now)s) AS upcoming
            FROM golf_rental_units u
            LEFT JOIN LATERAL (
                SELECT r.id, r.starts_at, r.due_at, r.holder_name FROM golf_rentals r
                WHERE r.unit_id = u.id AND r.returned_at IS NULL AND r.starts_at <= %(now)s
                ORDER BY r.starts_at DESC LIMIT 1
            ) cr ON TRUE
            LEFT JOIN LATERAL (
                SELECT r.id, r.starts_at, r.due_at, r.holder_name FROM golf_rentals r
                WHERE r.unit_id = u.id AND r.returned_at IS NULL AND r.starts_at > %(now)s
                ORDER BY r.starts_at LIMIT 1
            ) nr ON TRUE
            WHERE u.active OR cr.id IS NOT NULL
            ORDER BY u.kind DESC, u.hand DESC NULLS FIRST, u.number
            """,
            {"now": current},
        )
        units = cur.fetchall()

    groups: dict[str, dict] = {}
    for unit in units:
        key = unit["kind"] + (f"_{unit['hand']}" if unit["hand"] else "")
        current_rental = {"id": unit["cur_id"], "starts_at": unit["cur_start"], "due_at": unit["cur_due"],
                          "holder": unit["cur_holder"]} if unit["cur_id"] else None
        next_rental = {"id": unit["next_id"], "starts_at": unit["next_start"], "due_at": unit["next_due"],
                       "holder": unit["next_holder"]} if unit["next_id"] else None
        status = domain.unit_status(unit["in_service"], unit["active"], current_rental, next_rental, current)
        group = groups.setdefault(key, {
            "key": key, "kind": unit["kind"], "hand": unit["hand"],
            "name": domain.rental_description(unit["kind"], unit["hand"], plural=True).capitalize(),
            "total": 0, "available": 0, "out": 0, "overdue": 0, "out_of_service": 0, "units": [],
        })
        if unit["active"] and unit["in_service"]:
            group["total"] += 1
        if status in ("available", "reserved"):
            group["available"] += 1
        elif status in ("rented", "overdue"):
            group["out"] += 1
            group["overdue"] += status == "overdue"
        elif status == "out_of_service":
            group["out_of_service"] += 1
        if is_staff(user):
            group["units"].append({
                "id": unit["id"], "label": unit["label"], "status": status, "in_service": unit["in_service"],
                "notes": unit["notes"], "current": current_rental, "next": next_rental, "upcoming": unit["upcoming"],
            })
    order = ["riding_cart", "pull_cart", "club_set_right", "club_set_left"]
    return {"now": current, "average_round_minutes": settings["average_round_minutes"],
            "groups": sorted(groups.values(), key=lambda g: order.index(g["key"]) if g["key"] in order else 99)}


def rent_now(conn, user: dict, payload: dict) -> dict:
    kind = payload.get("kind")
    require(kind in domain.RENTAL_KINDS, 400, "Choose a riding cart, pull cart or club set")
    hand = payload.get("hand") if kind == "club_set" else None
    require(kind != "club_set" or hand in ("right", "left"), 400, "Choose right- or left-handed clubs")
    player_id = payload.get("player_id")
    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur)
        if player_id is not None:
            player_id = domain.clean_int(player_id, "Player", 1, 2**62)
            holder = load_players(cur, [player_id])[player_id]
        else:
            holder = domain.clean_text(payload.get("name"), "Name", 80, required=False) or "Walk-in"
        return allocate(cur, settings, user, kind=kind, hand=hand, starts_at=now(), holder_name=holder,
                        player_id=player_id, ledger_player_id=player_id)


def return_rental(conn, user: dict, rental_id: int) -> None:
    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur)
        cur.execute(
            """
            SELECT r.id, r.starts_at, r.returned_at, r.player_id, r.booking_id, r.holder_name, u.label
            FROM golf_rentals r JOIN golf_rental_units u ON u.id = r.unit_id WHERE r.id = %s FOR UPDATE OF r
            """,
            (rental_id,),
        )
        rental = cur.fetchone()
        require(rental is not None, 404, "Rental not found")
        require(rental["returned_at"] is None, 409, f"{rental['label']} was already returned")
        require(rental["starts_at"] <= now() + EARLY_CHECKOUT, 409,
                f"{rental['label']} is reserved for {day_label(rental['starts_at'], settings)}. "
                "Change the tee time options instead.")
        cur.execute("UPDATE golf_rentals SET returned_at = now() WHERE id = %s", (rental_id,))
        add_ledger(cur, player_id=rental["player_id"], kind="return", user=user, rental_id=rental_id,
                   booking_id=rental["booking_id"], description=f"{rental['label']} returned by {rental['holder_name']}")


def update_unit(conn, user: dict, unit_id: int, payload: dict) -> None:
    in_service = payload.get("in_service")
    require(in_service is None or isinstance(in_service, bool), 400, "In service must be true or false")
    notes = domain.clean_text(payload.get("notes"), "Notes", 500, required=False) if "notes" in payload else None
    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur)
        cur.execute("SELECT id, kind, hand, label, in_service FROM golf_rental_units WHERE id = %s FOR UPDATE", (unit_id,))
        unit = cur.fetchone()
        require(unit is not None, 404, "Unit not found")
        if in_service is not None and in_service != unit["in_service"]:
            cur.execute("UPDATE golf_rental_units SET in_service = %s WHERE id = %s", (in_service, unit_id))
            if not in_service:
                # Move upcoming reservations to another unit so nobody loses the clubs or cart they booked.
                cur.execute(
                    "SELECT id, starts_at, due_at FROM golf_rentals WHERE unit_id = %s AND returned_at IS NULL "
                    "AND starts_at > %s ORDER BY starts_at",
                    (unit_id, now()),
                )
                for rental in cur.fetchall():
                    other = find_free_unit(cur, unit["kind"], unit["hand"], rental["starts_at"], rental["due_at"], [unit_id])
                    require(other is not None, 409,
                            f"{unit['label']} is reserved for {day_label(rental['starts_at'], settings)} and no other "
                            f"{domain.rental_description(unit['kind'], unit['hand'])} is free then")
                    cur.execute("UPDATE golf_rentals SET unit_id = %s WHERE id = %s", (other["id"], rental["id"]))
            add_ledger(cur, player_id=None, kind="inventory", user=user,
                       description=f"{unit['label']} {'back in service' if in_service else 'taken out of service'}")
        if notes is not None or "notes" in payload:
            cur.execute("UPDATE golf_rental_units SET notes = %s WHERE id = %s", (notes or "", unit_id))


# --------------------------------------------------------------------------- players

def escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_players(conn, query: object) -> list[dict]:
    text = domain.clean_text(query, "Search", 80, required=False) or ""
    with conn.cursor() as cur:
        settings = load_settings(cur)
        cur.execute(
            """
            SELECT p.id, p.full_name, p.email, p.phone, (u.id IS NOT NULL) AS has_account,
                   (SELECT count(*) FROM golf_entitlements e
                    WHERE e.player_id = p.id AND e.status = 'active' AND e.valid_from <= %(today)s
                      AND (e.valid_until IS NULL OR e.valid_until >= %(today)s)
                      AND (e.kind = 'membership' OR e.punches_remaining > 0)) AS active_passes
            FROM golf_players p LEFT JOIN golf_users u ON u.player_id = p.id
            WHERE %(text)s = '' OR p.full_name ILIKE %(like)s OR p.email ILIKE %(like)s OR p.phone ILIKE %(like)s
            ORDER BY lower(p.full_name), p.id
            LIMIT 30
            """,
            {"today": course_today(settings), "text": text, "like": f"%{escape_like(text)}%"},
        )
        return cur.fetchall()


def clean_player_fields(payload: dict, staff: bool) -> dict:
    fields = {}
    if "full_name" in payload:
        fields["full_name"] = domain.clean_text(payload["full_name"], "Name", 120)
    if "phone" in payload:
        fields["phone"] = domain.clean_text(payload["phone"], "Phone", 40, required=False)
    if staff and "email" in payload:
        fields["email"] = domain.clean_email(payload["email"], required=False)
    if staff and "notes" in payload:
        fields["notes"] = domain.clean_text(payload["notes"], "Notes", 2000, required=False) or ""
    return fields


def create_player(conn, user: dict, payload: dict) -> int:
    fields = clean_player_fields(payload, staff=True)
    require("full_name" in fields, 400, "Name is required")
    with conn.transaction(), conn.cursor() as cur:
        columns = list(fields)
        cur.execute(f"INSERT INTO golf_players ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) RETURNING id",
                    [fields[c] for c in columns])
        player_id = cur.fetchone()["id"]
        add_ledger(cur, player_id=player_id, kind="profile", user=user, description="Player record created by the pro shop")
        return player_id


def update_player(conn, user: dict, player_id: int, payload: dict, staff: bool) -> None:
    fields = clean_player_fields(payload, staff)
    if not fields:
        return
    with conn.transaction(), conn.cursor() as cur:
        assignments = ", ".join(f"{column} = %s" for column in fields)
        cur.execute(f"UPDATE golf_players SET {assignments}, updated_at = now() WHERE id = %s RETURNING id",
                    [*fields.values(), player_id])
        require(cur.fetchone() is not None, 404, "Player not found")


def player_profile(conn, viewer: dict, player_id: int) -> dict:
    staff = is_staff(viewer)
    with conn.cursor() as cur:
        settings = load_settings(cur)
        today = course_today(settings)
        cur.execute(
            """
            SELECT p.id, p.full_name, p.email, p.phone, p.notes, p.claim_code_expires_at, p.created_at,
                   u.email AS account_email, u.role
            FROM golf_players p LEFT JOIN golf_users u ON u.player_id = p.id WHERE p.id = %s
            """,
            (player_id,),
        )
        player = cur.fetchone()
        require(player is not None, 404, "Player not found")
        cur.execute(
            """
            SELECT e.id, e.kind, e.name, e.covers, e.punches_total, e.punches_remaining, e.daily_round_limit,
                   e.valid_from, e.valid_until, e.status, e.issued_at,
                   (SELECT count(*) FROM golf_entitlement_uses x WHERE x.entitlement_id = e.id) AS uses
            FROM golf_entitlements e WHERE e.player_id = %s
            ORDER BY e.status, e.valid_until DESC NULLS FIRST, e.id DESC
            """,
            (player_id,),
        )
        passes = []
        for entitlement in cur.fetchall():
            entitlement["state"] = domain.pass_state(entitlement["kind"], entitlement["status"], entitlement["valid_from"],
                                                     entitlement["valid_until"], entitlement["punches_remaining"], today)
            passes.append(entitlement)
        cur.execute(
            """
            SELECT bp.id AS booking_player_id, b.id AS booking_id, b.tee_time, bp.clubs, bp.pull_cart,
                   bp.checked_in_at IS NOT NULL AS checked_in,
                   (SELECT count(*) FROM golf_booking_players x WHERE x.booking_id = b.id) AS players
            FROM golf_booking_players bp JOIN golf_bookings b ON b.id = bp.booking_id
            WHERE bp.player_id = %s AND b.tee_time >= %s ORDER BY b.tee_time LIMIT 20
            """,
            (player_id, now() - settings["round"]),
        )
        upcoming = cur.fetchall()
        cur.execute(
            """
            SELECT r.id, u.label, u.kind, r.starts_at, r.due_at FROM golf_rentals r
            JOIN golf_rental_units u ON u.id = r.unit_id
            WHERE r.player_id = %s AND r.returned_at IS NULL ORDER BY r.starts_at
            """,
            (player_id,),
        )
        rentals = cur.fetchall()
        cur.execute(
            """
            SELECT occurred_at, kind, description, quantity, unit_price_cents, billing_status
            FROM golf_ledger WHERE player_id = %s ORDER BY occurred_at DESC, id DESC LIMIT 100
            """,
            (player_id,),
        )
        history = cur.fetchall()
    profile = {
        "player": {"id": player["id"], "full_name": player["full_name"], "email": player["email"],
                   "phone": player["phone"], "created_at": player["created_at"],
                   "has_account": player["account_email"] is not None},
        "today": today, "passes": passes, "upcoming": upcoming, "rentals": rentals, "history": history,
    }
    if staff:
        profile["player"].update(notes=player["notes"], account_email=player["account_email"], role=player["role"],
                                 claim_code_expires_at=player["claim_code_expires_at"])
    return profile


def create_claim_code(conn, user: dict, player_id: int) -> dict:
    code = security.new_claim_code()
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT 1 FROM golf_users WHERE player_id = %s", (player_id,))
        require(cur.fetchone() is None, 409, "This player already has an app account")
        cur.execute(
            """
            UPDATE golf_players SET claim_code_hash = %s, claim_code_expires_at = now() + make_interval(days => %s)
            WHERE id = %s RETURNING claim_code_expires_at
            """,
            (security.hash_token(code), CLAIM_CODE_DAYS, player_id),
        )
        row = cur.fetchone()
        require(row is not None, 404, "Player not found")
    return {"code": f"{code[:4]}-{code[4:]}", "expires_at": row["claim_code_expires_at"]}


def issue_pass(conn, user: dict, player_id: int, payload: dict) -> int:
    product_id = domain.clean_int(payload.get("product_id"), "Product", 1, 2**31)
    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur)
        today = course_today(settings)
        valid_from = domain.parse_date(payload["valid_from"]) if payload.get("valid_from") else today
        if abs((valid_from - today).days) > 366:
            raise RuleError("Start date must be within a year of today")
        cur.execute("SELECT * FROM golf_products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        require(product is not None and product["kind"] in ("punch_card", "membership"), 404, "Pass product not found")
        require(product["active"], 409, f"{product['name']} is not currently offered")
        load_players(cur, [player_id])
        valid_until = domain.pass_valid_until(valid_from, product["valid_days"])
        if product["kind"] == "punch_card":
            covers, punches = product["covers"], product["punches"]
        else:
            covers, punches = ("round_and_range" if product["includes_range"] else "round"), None
        cur.execute(
            """
            INSERT INTO golf_entitlements (player_id, product_id, kind, name, covers, punches_total, punches_remaining,
                                           daily_round_limit, valid_from, valid_until, issued_by_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (player_id, product_id, product["kind"], product["name"], covers, punches, punches,
             product["daily_round_limit"] if product["kind"] == "membership" else None,
             valid_from, valid_until, user["id"]),
        )
        entitlement_id = cur.fetchone()["id"]
        through = f" through {valid_until:%b} {valid_until.day}, {valid_until.year}" if valid_until else ""
        add_ledger(cur, player_id=player_id, kind="pass_issue", user=user, product_id=product_id, billing="unbilled",
                   entitlement_id=entitlement_id, description=f"{product['name']} issued{through}")
        return entitlement_id


def adjust_pass(conn, user: dict, pass_id: int, payload: dict) -> None:
    reason = domain.clean_text(payload.get("reason"), "Reason", 200)
    delta = payload.get("punches_delta")
    delta = domain.clean_int(delta, "Punch change", -500, 500) if delta not in (None, 0) else 0
    status = payload.get("status")
    require(status in (None, "active", "void"), 400, "Status must be active or void")
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT * FROM golf_entitlements WHERE id = %s FOR UPDATE", (pass_id,))
        entitlement = cur.fetchone()
        require(entitlement is not None, 404, "Pass not found")
        changes = []
        if delta:
            require(entitlement["kind"] == "punch_card", 400, "Only punch cards have punches to adjust")
            remaining = entitlement["punches_remaining"] + delta
            require(remaining >= 0, 409, f"{entitlement['name']} only has {entitlement['punches_remaining']} punch(es) left")
            cur.execute("UPDATE golf_entitlements SET punches_remaining = %s, punches_total = greatest(punches_total, %s) "
                        "WHERE id = %s", (remaining, remaining, pass_id))
            changes.append(f"{delta:+d} punch{'es' if abs(delta) > 1 else ''} ({remaining} left)")
        if "valid_until" in payload:
            valid_until = domain.parse_date(payload["valid_until"]) if payload["valid_until"] else None
            require(valid_until is not None or entitlement["kind"] == "punch_card", 400, "Memberships need an end date")
            require(valid_until is None or valid_until >= entitlement["valid_from"], 400,
                    "The end date can't be before the start date")
            cur.execute("UPDATE golf_entitlements SET valid_until = %s WHERE id = %s", (valid_until, pass_id))
            changes.append(f"valid through {valid_until:%b} {valid_until.day}, {valid_until.year}" if valid_until else "no expiry")
        if status and status != entitlement["status"]:
            cur.execute("UPDATE golf_entitlements SET status = %s WHERE id = %s", (status, pass_id))
            changes.append("voided" if status == "void" else "reactivated")
        require(bool(changes), 400, "Nothing to change")
        add_ledger(cur, player_id=entitlement["player_id"], kind="pass_adjust", user=user, entitlement_id=pass_id,
                   description=f"{entitlement['name']}: {', '.join(changes)}. Reason: {reason}")


def sell_range_buckets(conn, user: dict, payload: dict) -> None:
    product_id = domain.clean_int(payload.get("product_id"), "Bucket", 1, 2**31)
    quantity = domain.clean_int(payload.get("quantity", 1), "Quantity", 1, 20)
    player_id = payload.get("player_id")
    with conn.transaction(), conn.cursor() as cur:
        settings = load_settings(cur)
        cur.execute("SELECT * FROM golf_products WHERE id = %s AND kind = 'range_bucket'", (product_id,))
        product = cur.fetchone()
        require(product is not None, 404, "Bucket size not found")
        require(product["active"], 409, f"{product['name']} is not currently offered")
        if player_id is not None:
            player_id = domain.clean_int(player_id, "Player", 1, 2**62)
            load_players(cur, [player_id])
        billing, entitlement_id, note = "unbilled", None, ""
        if payload.get("pass_id") is not None:
            require(player_id is not None, 400, "Choose the player whose pass to use")
            _, entitlement = use_pass(cur, user, player_id=player_id, kind=None, pass_id=payload["pass_id"],
                                      used_for="range", used_on=course_today(settings), punches=quantity)
            billing, entitlement_id, note = "covered", entitlement["id"], f" on {pass_note(entitlement)}"
        add_ledger(cur, player_id=player_id, kind="range_bucket", user=user, product_id=product_id, quantity=quantity,
                   billing=billing, entitlement_id=entitlement_id,
                   description=f"{quantity} × {product['name']} ({product['balls']} balls){note}")


# --------------------------------------------------------------------------- catalog and settings

PRODUCT_COLUMNS = ("id", "code", "kind", "name", "active", "price_cents", "punches", "valid_days", "covers",
                   "includes_range", "daily_round_limit", "bucket_size", "balls", "sort_order")
SELLABLE_KINDS = ("punch_card", "membership", "range_bucket")


def list_products(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(PRODUCT_COLUMNS)} FROM golf_products ORDER BY sort_order, id")
        return cur.fetchall()


def clean_product_fields(payload: dict, kind: str) -> dict:
    fields: dict = {}
    if "name" in payload:
        fields["name"] = domain.clean_text(payload["name"], "Name", 80)
    if "active" in payload:
        require(isinstance(payload["active"], bool), 400, "Active must be true or false")
        fields["active"] = payload["active"]
    if "price_cents" in payload:
        price = payload["price_cents"]
        fields["price_cents"] = None if price in (None, "") else domain.clean_int(price, "Price", 0, 10_000_000)
    if "sort_order" in payload:
        fields["sort_order"] = domain.clean_int(payload["sort_order"], "Sort order", -1000, 1000)
    if kind == "punch_card":
        if "punches" in payload:
            fields["punches"] = domain.clean_int(payload["punches"], "Punches", 1, 500)
        if "valid_days" in payload:
            days = payload["valid_days"]
            fields["valid_days"] = None if days in (None, "") else domain.clean_int(days, "Valid days", 1, 3660)
        if "covers" in payload:
            require(payload["covers"] in ("round", "range"), 400, "A punch card covers rounds or range buckets")
            fields["covers"] = payload["covers"]
    elif kind == "membership":
        if "valid_days" in payload:
            fields["valid_days"] = domain.clean_int(payload["valid_days"], "Valid days", 1, 3660)
        if "includes_range" in payload:
            require(isinstance(payload["includes_range"], bool), 400, "Includes range must be true or false")
            fields["includes_range"] = payload["includes_range"]
        if "daily_round_limit" in payload:
            limit = payload["daily_round_limit"]
            fields["daily_round_limit"] = None if limit in (None, "") else domain.clean_int(limit, "Rounds per day", 1, 10)
    elif kind == "range_bucket":
        if "bucket_size" in payload:
            require(payload["bucket_size"] in ("small", "large"), 400, "Bucket size must be small or large")
            fields["bucket_size"] = payload["bucket_size"]
        if "balls" in payload:
            fields["balls"] = domain.clean_int(payload["balls"], "Balls", 1, 1000)
    return fields


def create_product(conn, user: dict, payload: dict) -> int:
    kind = payload.get("kind")
    require(kind in SELLABLE_KINDS, 400, "New products can be punch cards, memberships or range buckets")
    fields = clean_product_fields(payload, kind)
    require("name" in fields, 400, "Name is required")
    code = payload.get("code") or "-".join("".join(ch if ch.isascii() and ch.isalnum() else " "
                                                    for ch in fields["name"].lower()).split())
    code = code[:40].strip("-") if isinstance(code, str) else ""
    require(bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", code)), 400,
            "Product codes use lowercase letters, numbers and dashes")
    fields.update(kind=kind, code=code)
    try:
        with conn.transaction(), conn.cursor() as cur:
            columns = list(fields)
            cur.execute(f"INSERT INTO golf_products ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) "
                        "RETURNING id", [fields[c] for c in columns])
            product_id = cur.fetchone()["id"]
            add_ledger(cur, player_id=None, kind="catalog", user=user, product_id=product_id,
                       description=f"Added {fields['name']} to the catalog")
            return product_id
    except psycopg.errors.UniqueViolation:
        raise ApiError(409, "A product with that code already exists") from None
    except psycopg.errors.CheckViolation:
        raise ApiError(400, "Fill in every field this kind of product needs") from None


def update_product(conn, user: dict, product_id: int, payload: dict) -> None:
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT id, kind, name FROM golf_products WHERE id = %s FOR UPDATE", (product_id,))
        product = cur.fetchone()
        require(product is not None, 404, "Product not found")
        fields = clean_product_fields(payload, product["kind"])
        if not fields:
            return
        assignments = ", ".join(f"{column} = %s" for column in fields)
        cur.execute(f"UPDATE golf_products SET {assignments} WHERE id = %s", [*fields.values(), product_id])
        add_ledger(cur, player_id=None, kind="catalog", user=user, product_id=product_id,
                   description=f"Updated {fields.get('name', product['name'])} in the catalog")


def update_settings(conn, user: dict, payload: dict) -> dict:
    with conn.transaction(), conn.cursor() as cur:
        current = load_settings(cur, "FOR UPDATE")
        new = {key: current[key] for key in SETTINGS_COLUMNS}
        if "course_name" in payload:
            new["course_name"] = domain.clean_text(payload["course_name"], "Course name", 80)
        if "time_zone" in payload:
            try:
                ZoneInfo(str(payload["time_zone"]))
            except (ZoneInfoNotFoundError, ValueError):
                raise RuleError("Unknown time zone; use a name like America/Los_Angeles") from None
            new["time_zone"] = str(payload["time_zone"])
        for key, label in (("opening_time", "Opening time"), ("closing_time", "Last tee time")):
            if key in payload:
                new[key] = domain.parse_hhmm(payload[key], label)
        limits = {"tee_interval_minutes": ("Tee interval", 5, 60), "average_round_minutes": ("Average round", 30, 720),
                  "booking_window_days": ("Booking window", 1, 365), "riding_cart_count": ("Riding carts", 0, 200),
                  "pull_cart_count": ("Pull carts", 0, 200), "club_sets_right": ("Right-handed club sets", 0, 200),
                  "club_sets_left": ("Left-handed club sets", 0, 200)}
        for key, (label, low, high) in limits.items():
            if key in payload:
                new[key] = domain.clean_int(payload[key], label, low, high)
        domain.tee_slots(new["opening_time"], new["closing_time"], new["tee_interval_minutes"])

        for key, (kind, hand) in COUNT_UNITS.items():
            if new[key] < current[key]:
                cur.execute(
                    """
                    SELECT u.label FROM golf_rental_units u JOIN golf_rentals r ON r.unit_id = u.id
                    WHERE u.kind = %s AND u.hand IS NOT DISTINCT FROM %s AND u.number > %s
                      AND r.returned_at IS NULL AND (r.due_at > %s OR r.starts_at <= %s)
                    ORDER BY u.number LIMIT 1
                    """,
                    (kind, hand, new[key], now(), now()),
                )
                busy = cur.fetchone()
                require(busy is None, 409, f"{busy['label'] if busy else ''} is out or reserved. Return it or change "
                                           "those bookings before lowering the count.")
        assignments = ", ".join(f"{column} = %s" for column in SETTINGS_COLUMNS)
        cur.execute(f"UPDATE golf_settings SET {assignments}, updated_at = now() WHERE singleton",
                    [new[key] for key in SETTINGS_COLUMNS])
        cur.execute("SELECT golf_sync_rental_units()")
        add_ledger(cur, player_id=None, kind="settings", user=user, description="Course settings updated")
        return settings_json(load_settings(cur))
