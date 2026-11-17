"""Unit tests for the pure golf rules (no database needed)."""
from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta, timezone

import golf_support  # noqa: F401  (puts golf/api on the import path)
import domain
import security
import service
from domain import RuleError

UTC = timezone.utc


class TeeSheetRules(unittest.TestCase):
    def test_database_time_zone_bytes_are_normalized(self):
        self.assertEqual(service.text_value(b"America/Los_Angeles"), "America/Los_Angeles")
        self.assertEqual(service.text_value(bytearray(b"UTC")), "UTC")
        self.assertEqual(service.text_value(memoryview(b"America/New_York")), "America/New_York")

    def test_slots_run_from_opening_to_last_tee_time_inclusive(self):
        self.assertEqual([domain.hhmm(t) for t in domain.tee_slots(time(7), time(8), 20)],
                         ["07:00", "07:20", "07:40", "08:00"])
        with self.assertRaises(RuleError):
            domain.tee_slots(time(7), time(17), 4)
        with self.assertRaises(RuleError):
            domain.tee_slots(time(17), time(7), 10)

    def test_party_is_the_captain_plus_up_to_three_guests(self):
        party = domain.parse_party({"clubs": "left", "pull_cart": True},
                                   [{"name": "Lou", "pull_cart": True}, {"name": "Max", "clubs": "right"}], False)
        self.assertEqual([(p.guest_name, p.clubs, p.pull_cart) for p in party],
                         [(None, "left", True), ("Lou", "none", True), ("Max", "right", False)])
        with self.assertRaises(RuleError):
            domain.parse_party({}, [{"name": n} for n in "ABCD"], False)
        with self.assertRaises(RuleError):
            domain.parse_party({}, [{"name": "Lou"}, {"name": "lou"}], False)
        with self.assertRaises(RuleError):
            domain.parse_party({}, [{"player_id": 7}], allow_player_ids=False)
        with self.assertRaises(RuleError):
            domain.parse_options({"clubs": "both"})

    def test_names_shown_to_other_golfers_are_shortened(self):
        self.assertEqual(domain.short_name("Brett  Dawson"), "Brett D.")
        self.assertEqual(domain.short_name("Cher"), "Cher")
        self.assertEqual(domain.short_name(""), "Player")


class RentalRules(unittest.TestCase):
    def test_rental_windows_are_half_open(self):
        start = datetime(2026, 11, 17, 9, tzinfo=UTC)
        due = start + timedelta(minutes=150)
        self.assertTrue(domain.intervals_overlap(start, due, start + timedelta(hours=1), due + timedelta(hours=1)))
        self.assertFalse(domain.intervals_overlap(start, due, due, due + timedelta(minutes=150)))

    def test_unit_status(self):
        now = datetime(2026, 11, 17, 12, tzinfo=UTC)
        out = {"due_at": now + timedelta(minutes=30)}
        late = {"due_at": now - timedelta(minutes=1)}
        later = {"due_at": now + timedelta(hours=5)}
        self.assertEqual(domain.unit_status(True, True, out, None, now), "rented")
        self.assertEqual(domain.unit_status(True, True, late, None, now), "overdue")
        self.assertEqual(domain.unit_status(False, True, out, None, now), "rented")  # still on the course
        self.assertEqual(domain.unit_status(False, True, None, later, now), "out_of_service")
        self.assertEqual(domain.unit_status(True, True, None, later, now), "reserved")
        self.assertEqual(domain.unit_status(True, True, None, None, now), "available")
        self.assertEqual(domain.unit_status(True, False, None, None, now), "retired")


class PassRules(unittest.TestCase):
    def test_validity_is_inclusive(self):
        self.assertEqual(domain.pass_valid_until(date(2027, 1, 1), 365), date(2027, 12, 31))
        self.assertIsNone(domain.pass_valid_until(date(2027, 1, 1), None))

    def test_pass_state(self):
        today = date(2027, 6, 1)
        self.assertEqual(domain.pass_state("membership", "active", date(2027, 1, 1), date(2027, 12, 31), None, today), "active")
        self.assertEqual(domain.pass_state("membership", "active", date(2026, 1, 1), date(2026, 12, 31), None, today), "expired")
        self.assertEqual(domain.pass_state("membership", "active", date(2027, 7, 1), date(2028, 6, 30), None, today), "upcoming")
        self.assertEqual(domain.pass_state("punch_card", "active", date(2027, 1, 1), None, 0, today), "used_up")
        self.assertEqual(domain.pass_state("punch_card", "void", date(2027, 1, 1), None, 5, today), "void")


class SecurityRules(unittest.TestCase):
    def test_passwords_round_trip_and_reject_wrong_ones(self):
        encoded = security.hash_password("correct horse battery")
        self.assertTrue(security.verify_password("correct horse battery", encoded))
        self.assertFalse(security.verify_password("correct horse batterY", encoded))
        self.assertFalse(security.verify_password("anything", "not-a-hash"))
        with self.assertRaises(ValueError):
            security.check_password_policy("short")

    def test_player_codes_are_easy_to_read_aloud(self):
        code = security.new_claim_code()
        self.assertEqual(len(code), 8)
        self.assertFalse(set(code) & set("01IOL"))
        self.assertEqual(security.normalize_claim_code(" abcd-efgh "), "ABCDEFGH")


if __name__ == "__main__":
    unittest.main()
