#!/bin/bash
# Golf tee sheet: PostgreSQL, the loopback API and daily backups. Run as root inside the web
# container; safe to re-run (setup.sh calls it).
#
#   GOLF_BOOTSTRAP_STAFF_EMAIL=pro@example.com bash /srv/brettsbox/deploy/golf-setup.sh
#
# The first run installs PostgreSQL on this container and creates a database, a login role with a
# random password, and /etc/brettsbox/golf.env (root:brettsbox-golf, mode 640, never in Git). To use
# a PostgreSQL server elsewhere instead, write that file with GOLF_DATABASE_URL before running this.
set -Eeuo pipefail

main() {
local status=0
trap 'status=$?; bash /srv/brettsbox/deploy/golf-doctor.sh || true; exit "$status"' ERR
REPO=/srv/brettsbox
APP_USER=brettsbox-golf
ENV_FILE=/etc/brettsbox/golf.env
DB_NAME=brettsbox_golf
DB_ROLE=brettsbox_golf
export DEBIAN_FRONTEND=noninteractive

apt-get install -y -qq python3 python3-venv postgresql-client openssl nginx iproute2 util-linux >/dev/null

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
    runuser -u postgres -- createdb --encoding=UTF8 --template=template0 -O "$DB_ROLE" "$DB_NAME"
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

install -m 755 "$REPO/deploy/golf-backup.sh" /usr/local/bin/brettsbox-golf-backup
install -d -m 700 /var/backups/brettsbox-golf
install -m 644 "$REPO/deploy/golf-api.service" "$REPO/deploy/golf-backup.service" "$REPO/deploy/golf-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable golf-api.service golf-backup.timer >/dev/null
systemctl start golf-backup.timer

bash "$REPO/deploy/golf-deploy.sh" --force
bash "$REPO/deploy/nginx-apply.sh"
if ! python3 "$REPO/deploy/golf-health.py" http://127.0.0.1/api/golf/app; then
  # A successful reload can still leave an old master serving the site's 404 page.
  systemctl restart nginx
  python3 "$REPO/deploy/golf-health.py" --wait 10 http://127.0.0.1/api/golf/app
fi
echo "Golf API answers through nginx at /api/golf/app."
}

main "$@"
