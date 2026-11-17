"""Pure golf rules shared by the API and its tests. Nothing here touches the database."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

MAX_PLAYERS = 4
CLUB_CHOICES = ("none", "right", "left")
RENTAL_KINDS = ("riding_cart", "pull_cart", "club_set")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RuleError(ValueError):
    """A request broke a course rule; the message is safe to show to the user."""


def clean_text(value: object, field: str, max_length: int, required: bool = True) -> str | None:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise RuleError(f"{field} must be text")
    value = " ".join(value.split())
    if not value:
        if required:
            raise RuleError(f"{field} is required")
        return None
    if len(value) > max_length:
        raise RuleError(f"{field} must be {max_length} characters or fewer")
    return value


def clean_email(value: object, required: bool = True) -> str | None:
    email = clean_text(value, "Email", 254, required)
    if email is None:
        return None
    email = email.lower()
    if not EMAIL_RE.match(email):
        raise RuleError("Enter a valid email address")
    return email


def clean_int(value: object, field: str, low: int, high: int) -> int:
    if isinstance(value, bool):
        raise RuleError(f"{field} must be a whole number")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise RuleError(f"{field} must be a whole number") from None
    if isinstance(value, float) and value != number:
        raise RuleError(f"{field} must be a whole number")
    if not low <= number <= high:
        raise RuleError(f"{field} must be between {low} and {high}")
    return number


def parse_date(value: object) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        raise RuleError("Dates must look like 2026-11-17") from None


def parse_hhmm(value: object, field: str = "Time") -> time:
    try:
        return datetime.strptime(str(value)[:5], "%H:%M").time()
    except ValueError:
        raise RuleError(f"{field} must look like 07:30") from None


def hhmm(value: time) -> str:
    return value.strftime("%H:%M")


def tee_slots(opening: time, closing: time, interval_minutes: int) -> list[time]:
    """Tee times from opening to closing inclusive, every interval_minutes."""
    if not 5 <= interval_minutes <= 60:
        raise RuleError("Tee interval must be between 5 and 60 minutes")
    if opening >= closing:
        raise RuleError("Opening time must be before closing time")
    slots = []
    minutes = opening.hour * 60 + opening.minute
    last = closing.hour * 60 + closing.minute
    while minutes <= last:
        slots.append(time(minutes // 60, minutes % 60))
        minutes += interval_minutes
    return slots


def local_tee_time(day: date, slot: time, zone: tzinfo) -> datetime:
    return datetime.combine(day, slot, zone)


def intervals_overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    """Half-open intervals: a rental due back at 9:30 does not clash with one starting at 9:30."""
    return start_a < end_b and start_b < end_a


@dataclass(frozen=True)
class PlayerChoice:
    """One player in a booking request: an account holder, a known player (staff only) or a named guest."""
    player_id: int | None
    guest_name: str | None
    clubs: str
    pull_cart: bool


def parse_options(raw: object) -> tuple[str, bool]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RuleError("Player options must be an object")
    clubs = raw.get("clubs", "none")
    if clubs is None or clubs is False:
        clubs = "none"
    if clubs is True:
        clubs = "right"
    if clubs not in CLUB_CHOICES:
        raise RuleError("Rental clubs must be none, right or left")
    pull_cart = raw.get("pull_cart", False)
    if not isinstance(pull_cart, bool):
        raise RuleError("Pull cart must be true or false")
    return clubs, pull_cart


def parse_party(captain_options: object, guests: object, allow_player_ids: bool) -> list[PlayerChoice]:
    """The captain first, then up to three guests. Guest names are unique within the group."""
    clubs, pull_cart = parse_options(captain_options)
    party = [PlayerChoice(None, None, clubs, pull_cart)]
    if guests is None:
        guests = []
    if not isinstance(guests, list):
        raise RuleError("Guests must be a list")
    if len(guests) > MAX_PLAYERS - 1:
        raise RuleError(f"A tee time holds at most {MAX_PLAYERS} players")
    seen_names: set[str] = set()
    seen_ids: set[int] = set()
    for index, guest in enumerate(guests, start=2):
        if not isinstance(guest, dict):
            raise RuleError("Each guest must be an object")
        clubs, pull_cart = parse_options(guest)
        player_id = guest.get("player_id")
        if player_id is not None:
            if not allow_player_ids:
                raise RuleError("Only course staff can add players from the player list")
            player_id = clean_int(player_id, "Player", 1, 2**62)
            if player_id in seen_ids:
                raise RuleError("That player is already in this group")
            seen_ids.add(player_id)
            party.append(PlayerChoice(player_id, None, clubs, pull_cart))
            continue
        name = clean_text(guest.get("name"), f"Player {index} name", 80)
        if name.casefold() in seen_names:
            raise RuleError(f"{name} is already in this group")
        seen_names.add(name.casefold())
        party.append(PlayerChoice(None, name, clubs, pull_cart))
    return party


def short_name(full_name: str | None) -> str:
    """'Brett Dawson' -> 'Brett D.' so other golfers see who is in a group without full names."""
    parts = (full_name or "").split()
    if not parts:
        return "Player"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0]}."


def pass_valid_until(valid_from: date, valid_days: int | None) -> date | None:
    """Inclusive last day: a 365-day pass from 1 Jan is good through 31 Dec."""
    if valid_days is None:
        return None
    return valid_from + timedelta(days=valid_days - 1)


def pass_state(kind: str, status: str, valid_from: date, valid_until: date | None,
               punches_remaining: int | None, today: date) -> str:
    if status != "active":
        return "void"
    if today < valid_from:
        return "upcoming"
    if valid_until is not None and today > valid_until:
        return "expired"
    if kind == "punch_card" and (punches_remaining or 0) <= 0:
        return "used_up"
    return "active"


def unit_status(in_service: bool, active: bool, current: dict | None, upcoming: dict | None,
                now: datetime) -> str:
    """Inventory state of one cart or club set.

    current is the latest unreturned rental that has started, upcoming the next unreturned one
    that has not. A unit that is out past its estimated return stays 'overdue' until staff mark
    it returned, so it is never handed to someone else while it is still on the course."""
    if not active:
        return "retired"
    if current is not None:
        return "overdue" if current["due_at"] <= now else "rented"
    if not in_service:
        return "out_of_service"
    if upcoming is not None:
        return "reserved"
    return "available"


def rental_description(kind: str, hand: str | None = None, plural: bool = False) -> str:
    if kind == "club_set":
        base = f"{'left' if hand == 'left' else 'right'}-handed club set"
    elif kind == "pull_cart":
        base = "pull cart"
    else:
        base = "riding cart"
    return base + ("s" if plural else "")
