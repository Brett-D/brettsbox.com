# Golf tee sheet

An installable web app (PWA) for a golf course, served at **https://brettsbox.com/golf/**. Players book tee
times for groups of one to four, join open groups, and choose rental clubs and pull carts per player. Course
staff run the counter: check players in against punch cards or memberships, rent carts and clubs, sell range
balls, manage the player database, and adjust course settings and the catalog. Payments are not taken in the app;
chargeable items are recorded as *unbilled* with a price snapshot so billing can be added later.

It works on phones, iPads in either orientation, and touchscreen PCs at the counter: every control is at least
48 px (52 px on touch screens), nothing depends on hover, and it has light and dark themes (the header's sun/moon
button: Match device, Light or Dark; the choice is saved on the device).

## How it fits together

```mermaid
flowchart LR
  browser["Phone, iPad or counter PC<br/>(installed PWA)"] -->|HTTPS| cf[Cloudflare Tunnel]
  cf --> nginx["nginx on 127.0.0.1:80"]
  nginx -->|"/golf/ (static files)"| files["public/golf/"]
  nginx -->|"/api/golf/*"| api["Python API<br/>gunicorn on 127.0.0.1:8787"]
  api --> pg[("PostgreSQL<br/>brettsbox_golf")]
  backup["golf-backup.timer<br/>pg_dump nightly"] --> pg
```

| Path | What it is |
|---|---|
| `public/golf/` | The app: `index.html`, `style.css`, `app.js` (plain JavaScript, no build step), `theme.js` (applies the saved theme before first paint), `sw.js` (offline app shell), `manifest.webmanifest`, `icons/` |
| `golf/api/app.py` | WSGI entry point: routes, sessions, CSRF checks, JSON in and out |
| `golf/api/service.py` | Everything that reads or writes the database; each write is one transaction |
| `golf/api/domain.py` | Pure rules (tee sheet slots, party sizes, pass and unit states) |
| `golf/api/security.py` | PBKDF2 password hashes, session tokens, one-time player codes |
| `golf/api/migrations/` | SQL migrations, applied in order by `migrate.py` |
| `golf/api/devserver.py` | Local preview of app and API on one origin |
| `golf/make_icons.py` | Redraws `public/golf/icons/` (needs Pillow) |
| `deploy/golf-*.{sh,service,timer}`, `nginx-apply.sh` | Server setup, deploys, diagnostics (`golf-doctor.sh`), the API service and nightly backups |
| `tests/test_golf_*.py` | Unit, PWA and PostgreSQL integration tests |

`site/build.py` leaves `public/golf/` alone, so rebuilding the blog never touches the app.

## Course rules (enforced by the database, not just the app)

- **One group per tee time, at most four players.** A unique constraint and a trigger that locks the group
  before counting, so simultaneous joins can't create a fifth player.
- **Rentals never double up.** Riding carts, pull carts and right- or left-handed club sets are numbered units.
  A rental holds a unit from the tee time for the *average round* (default 2 h 30 min); a trigger rejects any
  overlapping reservation of the same unit. Units that are out past their estimated return (*overdue*) are not
  handed to anyone else until staff mark them returned.
- **Bookings and their rentals are all or nothing.** If any player's clubs or pull cart, or the group's riding
  carts, can't be reserved, the whole booking is rolled back and the player is told what ran out.
- **Nobody is billed for what didn't happen.** Cancelling a reservation before it starts, or undoing a check-in,
  turns its ledger entry from *unbilled* into a plain history note. When a captain leaves, the group's riding carts
  and their charges move to the new captain.
- **Passes can't be overdrawn or used outside their dates.** A trigger checks a pass is active, inside its
  valid dates, covers what it's used for (rounds or range buckets), and has punches left before taking one;
  `punches_remaining` also has a `CHECK (>= 0)`. Memberships can have a rounds-per-day limit. Undoing a check-in
  gives the punch back.
- A player can't hold two tee times that overlap a round.

## Data model

