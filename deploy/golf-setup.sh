#!/bin/bash
# Golf tee sheet: PostgreSQL, the loopback API, nginx relay and nightly backups. Run as root inside
# the web container; safe to re-run (setup.sh calls it). It only succeeds once the API answers both
# directly and through nginx; otherwise it prints diagnostics (deploy/golf-doctor.sh) and fails.
#
#   GOLF_BOOTSTRAP_STAFF_EMAIL=pro@example.com bash /srv/brettsbox/deploy/golf-setup.sh
#
# The first run installs PostgreSQL on this container and creates a database, a login role with a
# random password, and /etc/brettsbox/golf.env (root:brettsbox-golf, mode 640, never in Git). To use
# a PostgreSQL server elsewhere instead, write that file with GOLF_DATABASE_URL before running this.
set -euo pipefail

main() {
  local repo=/srv/brettsbox
  local app_user=brettsbox-golf
  local app_dir=/opt/brettsbox-golf
  local venv=$app_dir/venv
  local env_file=/etc/brettsbox/golf.env
  local db_name=brettsbox_golf
  local db_role=brettsbox_golf
  export DEBIAN_FRONTEND=noninteractive
  # Containers often have LANG set to a locale that isn't installed; C.UTF-8 always exists.
  export LC_ALL=C.UTF-8 LANG=C.UTF-8

  apt-get install -y -qq python3 python3-venv postgresql-client openssl curl iproute2 >/dev/null

  if ! id "$app_user" >/dev/null 2>&1; then
    useradd --system --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin "$app_user"
  fi
  install -d -m 750 -o root -g "$app_user" /etc/brettsbox

  if [ ! -f "$env_file" ]; then
    apt-get install -y -qq postgresql >/dev/null
    systemctl enable --now postgresql >/dev/null 2>&1
    local password
    password=$(openssl rand -hex 24)
    # Fed on stdin so the password never shows up in a process list.
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$db_role') THEN
    CREATE ROLE $db_role LOGIN PASSWORD '$password';
  ELSE
    ALTER ROLE $db_role WITH LOGIN PASSWORD '$password';
  END IF;
END
\$\$;
SQL
    if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$db_name'" | grep -q 1; then
      # UTF8 even if the cluster was created under the C locale (which defaults to SQL_ASCII).
      runuser -u postgres -- createdb -O "$db_role" -E UTF8 -T template0 --locale=C.UTF-8 "$db_name"
    fi
    umask 027
    cat >"$env_file" <<ENV
# Golf API settings (read by golf-api.service and golf-backup.service). Not in Git.
GOLF_DATABASE_URL=postgresql://$db_role:$password@127.0.0.1:5432/$db_name
GOLF_ALLOWED_ORIGINS=https://brettsbox.com,https://www.brettsbox.com
GOLF_COOKIE_SECURE=1
# Signing up with this email creates the first staff account (only while there is none yet).
GOLF_BOOTSTRAP_STAFF_EMAIL=${GOLF_BOOTSTRAP_STAFF_EMAIL:-}
ENV
    umask 022
    echo "Created $env_file and the $db_name database."
  fi
  chown root:"$app_user" "$env_file"
  chmod 640 "$env_file"

  install -d -m 755 "$app_dir"
  [ -x "$venv/bin/python" ] || python3 -m venv "$venv"
  install -m 755 "$repo/deploy/golf-backup.sh" /usr/local/bin/brettsbox-golf-backup
  install -d -m 700 /var/backups/brettsbox-golf

  # Copy the code to /opt, install requirements, migrate, restart, and wait for it to answer.
  bash "$repo/deploy/golf-deploy.sh"

  # Now relay /api/golf/ through nginx (applied after the API is up) and prove it works end to end.
  bash "$repo/deploy/nginx-apply.sh"
  if ! "$venv/bin/python" "$repo/deploy/golf-check.py" http://127.0.0.1/api/golf/app --host brettsbox.com --timeout 15; then
    echo "nginx does not relay /api/golf/ yet; restarting nginx once and checking again." >&2
    systemctl restart nginx
    if ! "$venv/bin/python" "$repo/deploy/golf-check.py" http://127.0.0.1/api/golf/app --host brettsbox.com --timeout 15; then
      echo "nginx does not relay /api/golf/ to the API. Diagnostics:" >&2
      bash "$repo/deploy/golf-doctor.sh" >&2 || true
      exit 1
    fi
  fi
  echo "Golf tee sheet is up: API on 127.0.0.1:8787, relayed by nginx at /api/golf/."
  echo "Check the public site with: bash $repo/deploy/golf-doctor.sh"
}

main "$@"
exit
