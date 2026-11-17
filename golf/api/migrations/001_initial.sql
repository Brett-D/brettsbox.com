-- Golf tee sheet: players, accounts, tee times, rentals, passes and the activity ledger.
-- Capacity and credit rules are enforced here as well as in the API, so no client or
-- concurrent request can overbook a tee time, double-rent a unit or overdraw a pass.

CREATE TABLE golf_settings (
    singleton boolean PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    course_name text NOT NULL DEFAULT 'Golf course' CHECK (length(btrim(course_name)) BETWEEN 1 AND 80),
    time_zone text NOT NULL DEFAULT 'America/Los_Angeles',
    opening_time time NOT NULL DEFAULT '07:00',
    closing_time time NOT NULL DEFAULT '17:00',
    tee_interval_minutes integer NOT NULL DEFAULT 10 CHECK (tee_interval_minutes BETWEEN 5 AND 60),
    average_round_minutes integer NOT NULL DEFAULT 150 CHECK (average_round_minutes BETWEEN 30 AND 720),
    booking_window_days integer NOT NULL DEFAULT 14 CHECK (booking_window_days BETWEEN 1 AND 365),
    riding_cart_count integer NOT NULL DEFAULT 20 CHECK (riding_cart_count BETWEEN 0 AND 200),
    pull_cart_count integer NOT NULL DEFAULT 10 CHECK (pull_cart_count BETWEEN 0 AND 200),
    club_sets_right integer NOT NULL DEFAULT 6 CHECK (club_sets_right BETWEEN 0 AND 200),
    club_sets_left integer NOT NULL DEFAULT 2 CHECK (club_sets_left BETWEEN 0 AND 200),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (opening_time < closing_time)
);

INSERT INTO golf_settings DEFAULT VALUES;

-- The player (customer) record. Accounts, tee times, rentals, passes and history all point here.
CREATE TABLE golf_players (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name text NOT NULL CHECK (length(btrim(full_name)) BETWEEN 1 AND 120),
    email text CHECK (email IS NULL OR length(email) <= 254),
    phone text CHECK (phone IS NULL OR length(phone) <= 40),
    notes text NOT NULL DEFAULT '' CHECK (length(notes) <= 2000),
    claim_code_hash text UNIQUE,
    claim_code_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX golf_players_name ON golf_players (lower(full_name));

CREATE TABLE golf_users (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email text NOT NULL UNIQUE CHECK (email = lower(email)),
    password_hash text NOT NULL,
    role text NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'staff')),
    player_id bigint NOT NULL UNIQUE REFERENCES golf_players (id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE golf_sessions (
    token_hash text PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES golf_users (id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX golf_sessions_user ON golf_sessions (user_id);

-- Catalog. Prices are bookkeeping metadata only: nothing here takes or records a payment.
CREATE TABLE golf_products (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9][a-z0-9-]{0,39}$'),
    kind text NOT NULL CHECK (kind IN ('green_fee', 'punch_card', 'membership', 'range_bucket',
                                       'riding_cart_rental', 'pull_cart_rental', 'club_rental')),
    name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
    active boolean NOT NULL DEFAULT TRUE,
    price_cents integer CHECK (price_cents IS NULL OR price_cents BETWEEN 0 AND 10000000),
    punches integer CHECK (punches IS NULL OR punches BETWEEN 1 AND 500),
    valid_days integer CHECK (valid_days IS NULL OR valid_days BETWEEN 1 AND 3660),
    covers text CHECK (covers IS NULL OR covers IN ('round', 'range')),
    includes_range boolean NOT NULL DEFAULT FALSE,
    daily_round_limit integer CHECK (daily_round_limit IS NULL OR daily_round_limit BETWEEN 1 AND 10),
    bucket_size text CHECK (bucket_size IS NULL OR bucket_size IN ('small', 'large')),
    balls integer CHECK (balls IS NULL OR balls BETWEEN 1 AND 1000),
    sort_order integer NOT NULL DEFAULT 0,
    CHECK (kind <> 'punch_card' OR (punches IS NOT NULL AND covers IS NOT NULL)),
    CHECK (kind <> 'membership' OR valid_days IS NOT NULL),
    CHECK (kind <> 'range_bucket' OR (bucket_size IS NOT NULL AND balls IS NOT NULL))
);

-- The fee and rental products are used by name in the API, so there is exactly one of each.
CREATE UNIQUE INDEX golf_products_system_kind ON golf_products (kind)
    WHERE kind IN ('green_fee', 'riding_cart_rental', 'pull_cart_rental', 'club_rental');

INSERT INTO golf_products (code, kind, name, punches, valid_days, covers, includes_range, bucket_size, balls, sort_order) VALUES
    ('green-fee', 'green_fee', 'Green fee', NULL, NULL, NULL, FALSE, NULL, NULL, 10),
    ('punch-10', 'punch_card', '10-round punch card', 10, 365, 'round', FALSE, NULL, NULL, 20),
    ('range-punch-10', 'punch_card', '10-bucket range card', 10, 365, 'range', FALSE, NULL, NULL, 30),
    ('annual', 'membership', 'Annual golf', NULL, 365, NULL, FALSE, NULL, NULL, 40),
    ('bucket-small', 'range_bucket', 'Small bucket', NULL, NULL, NULL, FALSE, 'small', 35, 50),
    ('bucket-large', 'range_bucket', 'Large bucket', NULL, NULL, NULL, FALSE, 'large', 70, 60),
    ('riding-cart', 'riding_cart_rental', 'Riding cart rental', NULL, NULL, NULL, FALSE, NULL, NULL, 70),
    ('pull-cart', 'pull_cart_rental', 'Pull cart rental', NULL, NULL, NULL, FALSE, NULL, NULL, 80),
    ('rental-clubs', 'club_rental', 'Rental clubs', NULL, NULL, NULL, FALSE, NULL, NULL, 90);

-- A punch card or membership owned by a player. Terms are copied from the product when it is
-- issued, so later catalog edits never change a pass someone already holds.
CREATE TABLE golf_entitlements (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id bigint NOT NULL REFERENCES golf_players (id),
    product_id integer NOT NULL REFERENCES golf_products (id),
    kind text NOT NULL CHECK (kind IN ('punch_card', 'membership')),
    name text NOT NULL,
    covers text NOT NULL CHECK (covers IN ('round', 'range', 'round_and_range')),
    punches_total integer CHECK (punches_total IS NULL OR punches_total >= 1),
    punches_remaining integer CHECK (punches_remaining IS NULL OR punches_remaining >= 0),
    daily_round_limit integer CHECK (daily_round_limit IS NULL OR daily_round_limit >= 1),
    valid_from date NOT NULL,
    valid_until date,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'void')),
    notes text NOT NULL DEFAULT '',
    issued_at timestamptz NOT NULL DEFAULT now(),
    issued_by_user_id bigint REFERENCES golf_users (id),
    CHECK ((kind = 'punch_card') = (punches_total IS NOT NULL AND punches_remaining IS NOT NULL)),
    CHECK (kind <> 'membership' OR valid_until IS NOT NULL),
    CHECK (valid_until IS NULL OR valid_until >= valid_from)
);

