"""Integration tests for the golf API against a real PostgreSQL server.

Run with a disposable server, for example:

    docker run -d --name golf-test-pg -e POSTGRES_PASSWORD=golf -p 127.0.0.1:55432:5432 postgres:16
    GOLF_TEST_DATABASE_URL=postgresql://postgres:golf@127.0.0.1:55432/postgres python -m unittest discover -s tests
"""
from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta

from golf_support import Client, GolfDatabaseTest, drop_template


def tearDownModule():
    drop_template()


def run_together(calls) -> list[tuple[int, dict]]:
    """Start every call at the same moment on its own thread and connection."""
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def worker(index, call):
        barrier.wait()
        results[index] = call()

    threads = [threading.Thread(target=worker, args=(i, call)) for i, call in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


class AccountTests(GolfDatabaseTest):
    def test_roles_sessions_and_login(self):
        self.assertTrue(self.staff.me["is_staff"])
        player = self.signup("Alex Rivera")
        self.assertFalse(player.me["is_staff"])
        self.assertEqual(player.get("/players")[0], 403)
        self.assertEqual(player.get("/me")[0], 200)

        player.post("/auth/logout")
        self.assertIsNone(player.token)
        self.assertEqual(player.get("/me")[0], 401)
        self.assertEqual(Client().post("/auth/login", {"email": player.email, "password": "wrong password!"})[0], 401)
        again = Client()
        again.ok("POST", "/auth/login", {"email": player.email, "password": "correct horse battery"})
        self.assertEqual(again.ok("GET", "/me")["player"]["full_name"], "Alex Rivera")
        self.assertEqual(Client().post("/auth/register", {"email": player.email, "password": "another long one",
                                                          "full_name": "Copy"})[0], 409)

    def test_bootstrap_email_only_creates_the_first_staff_account(self):
        import os
        os.environ["GOLF_BOOTSTRAP_STAFF_EMAIL"] = "late@example.com"
        late = self.signup("Late Comer", "late@example.com")  # a staff account already exists
        self.assertFalse(late.me["is_staff"])
        relogin = Client()
        relogin.ok("POST", "/auth/login", {"email": "late@example.com", "password": "correct horse battery"})
        self.assertFalse(relogin.ok("GET", "/app")["user"]["is_staff"])

    def test_player_code_links_a_new_account_to_an_existing_player_record(self):
        player_id = self.staff.ok("POST", "/players", {"full_name": "Morgan Lee", "phone": "555-0101"})["player_id"]
        punch = self.product("punch-10")
        self.staff.ok("POST", f"/players/{player_id}/passes", {"product_id": punch["id"]})
        code = self.staff.ok("POST", f"/players/{player_id}/player-code")["code"]

        morgan = self.signup("Morgan L", player_code=code.lower())
        profile = morgan.ok("GET", "/me")
        self.assertEqual(profile["player"]["id"], player_id)
        self.assertEqual(profile["player"]["full_name"], "Morgan Lee")
        self.assertEqual(profile["passes"][0]["punches_remaining"], 10)
        self.assertTrue(any("issued" in item["description"] for item in profile["history"]))

        status, payload = Client().post("/auth/register", {"email": "other@example.com", "password": "correct horse battery",
                                                           "full_name": "Other", "player_code": code})
        self.assertEqual(status, 400)
        self.assertIn("not valid", payload["error"])

    def product(self, code: str) -> dict:
        return next(p for p in self.staff.ok("GET", "/products")["products"] if p["code"] == code)


class BookingTests(GolfDatabaseTest):
    def test_bookings_hold_one_to_four_players(self):
        alex = self.signup("Alex Rivera")
        self.assertEqual(Client().post("/bookings", {"date": self.tomorrow, "time": "09:00"})[0], 401)
        status, payload = self.book(alex, guests=[{"name": f"Guest {i}"} for i in range(4)])
        self.assertEqual(status, 400)
        self.assertIn("at most 4", payload["error"])

        self.assertEqual(self.book(alex, "08:00")[0], 201)
        self.assertEqual(self.sheet_slot(alex, "08:00")["booking"]["open_spots"], 3)
        status, _ = self.book(self.signup("Sam Ortiz"), "12:00", guests=[{"name": "Kim"}, {"name": "Lou"}, {"name": "Max"}])
        self.assertEqual(status, 201)
        self.assertEqual(self.sheet_slot(alex, "12:00")["booking"]["open_spots"], 0)
        self.assertEqual(self.book(alex, "09:05")[0], 400)  # not on the 10-minute sheet

    def test_one_group_per_tee_time(self):
        self.assertEqual(self.book(self.signup("Alex Rivera"))[0], 201)
        status, payload = self.book(self.signup("Sam Ortiz"))
        self.assertEqual(status, 409)
        self.assertIn("Join their group", payload["error"])

    def test_join_and_leave_never_exceed_four(self):
        alex, sam, kim = self.signup("Alex Rivera"), self.signup("Sam Ortiz"), self.signup("Kim Park")
        booking_id = self.book(alex, guests=[{"name": "Lou"}, {"name": "Max"}])[1]["booking_id"]
        self.assertEqual(sam.post(f"/bookings/{booking_id}/join")[0], 200)
        self.assertEqual(sam.post(f"/bookings/{booking_id}/join")[0], 409)
        status, payload = kim.post(f"/bookings/{booking_id}/join")
        self.assertEqual(status, 409)
        self.assertIn("room for 0", payload["error"])

        sam.ok("POST", f"/bookings/{booking_id}/leave")
        kim.ok("POST", f"/bookings/{booking_id}/join", {"me": {"clubs": "right"}})
        self.assertEqual(self.sql("SELECT count(*) AS n FROM golf_booking_players")[0]["n"], 4)

    def test_concurrent_joins_fill_the_last_spot_once(self):
        alex = self.signup("Alex Rivera")
        booking_id = self.book(alex, guests=[{"name": "Lou"}, {"name": "Max"}])[1]["booking_id"]
        joiners = [self.signup(f"Joiner {i}") for i in range(5)]
        results = run_together([lambda c=c: c.post(f"/bookings/{booking_id}/join") for c in joiners])
        self.assertEqual(sorted(status for status, _ in results), [200, 409, 409, 409, 409])
        self.assertEqual(self.sql("SELECT count(*) AS n FROM golf_booking_players WHERE booking_id = %s",
                                  (booking_id,))[0]["n"], 4)

    def test_database_rejects_a_fifth_player_even_without_the_api(self):
        alex = self.signup("Alex Rivera")
        booking_id = self.book(alex, guests=[{"name": "A"}, {"name": "B"}, {"name": "C"}])[1]["booking_id"]
        import psycopg
        with self.assertRaises(psycopg.errors.RaiseException):
            self.sql("INSERT INTO golf_booking_players (booking_id, guest_name) VALUES (%s, 'Extra')", (booking_id,))

    def test_captain_leaving_hands_over_the_group_and_takes_their_guests(self):
        self.set_counts(pull_cart_count=2)
        alex, sam = self.signup("Alex Rivera"), self.signup("Sam Ortiz")
        booking_id = self.book(alex, guests=[{"name": "Lou", "pull_cart": True}])[1]["booking_id"]
        sam.ok("POST", f"/bookings/{booking_id}/join")
        alex.ok("POST", f"/bookings/{booking_id}/leave")

        booking = self.sheet_slot(self.staff, "09:00")["booking"]
        self.assertEqual([p["name"] for p in booking["players"]], ["Sam Ortiz"])
        self.assertTrue(booking["players"][0]["is_captain"])
        self.assertEqual(self.sql("SELECT count(*) AS n FROM golf_rentals")[0]["n"], 0)

        sam.ok("POST", f"/bookings/{booking_id}/leave")
        self.assertIsNone(self.sheet_slot(self.staff, "09:00")["booking"])

    def test_riding_carts_and_their_charges_follow_the_new_captain(self):
        alex, sam = self.signup("Alex Rivera"), self.signup("Sam Ortiz")
        booking_id = self.book(alex, riding_carts=1)[1]["booking_id"]
        sam.ok("POST", f"/bookings/{booking_id}/join")
        alex.ok("POST", f"/bookings/{booking_id}/leave")
        rental = self.sql("SELECT player_id, holder_name FROM golf_rentals")[0]
        self.assertEqual((rental["player_id"], rental["holder_name"]), (sam.me["player_id"], "Sam Ortiz"))
        charge = self.sql("SELECT player_id FROM golf_ledger WHERE kind = 'rental' AND billing_status = 'unbilled'")
        self.assertEqual([row["player_id"] for row in charge], [sam.me["player_id"]])
        self.assertEqual(alex.ok("GET", "/me")["rentals"], [])

    def test_a_player_cannot_hold_overlapping_tee_times(self):
        alex = self.signup("Alex Rivera")
        self.assertEqual(self.book(alex, "09:00")[0], 201)
        status, payload = self.book(alex, "10:00")
        self.assertEqual(status, 409)
        self.assertIn("already has a 9:00 AM tee time", payload["error"])
        self.assertEqual(self.book(alex, "11:30")[0], 201)

    def test_tee_sheet_privacy(self):
        alex = self.signup("Alex Rivera")
        self.book(alex, guests=[{"name": "Lou Grant", "clubs": "left"}])
        public = self.sheet_slot(Client(), "09:00")["booking"]
        self.assertEqual([p["name"] for p in public["players"]], ["Booked", "Booked"])
        self.assertNotIn("clubs", public["players"][0])
        other = self.sheet_slot(self.signup("Sam Ortiz"), "09:00")["booking"]
        self.assertEqual([p["name"] for p in other["players"]], ["Alex R.", "Lou G."])
        self.assertTrue(other["can_join"])
        staff = self.sheet_slot(self.staff, "09:00")["booking"]
        self.assertEqual(staff["players"][1]["name"], "Lou Grant")
        self.assertEqual(staff["players"][1]["gear"], ["LH clubs 01"])


class RentalTests(GolfDatabaseTest):
    def test_each_player_can_choose_rental_clubs_and_or_a_pull_cart(self):
        alex = self.signup("Alex Rivera")
        status, _ = self.book(alex, captain={"clubs": "left", "pull_cart": True},
                              guests=[{"name": "Lou", "clubs": "right"}, {"name": "Max", "pull_cart": True}, {"name": "Kim"}],
                              riding_carts=1)
        self.assertEqual(status, 201)
        players = self.sheet_slot(self.staff, "09:00")["booking"]["players"]
        self.assertEqual({p["name"]: (p["clubs"], p["pull_cart"], p["gear"]) for p in players}, {
            "Alex Rivera": ("left", True, ["LH clubs 01", "Pull cart 01"]),
            "Lou": ("right", False, ["RH clubs 01"]),
            "Max": ("none", True, ["Pull cart 02"]),
            "Kim": ("none", False, []),
        })
        self.assertEqual(self.sheet_slot(self.staff, "09:00")["booking"]["riding_cart_labels"], ["Cart 01"])

    def test_a_rental_shortage_cancels_the_whole_booking(self):
        self.set_counts(club_sets_left=1)
        self.assertEqual(self.book(self.signup("Alex Rivera"), "09:00", captain={"clubs": "left"})[0], 201)
        sam = self.signup("Sam Ortiz")
        status, payload = self.book(sam, "10:00", captain={"pull_cart": True}, guests=[{"name": "Lou", "clubs": "left"}])
        self.assertEqual(status, 409)
        self.assertIn("left-handed club sets", payload["error"])
        self.assertEqual(self.sql("SELECT count(*) AS n FROM golf_bookings")[0]["n"], 1)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM golf_rentals")[0]["n"], 1)
        # A round is 2 h 30 min, so the set is free again for the 11:30 tee time.
        self.assertEqual(self.book(sam, "11:30", captain={"clubs": "left"})[0], 201)

    def test_riding_carts_cannot_be_overbooked(self):
        self.set_counts(riding_cart_count=1)
        self.assertEqual(self.book(self.signup("Alex Rivera"), "09:00", riding_carts=1)[0], 201)
        sam = self.signup("Sam Ortiz")
        self.assertEqual(self.book(sam, "10:00", riding_carts=1)[0], 409)
        booking_id = self.book(sam, "10:00")[1]["booking_id"]
        status, payload = sam.put(f"/bookings/{booking_id}/riding-carts", {"count": 1})
        self.assertEqual(status, 409)
        self.assertIn("riding carts", payload["error"])
        self.assertEqual(sam.put(f"/bookings/{booking_id}/riding-carts", {"count": 2})[0], 400)  # more carts than players

    def test_concurrent_bookings_cannot_share_the_last_pull_cart(self):
        self.set_counts(pull_cart_count=1)
        golfers = [self.signup(f"Golfer {i}") for i in range(4)]
        times = ["09:00", "09:10", "09:20", "09:30"]
        results = run_together([lambda c=c, t=t: self.book(c, t, captain={"pull_cart": True})
                                for c, t in zip(golfers, times)])
        self.assertEqual(sorted(status for status, _ in results), [201, 409, 409, 409])
        self.assertEqual(self.sql("SELECT count(*) AS n FROM golf_rentals")[0]["n"], 1)

    def test_players_can_change_their_rentals_later(self):
        self.set_counts(club_sets_left=1)
        alex = self.signup("Alex Rivera")
        self.book(alex)
        me = self.sheet_slot(alex, "09:00")["booking"]["players"][0]
        alex.ok("PUT", f"/booking-players/{me['id']}", {"clubs": "left", "pull_cart": True})
        self.assertEqual(len(self.sql("SELECT id FROM golf_rentals")), 2)
        self.assertEqual(self.signup("Sam Ortiz").put(f"/booking-players/{me['id']}", {"clubs": "none"})[0], 403)
        alex.ok("PUT", f"/booking-players/{me['id']}", {"clubs": "none", "pull_cart": False})
        self.assertEqual(self.sql("SELECT count(*) AS n FROM golf_rentals")[0]["n"], 0)
        # Changing your mind before the round leaves nothing to bill.
        billed = self.sql("SELECT count(*) AS n FROM golf_ledger WHERE kind = 'rental' AND billing_status = 'unbilled'")
        self.assertEqual(billed[0]["n"], 0)

    def test_saving_unchanged_rentals_never_re_reserves_returned_gear(self):
        self.set_counts(club_sets_right=1)
        alex = self.signup("Alex Rivera")
        self.book(alex, captain={"clubs": "right"})
        me = self.sheet_slot(self.staff, "09:00")["booking"]["players"][0]
        # The round is over and the clubs came back.
        self.sql("UPDATE golf_rentals SET returned_at = now()")
        self.staff.ok("PUT", f"/booking-players/{me['id']}", {"clubs": "right", "pull_cart": False})
        self.assertEqual(self.sql("SELECT count(*) AS n FROM golf_rentals WHERE returned_at IS NULL")[0]["n"], 0)
        self.assertEqual(self.book(self.signup("Sam Ortiz"), "10:00", captain={"clubs": "right"})[0], 201)

    def test_walk_in_rental_status_estimated_return_and_return(self):
        player_id = self.staff.ok("POST", "/players", {"full_name": "Walk Up"})["player_id"]
        rental = self.staff.ok("POST", "/rentals", {"kind": "riding_cart", "player_id": player_id})
        unit = self.unit("Cart 01")
        self.assertEqual(unit["status"], "rented")
        started = datetime.fromisoformat(unit["current"]["starts_at"])
        due = datetime.fromisoformat(unit["current"]["due_at"])
        self.assertEqual(due - started, timedelta(hours=2, minutes=30))
        self.assertEqual(unit["current"]["holder"], "Walk Up")

        self.assertEqual(self.signup("Alex Rivera").post(f"/rentals/{rental['id']}/return")[0], 403)
        self.staff.ok("POST", f"/rentals/{rental['id']}/return")
        self.assertEqual(self.unit("Cart 01")["status"], "available")
        self.assertEqual(self.staff.post(f"/rentals/{rental['id']}/return")[0], 409)
        summary = Client().ok("GET", "/inventory")
        self.assertEqual(summary["groups"][0]["units"], [])  # only staff see unit details
        self.assertEqual(summary["groups"][0]["available"], 20)

    def test_overdue_units_are_held_back_until_returned(self):
        self.set_counts(pull_cart_count=1)
        unit_id = self.sql("SELECT id FROM golf_rental_units WHERE label = 'Pull cart 01'")[0]["id"]
        rental_id = self.sql(
            "INSERT INTO golf_rentals (unit_id, holder_name, starts_at, due_at) "
            "VALUES (%s, 'Late Larry', now() - interval '4 hours', now() - interval '90 minutes') RETURNING id",
            (unit_id,))[0]["id"]
        self.assertEqual(self.unit("Pull cart 01")["status"], "overdue")
        alex = self.signup("Alex Rivera")
        self.assertEqual(self.book(alex, captain={"pull_cart": True})[0], 409)
        self.staff.ok("POST", f"/rentals/{rental_id}/return")
        self.assertEqual(self.book(alex, captain={"pull_cart": True})[0], 201)

    def test_out_of_service_unit_hands_its_reservations_to_another(self):
        self.set_counts(pull_cart_count=2)
        self.book(self.signup("Alex Rivera"), captain={"pull_cart": True})
        first, second = self.unit("Pull cart 01"), self.unit("Pull cart 02")
        self.assertEqual(first["status"], "reserved")
        self.staff.ok("PUT", f"/rental-units/{first['id']}", {"in_service": False, "notes": "Flat tyre"})
        self.assertEqual(self.unit("Pull cart 01")["status"], "out_of_service")
        self.assertEqual(self.unit("Pull cart 02")["status"], "reserved")
        status, payload = self.staff.put(f"/rental-units/{second['id']}", {"in_service": False})
        self.assertEqual(status, 409)
        self.assertIn("no other pull cart", payload["error"])

    def test_lowering_a_count_cannot_strand_a_reservation(self):
        self.set_counts(club_sets_right=2)
        self.book(self.signup("Alex Rivera"), "09:00", captain={"clubs": "right"})
        self.book(self.signup("Sam Ortiz"), "09:30", captain={"clubs": "right"})
        status, payload = self.staff.put("/settings", {"club_sets_right": 1})
        self.assertEqual(status, 409)
        self.assertIn("RH clubs 02", payload["error"])
        self.staff.ok("PUT", "/settings", {"club_sets_right": 4, "pull_cart_count": 3})
        self.assertEqual(self.sql("SELECT count(*) AS n FROM golf_rental_units WHERE kind = 'pull_cart' AND active")[0]["n"], 3)

    def unit(self, label: str) -> dict:
        for group in self.staff.ok("GET", "/inventory")["groups"]:
            for unit in group["units"]:
                if unit["label"] == label:
                    return unit
        raise AssertionError(f"no unit {label}")


class PassTests(GolfDatabaseTest):
    def setUp(self):
        super().setUp()
        self.products = {p["code"]: p for p in self.staff.ok("GET", "/products")["products"]}

    def player_with(self, code: str | None = None, name: str = "Alex Rivera") -> Client:
        client = self.signup(name)
        if code:
            self.issue(client.me["player_id"], code)
        return client

    def issue(self, player_id: int, code: str, **extra) -> int:
        return self.staff.ok("POST", f"/players/{player_id}/passes", {"product_id": self.products[code]["id"], **extra})["pass_id"]

    def booked_player(self, client: Client, date: str, time: str = "09:00") -> int:
        self.assertEqual(self.book(client, time, date=date)[0], 201)
        return self.sheet_slot(self.staff, time, date)["booking"]["players"][0]["id"]

    def test_punch_card_never_goes_below_zero(self):
        self.staff.ok("PUT", f"/products/{self.products['punch-10']['id']}", {"punches": 2, "name": "2-round card"})
        alex = self.player_with("punch-10")
        rounds = [self.booked_player(alex, self.day(n)) for n in (1, 2, 3)]
        for booking_player in rounds[:2]:
            self.staff.ok("POST", f"/booking-players/{booking_player}/check-in", {"coverage": "punch_card"})
        status, payload = self.staff.post(f"/booking-players/{rounds[2]}/check-in", {"coverage": "punch_card"})
        self.assertEqual(status, 409)
        self.assertIn("No valid punch card", payload["error"])

        punch_pass = alex.ok("GET", "/me")["passes"][0]
        self.assertEqual((punch_pass["punches_remaining"], punch_pass["state"]), (0, "used_up"))
        status, payload = self.staff.post(f"/booking-players/{rounds[2]}/check-in",
                                          {"coverage": "punch_card", "pass_id": punch_pass["id"]})
        self.assertEqual(status, 409)
        self.assertIn("0 punch(es) left", payload["error"])

        import psycopg
        with self.assertRaises(psycopg.errors.RaiseException):
            self.sql("INSERT INTO golf_entitlement_uses (entitlement_id, used_for, used_on, punches) VALUES (%s, 'round', %s, 1)",
                     (punch_pass["id"], self.day(3)))
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.sql("UPDATE golf_entitlements SET punches_remaining = -1 WHERE id = %s", (punch_pass["id"],))

        self.staff.ok("DELETE", f"/booking-players/{rounds[1]}/check-in")
        self.assertEqual(alex.ok("GET", "/me")["passes"][0]["punches_remaining"], 1)
        self.staff.ok("POST", f"/booking-players/{rounds[2]}/check-in", {"coverage": "punch_card"})

    def test_undoing_a_pay_at_counter_check_in_cancels_the_charge(self):
        alex = self.player_with()
        booking_player = self.booked_player(alex, self.tomorrow)
        self.staff.ok("POST", f"/booking-players/{booking_player}/check-in", {"coverage": "pay_at_counter"})
        self.staff.ok("DELETE", f"/booking-players/{booking_player}/check-in")
        self.staff.ok("POST", f"/booking-players/{booking_player}/check-in", {"coverage": "pay_at_counter"})
        fees = self.sql("SELECT billing_status FROM golf_ledger WHERE kind = 'check_in' ORDER BY id")
        self.assertEqual([row["billing_status"] for row in fees], ["none", "unbilled"])

    def test_passes_cannot_be_used_outside_their_dates_or_after_voiding(self):
        alex = self.player_with()
        pass_id = self.issue(alex.me["player_id"], "annual", valid_from=self.day(2))
        booking_player = self.booked_player(alex, self.tomorrow)
        status, payload = self.staff.post(f"/booking-players/{booking_player}/check-in",
                                          {"coverage": "membership", "pass_id": pass_id})
        self.assertEqual(status, 409)
        self.assertIn("not valid until", payload["error"])

        self.staff.ok("POST", f"/passes/{pass_id}/adjust", {"valid_until": self.day(5), "reason": "Short trial"})
        later = self.booked_player(alex, self.day(6))
        status, payload = self.staff.post(f"/booking-players/{later}/check-in", {"coverage": "membership", "pass_id": pass_id})
        self.assertEqual(status, 409)
        self.assertIn("expired", payload["error"])

        valid_day = self.booked_player(alex, self.day(3))
        self.staff.ok("POST", f"/passes/{pass_id}/adjust", {"status": "void", "reason": "Refunded"})
        status, payload = self.staff.post(f"/booking-players/{valid_day}/check-in", {"coverage": "membership", "pass_id": pass_id})
        self.assertEqual(status, 409)
        self.assertIn("no longer active", payload["error"])

    def test_membership_allows_unlimited_play_unless_the_plan_sets_a_daily_limit(self):
        alex = self.player_with("annual")
        for time in ("07:00", "09:30", "12:00", "14:30"):
            booking_player = self.booked_player(alex, self.tomorrow, time)
            self.staff.ok("POST", f"/booking-players/{booking_player}/check-in", {"coverage": "membership"})
        self.assertEqual(alex.ok("GET", "/me")["passes"][0]["uses"], 4)

        limited = self.staff.ok("POST", "/products", {"kind": "membership", "name": "Weekday plan", "valid_days": 30,
                                                      "daily_round_limit": 1})["product_id"]
        sam = self.signup("Sam Ortiz")
        self.staff.ok("POST", f"/players/{sam.me['player_id']}/passes", {"product_id": limited})
        first, second = (self.booked_player(sam, self.day(2), t) for t in ("08:00", "11:00"))
        self.staff.ok("POST", f"/booking-players/{first}/check-in", {"coverage": "membership"})
        status, payload = self.staff.post(f"/booking-players/{second}/check-in", {"coverage": "membership"})
        self.assertEqual(status, 409)
        self.assertIn("1 round(s) per day", payload["error"])

    def test_range_buckets_small_and_large(self):
        small, large = self.products["bucket-small"], self.products["bucket-large"]
        self.staff.ok("POST", "/range-buckets", {"product_id": small["id"]})
        alex = self.player_with("range-punch-10")
        range_pass = alex.ok("GET", "/me")["passes"][0]
        self.staff.ok("POST", "/range-buckets", {"product_id": large["id"], "quantity": 2,
                                                 "player_id": alex.me["player_id"], "pass_id": range_pass["id"]})
        self.assertEqual(alex.ok("GET", "/me")["passes"][0]["punches_remaining"], 8)

        member = self.player_with("annual", "Sam Ortiz")
        membership = member.ok("GET", "/me")["passes"][0]
        status, payload = self.staff.post("/range-buckets", {"product_id": small["id"], "player_id": member.me["player_id"],
                                                             "pass_id": membership["id"]})
        self.assertEqual(status, 409)
        self.assertIn("does not cover range balls", payload["error"])

        self.staff.ok("PUT", f"/products/{small['id']}", {"active": False})
        self.assertEqual(self.staff.post("/range-buckets", {"product_id": small["id"]})[0], 409)
        rows = self.sql("SELECT quantity, billing_status, description FROM golf_ledger WHERE kind = 'range_bucket' ORDER BY id")
        self.assertEqual([(r["quantity"], r["billing_status"]) for r in rows], [(1, "unbilled"), (2, "covered")])
        self.assertIn("70 balls", rows[1]["description"])

    def test_staff_adjustments_are_validated_and_logged(self):
        alex = self.player_with("punch-10")
        pass_id = alex.ok("GET", "/me")["passes"][0]["id"]
        self.assertEqual(self.staff.post(f"/passes/{pass_id}/adjust", {"punches_delta": 2})[0], 400)  # reason required
        status, payload = self.staff.post(f"/passes/{pass_id}/adjust", {"punches_delta": -11, "reason": "Typo"})
        self.assertEqual(status, 409)
        self.staff.ok("POST", f"/passes/{pass_id}/adjust", {"punches_delta": 3, "reason": "Rain check"})
        punch_pass = alex.ok("GET", "/me")["passes"][0]
        self.assertEqual((punch_pass["punches_remaining"], punch_pass["punches_total"]), (13, 13))
        self.assertIn("Rain check", alex.ok("GET", "/me")["history"][0]["description"])

    def test_guest_check_in_links_the_player_record(self):
        alex = self.signup("Alex Rivera")
        self.book(alex, guests=[{"name": "Sam Ortiz"}, {"name": "Lou"}])
        sam_id = self.staff.ok("POST", "/players", {"full_name": "Sam Ortiz"})["player_id"]
        self.issue(sam_id, "punch-10")
        guests = self.sheet_slot(self.staff, "09:00")["booking"]["players"][1:]
        status, payload = self.staff.post(f"/booking-players/{guests[0]['id']}/check-in", {"coverage": "punch_card"})
        self.assertEqual(status, 400)
        self.assertIn("Link this guest", payload["error"])
        self.staff.ok("POST", f"/booking-players/{guests[0]['id']}/check-in",
                      {"coverage": "punch_card", "link_player_id": sam_id})
        self.staff.ok("POST", f"/booking-players/{guests[1]['id']}/check-in",
                      {"coverage": "pay_at_counter", "create_player": True})
        profile = self.staff.ok("GET", f"/players/{sam_id}")
        self.assertEqual(profile["passes"][0]["punches_remaining"], 9)
        self.assertEqual(profile["upcoming"][0]["checked_in"], True)
        self.assertEqual(len(self.staff.ok("GET", "/players", query="q=lou")["players"]), 1)
        self.assertEqual(alex.post(f"/bookings/{self.sheet_slot(alex, '09:00')['booking']['id']}/leave")[0], 200)

    def test_catalog_is_staff_only_and_editable(self):
        alex = self.signup("Alex Rivera")
        self.assertEqual(alex.get("/products")[0], 403)
        self.assertEqual(alex.put("/settings", {"riding_cart_count": 0})[0], 403)
        product_id = self.staff.ok("POST", "/products", {"kind": "punch_card", "name": "5 Twilight rounds", "punches": 5,
                                                         "covers": "round", "valid_days": 90, "price_cents": 12500})["product_id"]
        self.staff.ok("PUT", f"/products/{product_id}", {"active": False})
        status, _ = self.staff.post(f"/players/{alex.me['player_id']}/passes", {"product_id": product_id})
        self.assertEqual(status, 409)
        self.assertEqual(self.staff.post("/products", {"kind": "green_fee", "name": "Another fee"})[0], 400)


class SecurityTests(GolfDatabaseTest):
    def test_writes_need_the_app_header_and_an_allowed_origin(self):
        self.assertEqual(Client(golf_header=False).post("/auth/login", {})[0], 403)
        self.assertEqual(Client(origin="https://evil.example").post("/auth/login", {})[0], 403)
        self.assertEqual(Client(origin=None).post("/auth/login", {"email": "x@example.com", "password": "nope"})[0], 401)
        self.assertEqual(Client(golf_header=False).get("/tee-sheet", query=f"date={self.tomorrow}")[0], 200)

    def test_migrations_rerun_cleanly(self):
        import migrate
        self.assertEqual(migrate.migrate(self.dsn, quiet=True), [])


if __name__ == "__main__":
    unittest.main()