```mermaid
erDiagram
  golf_players ||--o| golf_users : "signs in as"
  golf_players ||--o{ golf_booking_players : "plays in"
  golf_bookings ||--|{ golf_booking_players : has
  golf_bookings ||--o{ golf_rentals : "riding carts"
  golf_booking_players ||--o{ golf_rentals : "clubs, pull cart"
  golf_rental_units ||--o{ golf_rentals : "reserved as"
  golf_players ||--o{ golf_entitlements : holds
  golf_products ||--o{ golf_entitlements : "issued from"
  golf_entitlements ||--o{ golf_entitlement_uses : "used by"
  golf_players ||--o{ golf_ledger : history
```

- **Players** are the customer database. Every account has one; staff can also add players who never use the app.
  A staff-generated **player code** (8 characters, 14 days, single use) links a new app account to an existing
  player record and its passes, so nobody can claim someone else's punch card just by knowing their email.
- **Products** are the catalog: green fee, punch cards (rounds or range buckets), memberships (unlimited or
  limited rounds per day, optionally with range balls), small and large range buckets, and riding cart, pull cart
  and club rentals. Staff edit names, prices, punches, validity and bucket sizes, and turn products on or off.
- **Entitlements** are passes a player holds. Their terms are copied from the product when issued, so later
  catalog edits never change a pass someone already has.
- **Ledger** is each player's history (bookings, rentals, check-ins, passes, range balls, adjustments) with a
  price snapshot and a billing status: `none`, `unbilled` (chargeable, not yet settled) or `covered` (paid for by
  a membership or punch card).
- Course settings hold hours, tee interval, average round, booking window and the rental counts; changing a count
  adds or retires numbered units (it refuses to retire a unit that is out or reserved).

## Roles

- **Players** see the tee sheet (other golfers appear as "Brett D."), book and join groups, pick rental clubs and
  pull carts, manage riding carts for their group, and see their passes, tee times and history under *My golf*.
- **Course staff** also get *Counter* (unit status, mark returned, out of service, walk-in rentals, range balls),
  *Players* (search, profiles, passes, adjustments, player codes) and *Setup* (course settings and catalog), and can
  check players in, add players to groups and cancel tee times.

Signing up with `GOLF_BOOTSTRAP_STAFF_EMAIL` creates the first staff account, and only while there is no staff account yet:
sign up with it yourself straight after deploying (or leave it empty and promote your own account). Promote or
demote anyone on the server:

```bash
set -a; . /etc/brettsbox/golf.env; set +a
/opt/brettsbox-golf/venv/bin/python /opt/brettsbox-golf/api/manage_staff.py promote someone@example.com
```

## Deploying

On the web container (CT 140), as root. Update the checkout first, so bash runs the current `setup.sh`:

```bash
git -C /srv/brettsbox fetch -q --depth 1 origin main && git -C /srv/brettsbox reset -q --hard origin/main
GOLF_BOOTSTRAP_STAFF_EMAIL=you@example.com bash /srv/brettsbox/deploy/setup.sh
```

`setup.sh` sets up the static site as before, applies the nginx config (`deploy/nginx-apply.sh`), then runs
`deploy/golf-setup.sh`, which:

1. installs PostgreSQL, creates the `brettsbox_golf` database (UTF-8) and a login role with a random password, and
   writes `/etc/brettsbox/golf.env` (owner `root:brettsbox-golf`, mode 640; never in Git). To use a PostgreSQL
   server elsewhere, write that file with your own `GOLF_DATABASE_URL` first and the local install is skipped;
2. creates the `brettsbox-golf` system user and a virtualenv in `/opt/brettsbox-golf/venv`;
3. runs `deploy/golf-deploy.sh`: copies `golf/api` to `/opt/brettsbox-golf/api` (so the service never needs access
   to `/srv` and git updates never change files under running workers), installs requirements, applies
   migrations, installs `golf-api.service` (gunicorn on 127.0.0.1:8787 as `brettsbox-golf`) and
   `golf-backup.timer`, restarts the API and waits for it to answer;
4. applies the nginx config again and checks `/api/golf/app` through nginx.

It only reports success when the API answers both directly and through nginx; otherwise it prints diagnostics and
`setup.sh` fails. It is safe to re-run. nginx relays `/api/golf/*` to the API (with a sign-in rate limit per
visitor) and serves `/golf/` with `Cache-Control: no-cache` and a strict Content-Security-Policy.