CREATE INDEX golf_entitlements_player ON golf_entitlements (player_id);

CREATE TABLE golf_entitlement_uses (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entitlement_id bigint NOT NULL REFERENCES golf_entitlements (id),
    used_for text NOT NULL CHECK (used_for IN ('round', 'range')),
    used_on date NOT NULL,
    punches integer NOT NULL DEFAULT 0 CHECK (punches >= 0),
    recorded_by_user_id bigint REFERENCES golf_users (id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX golf_entitlement_uses_entitlement ON golf_entitlement_uses (entitlement_id, used_on);

-- One group per tee time; the group holds at most four players.
CREATE TABLE golf_bookings (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tee_time timestamptz NOT NULL,
    captain_player_id bigint NOT NULL REFERENCES golf_players (id),
    created_by_user_id bigint REFERENCES golf_users (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT golf_bookings_one_per_tee UNIQUE (tee_time)
);

CREATE TABLE golf_booking_players (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    booking_id bigint NOT NULL REFERENCES golf_bookings (id) ON DELETE CASCADE,
    player_id bigint REFERENCES golf_players (id),
    guest_name text CHECK (guest_name IS NULL OR length(btrim(guest_name)) BETWEEN 1 AND 80),
    added_by_player_id bigint REFERENCES golf_players (id),
    clubs text NOT NULL DEFAULT 'none' CHECK (clubs IN ('none', 'right', 'left')),
    pull_cart boolean NOT NULL DEFAULT FALSE,
    checked_in_at timestamptz,
    coverage text CHECK (coverage IS NULL OR coverage IN ('membership', 'punch_card', 'pay_at_counter')),
    entitlement_use_id bigint REFERENCES golf_entitlement_uses (id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((player_id IS NULL) <> (guest_name IS NULL)),
    CHECK ((checked_in_at IS NULL) = (coverage IS NULL))
);

CREATE UNIQUE INDEX golf_booking_players_once ON golf_booking_players (booking_id, player_id)
    WHERE player_id IS NOT NULL;
CREATE INDEX golf_booking_players_player ON golf_booking_players (player_id);

CREATE FUNCTION golf_booking_players_capacity() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    taken integer;
BEGIN
    -- Lock the group so concurrent joins are counted one at a time.
    PERFORM 1 FROM golf_bookings WHERE id = NEW.booking_id FOR UPDATE;
    SELECT count(*) INTO taken FROM golf_booking_players WHERE booking_id = NEW.booking_id;
    IF taken >= 4 THEN
        RAISE EXCEPTION 'This tee time already has 4 players';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER golf_booking_players_capacity
    BEFORE INSERT OR UPDATE OF booking_id ON golf_booking_players
    FOR EACH ROW EXECUTE FUNCTION golf_booking_players_capacity();

-- Rentable inventory: riding carts, pull carts and right- or left-handed club sets.
-- active follows the counts in golf_settings; in_service is the staff "out of service" switch.
CREATE TABLE golf_rental_units (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('riding_cart', 'pull_cart', 'club_set')),
    hand text CHECK (hand IS NULL OR hand IN ('right', 'left')),
    number integer NOT NULL CHECK (number >= 1),
    label text NOT NULL,
    active boolean NOT NULL DEFAULT TRUE,
    in_service boolean NOT NULL DEFAULT TRUE,
    notes text NOT NULL DEFAULT '' CHECK (length(notes) <= 500),
    CHECK ((kind = 'club_set') = (hand IS NOT NULL))
);

CREATE UNIQUE INDEX golf_rental_units_number ON golf_rental_units (kind, (COALESCE(hand, '')), number);

CREATE FUNCTION golf_sync_unit_kind(p_kind text, p_hand text, p_count integer, p_prefix text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO golf_rental_units (kind, hand, number, label)
    SELECT p_kind, p_hand, n, p_prefix || lpad(n::text, greatest(2, length(n::text)), '0')
    FROM generate_series(1, p_count) AS n
    ON CONFLICT (kind, (COALESCE(hand, '')), number) DO NOTHING;

    UPDATE golf_rental_units
    SET active = (number <= p_count)
    WHERE kind = p_kind AND hand IS NOT DISTINCT FROM p_hand AND active IS DISTINCT FROM (number <= p_count);
END;
$$;

CREATE FUNCTION golf_sync_rental_units() RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    s golf_settings%ROWTYPE;
BEGIN
    SELECT * INTO s FROM golf_settings WHERE singleton;
    PERFORM golf_sync_unit_kind('riding_cart', NULL, s.riding_cart_count, 'Cart ');
    PERFORM golf_sync_unit_kind('pull_cart', NULL, s.pull_cart_count, 'Pull cart ');
    PERFORM golf_sync_unit_kind('club_set', 'right', s.club_sets_right, 'RH clubs ');
    PERFORM golf_sync_unit_kind('club_set', 'left', s.club_sets_left, 'LH clubs ');
END;
$$;

SELECT golf_sync_rental_units();

CREATE TABLE golf_rentals (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    unit_id integer NOT NULL REFERENCES golf_rental_units (id),
    booking_id bigint REFERENCES golf_bookings (id) ON DELETE CASCADE,
    booking_player_id bigint REFERENCES golf_booking_players (id) ON DELETE CASCADE,
    player_id bigint REFERENCES golf_players (id),
    holder_name text NOT NULL DEFAULT '',
    starts_at timestamptz NOT NULL,
    due_at timestamptz NOT NULL,
    returned_at timestamptz,
    created_by_user_id bigint REFERENCES golf_users (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (due_at > starts_at)
);

CREATE INDEX golf_rentals_open ON golf_rentals (unit_id, starts_at, due_at) WHERE returned_at IS NULL;
CREATE INDEX golf_rentals_booking ON golf_rentals (booking_id);
CREATE INDEX golf_rentals_player ON golf_rentals (player_id);

CREATE FUNCTION golf_rentals_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    unit golf_rental_units%ROWTYPE;
BEGIN
    IF NEW.returned_at IS NOT NULL THEN
        RETURN NEW;
    END IF;
    -- One allocation at a time: the API takes the same lock before it picks a free unit.
    PERFORM pg_advisory_xact_lock(4270001);
    SELECT * INTO unit FROM golf_rental_units WHERE id = NEW.unit_id;
    IF (TG_OP = 'INSERT' OR NEW.unit_id IS DISTINCT FROM OLD.unit_id) AND NOT (unit.active AND unit.in_service) THEN
        RAISE EXCEPTION '% is not available for rental', unit.label;
    END IF;
    IF EXISTS (
        SELECT 1 FROM golf_rentals r
        WHERE r.unit_id = NEW.unit_id
          AND r.id <> NEW.id
          AND r.returned_at IS NULL
          AND r.starts_at < NEW.due_at
          AND NEW.starts_at < r.due_at
    ) THEN
        RAISE EXCEPTION '% is already reserved for an overlapping time', unit.label;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER golf_rentals_guard
    BEFORE INSERT OR UPDATE OF unit_id, starts_at, due_at, returned_at ON golf_rentals
    FOR EACH ROW EXECUTE FUNCTION golf_rentals_guard();

-- Pass use: checks status, validity dates and coverage, and takes punches without going below zero.
CREATE FUNCTION golf_entitlement_use_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    pass golf_entitlements%ROWTYPE;
    rounds_today integer;
BEGIN
    SELECT * INTO pass FROM golf_entitlements WHERE id = NEW.entitlement_id FOR UPDATE;
    IF pass.status <> 'active' THEN
        RAISE EXCEPTION '% is no longer active', pass.name;
    END IF;
    IF NEW.used_on < pass.valid_from THEN
        RAISE EXCEPTION '% is not valid until %', pass.name, to_char(pass.valid_from, 'FMMon FMDD, YYYY');
    END IF;
    IF pass.valid_until IS NOT NULL AND NEW.used_on > pass.valid_until THEN
        RAISE EXCEPTION '% expired on %', pass.name, to_char(pass.valid_until, 'FMMon FMDD, YYYY');
    END IF;
    IF NEW.used_for = 'round' AND pass.covers NOT IN ('round', 'round_and_range') THEN
        RAISE EXCEPTION '% does not cover rounds of golf', pass.name;
    END IF;
    IF NEW.used_for = 'range' AND pass.covers NOT IN ('range', 'round_and_range') THEN
        RAISE EXCEPTION '% does not cover range balls', pass.name;
    END IF;

    IF pass.kind = 'punch_card' THEN
        NEW.punches := greatest(NEW.punches, 1);
        IF pass.punches_remaining < NEW.punches THEN
            RAISE EXCEPTION '% has % punch(es) left', pass.name, pass.punches_remaining;
        END IF;
        UPDATE golf_entitlements SET punches_remaining = punches_remaining - NEW.punches WHERE id = pass.id;
    ELSE
        NEW.punches := 0;
        IF NEW.used_for = 'round' AND pass.daily_round_limit IS NOT NULL THEN
            SELECT count(*) INTO rounds_today
            FROM golf_entitlement_uses
            WHERE entitlement_id = pass.id AND used_for = 'round' AND used_on = NEW.used_on;
            IF rounds_today >= pass.daily_round_limit THEN
                RAISE EXCEPTION '% allows % round(s) per day', pass.name, pass.daily_round_limit;
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER golf_entitlement_use_guard
    BEFORE INSERT ON golf_entitlement_uses
    FOR EACH ROW EXECUTE FUNCTION golf_entitlement_use_guard();

CREATE FUNCTION golf_entitlement_use_restore() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.punches > 0 THEN
        UPDATE golf_entitlements SET punches_remaining = punches_remaining + OLD.punches WHERE id = OLD.entitlement_id;
    END IF;
    RETURN OLD;
END;
$$;

CREATE TRIGGER golf_entitlement_use_restore
    AFTER DELETE ON golf_entitlement_uses
    FOR EACH ROW EXECUTE FUNCTION golf_entitlement_use_restore();

CREATE FUNCTION golf_entitlement_use_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Pass uses cannot be edited; undo the check-in and record it again';
END;
$$;

CREATE TRIGGER golf_entitlement_use_immutable
    BEFORE UPDATE ON golf_entitlement_uses
    FOR EACH ROW EXECUTE FUNCTION golf_entitlement_use_immutable();

-- Everything that happens to a player, with a price snapshot for future billing.
-- billing_status: none = not chargeable, unbilled = chargeable and not yet settled,
-- covered = paid for by a membership or punch card.
CREATE TABLE golf_ledger (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    player_id bigint REFERENCES golf_players (id),
    kind text NOT NULL,
    description text NOT NULL,
    product_id integer REFERENCES golf_products (id),
    quantity integer NOT NULL DEFAULT 1 CHECK (quantity >= 0),
    unit_price_cents integer,
    billing_status text NOT NULL DEFAULT 'none' CHECK (billing_status IN ('none', 'unbilled', 'covered')),
    booking_id bigint,
    booking_player_id bigint,
    rental_id bigint,
    entitlement_id bigint REFERENCES golf_entitlements (id),
    recorded_by_user_id bigint REFERENCES golf_users (id)
);

CREATE INDEX golf_ledger_player ON golf_ledger (player_id, occurred_at DESC);
CREATE INDEX golf_ledger_time ON golf_ledger (occurred_at DESC);
CREATE INDEX golf_ledger_rental ON golf_ledger (rental_id) WHERE rental_id IS NOT NULL;
