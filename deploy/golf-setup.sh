#!/bin/bash
# Golf tee sheet: PostgreSQL, the loopback API and daily backups. Run as root inside the web
# container; safe to re-run (setup.sh calls it).
#
#   GOLF_BOOTSTRAP_STAFF_EMAIL=pro@example.com bash /srv/brettsbox/deploy/golf-setup.sh
#
# The first run installs PostgreSQL on this container and creates a database, a login role with a
# random password, and /etc/brettsbox/golf.env (root:brettsbox-golf, mode 640, never in Git). To use
# a PostgreSQL server elsewhere instead, write that file with GOLF_DATABASE_URL before running this.
set -euo pipefail

REPO=/srv/brettsbox
APP_USER=brettsbox-golf
APP_DIR=/opt/brettsbox-golf
VENV=$APP_DIR/venv
ENV_FILE=/etc/brettsbox/golf.env
DB_NAME=brettsbox_golf
DB_ROLE=brettsbox_golf
export DEBIAN_FRONTEND=noninteractive

apt-get install -y -qq python3 python3-venv postgresql-client openssl >/dev/null

if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin "$APP_USER"
fi
install -d -m 750 -o root -g "$APP_USER" /etc/brettsbox

if [ ! -f "$ENV_FILE" ]; then
  apt-get install -y -qq postgresql >/dev/null
  systemctl enable --now postgresql >/dev/null
  password=$(openssl rand -hex 24)
  # Fed on stdin so the password never shows up in a process list.
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_ROLE') THEN
    CREATE ROLE $DB_ROLE LOGIN PASSWORD '$password';
  ELSE
    ALTER ROLE $DB_ROLE WITH LOGIN PASSWORD '$password';
  END IF;
END
\$\$;
SQL
  if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1; then
    runuser -u postgres -- createdb -O "$DB_ROLE" "$DB_NAME"
  fi
  umask 027
  cat >"$ENV_FILE" <<ENV
# Golf API settings (read by golf-api.service and golf-backup.service). Not in Git.
GOLF_DATABASE_URL=postgresql://$DB_ROLE:$password@127.0.0.1:5432/$DB_NAME
GOLF_ALLOWED_ORIGINS=https://brettsbox.com,https://www.brettsbox.com
GOLF_COOKIE_SECURE=1
# Signing up with this email creates the first staff account (only while there is none yet).
GOLF_BOOTSTRAP_STAFF_EMAIL=${GOLF_BOOTSTRAP_STAFF_EMAIL:-}
ENV
  umask 022
  echo "Created $ENV_FILE and the $DB_NAME database."
fi
chown root:"$APP_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

# Python environment outside the checkout, so git resets never touch it.
install -d -m 755 "$APP_DIR"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --disable-pip-version-check -q -r "$REPO/golf/api/requirements.txt"
sha256sum "$REPO/golf/api/requirements.txt" >"$APP_DIR/requirements.sha256"

set -a
# shellcheck source=/dev/null
. "$ENV_FILE"
set +a
"$VENV/bin/python" "$REPO/golf/api/migrate.py"

install -m 755 "$REPO/deploy/golf-backup.sh" /usr/local/bin/brettsbox-golf-backup
install -d -m 700 /var/backups/brettsbox-golf
install -m 644 "$REPO/deploy/golf-api.service" "$REPO/deploy/golf-backup.service" "$REPO/deploy/golf-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable golf-api.service golf-backup.timer >/dev/null
systemctl restart golf-api.service
systemctl start golf-backup.timer

for _ in $(seq 1 15); do
  if "$VENV/bin/python" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/golf/app', timeout=2)" 2>/dev/null; then
    # The pull timer redeploys the API whenever golf/api differs from this.
    git -C "$REPO" rev-parse HEAD:golf/api >"$APP_DIR/deployed" 2>/dev/null || rm -f "$APP_DIR/deployed"
    echo "Golf API is up on 127.0.0.1:8787 (nginx relays https://brettsbox.com/api/golf/)."
    exit 0
  fi
  sleep 1
done
echo "Golf API did not answer; check: journalctl -u golf-api.service -n 50" >&2
exit 1