`nginx-apply.sh` restarts nginx instead of reloading it while nginx still listens beyond loopback: a reload can't
move nginx from the original `listen 80` to the loopback-only listeners (it can't bind `127.0.0.1:80` while holding
`0.0.0.0:80`), and nginx then silently keeps its old config even though `systemctl reload` reports success.

After that, pushing to `main` is still all it takes: the pull timer updates the files, and whenever `golf/api/`
differs from the last version that deployed successfully it runs `golf-deploy.sh` (a failed attempt is retried on
the next run). If a push changes the nginx config, re-run `setup.sh`.

If something isn't working, run the read-only diagnostics. They check the service, its log, the API directly,
through this container's nginx and on the public site, the nginx config in use, and the Cloudflare tunnel, and end
with a verdict:

```bash
bash /srv/brettsbox/deploy/golf-doctor.sh
```
`/etc/brettsbox/golf.env` settings:

| Variable | Meaning |
|---|---|
| `GOLF_DATABASE_URL` | PostgreSQL connection string |
| `GOLF_ALLOWED_ORIGINS` | Origins allowed to make changes (default `https://brettsbox.com,https://www.brettsbox.com`) |
| `GOLF_COOKIE_SECURE` | `1` (default) marks the session cookie Secure; only turn off for local testing |
| `GOLF_BOOTSTRAP_STAFF_EMAIL` | Signing up with this email creates the first staff account (only while none exists) |
| `GOLF_BACKUP_DAYS` | Days of backups to keep (default 30) |

Useful commands:

```bash
systemctl status golf-api.service
journalctl -u golf-api.service -f
systemctl list-timers golf-backup.timer
```

## Backups and restore

`golf-backup.timer` runs `pg_dump` every night around 02:30 into `/var/backups/brettsbox-golf/` (root only,
custom format) and keeps 30 days. Run one now with `systemctl start golf-backup.service`. Copy the folder off the
container too (for example with the Proxmox backup job) and test a restore now and then:

```bash
systemctl stop golf-api.service
set -a; . /etc/brettsbox/golf.env; set +a
pg_restore --clean --if-exists --no-owner --dbname="$GOLF_DATABASE_URL" /var/backups/brettsbox-golf/golf-YYYYMMDDTHHMMSSZ.dump
systemctl start golf-api.service
```

## Security

- Passwords: PBKDF2-SHA256 (390,000 iterations), at least 10 characters. Unknown emails take as long as wrong
  passwords.
- Sessions: random tokens stored as SHA-256 hashes, 30 days, `HttpOnly; SameSite=Lax; Secure; Path=/api/golf`.
- Writes need the `X-Golf-Client` header (a cross-site form can't send it without a CORS preflight, which the API
  never grants) and, when the browser sends one, an `Origin` from `GOLF_ALLOWED_ORIGINS`.
- The API only listens on loopback and runs as its own unprivileged user. The app uses no inline script or
  style, so the CSP blocks injected code.

## Developing

```bash
# A throwaway PostgreSQL
docker run -d --name golf-pg -e POSTGRES_PASSWORD=golf -p 127.0.0.1:55432:5432 postgres:16

# Tests (the database tests are skipped without GOLF_TEST_DATABASE_URL)
pip install -r golf/api/requirements.txt
GOLF_TEST_DATABASE_URL=postgresql://postgres:golf@127.0.0.1:55432/postgres python -m unittest discover -s tests

# Preview app and API together on http://127.0.0.1:8000/golf/
GOLF_DATABASE_URL=postgresql://postgres:golf@127.0.0.1:55432/postgres python golf/api/migrate.py
GOLF_DATABASE_URL=postgresql://postgres:golf@127.0.0.1:55432/postgres GOLF_BOOTSTRAP_STAFF_EMAIL=you@example.com \
  python golf/api/devserver.py
```

When you change files in `public/golf/`, bump `VERSION` in `sw.js` so installed apps refresh their offline copy.
New database changes go in a new numbered file in `golf/api/migrations/`; never edit one that has been deployed.
