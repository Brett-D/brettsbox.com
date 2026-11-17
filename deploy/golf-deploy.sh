#!/bin/bash
# Deploy the golf API from the checkout. Used by golf-setup.sh and by the pull timer whenever
# golf/api changes. Run as root.
#
# The code is copied to /opt/brettsbox-golf/api (swapped in at once), so git updates never change
# files under running workers and the service user never needs access to /srv. New requirements
# are installed, migrations applied, and the service restarted; the deploy only counts as done
# once the API answers on loopback. Otherwise it prints diagnostics and exits non-zero, and the
# pull timer retries on its next run.
set -euo pipefail

main() {
  local repo=${GOLF_REPO:-/srv/brettsbox}
  local app=/opt/brettsbox-golf
  local venv=$app/venv
  local env_file=/etc/brettsbox/golf.env

  # One deploy at a time (setup and the pull timer can overlap).
  exec 9>/run/brettsbox-golf-deploy.lock
  flock 9

  rm -rf "$app/api.new"
  cp -r "$repo/golf/api" "$app/api.new"
  rm -rf "$app/api.new/__pycache__"
  chmod -R u=rwX,go=rX "$app/api.new"

  local want have
  want=$(sha256sum <"$app/api.new/requirements.txt" | cut -d' ' -f1)
  have=$(cat "$app/requirements.sha256" 2>/dev/null || true)
  if [ "$want" != "$have" ]; then
    "$venv/bin/pip" install --disable-pip-version-check -q -r "$app/api.new/requirements.txt"
    echo "$want" >"$app/requirements.sha256"
  fi

  set -a
  # shellcheck source=/dev/null
  . "$env_file"
  set +a
  "$venv/bin/python" "$app/api.new/migrate.py"

  install -m 644 "$repo/deploy/golf-api.service" "$repo/deploy/golf-backup.service" "$repo/deploy/golf-backup.timer" /etc/systemd/system/
  systemctl daemon-reload
  rm -rf "$app/api.old"
  if [ -d "$app/api" ]; then mv "$app/api" "$app/api.old"; fi
  mv "$app/api.new" "$app/api"
  systemctl enable golf-api.service golf-backup.timer >/dev/null 2>&1
  systemctl restart golf-api.service
  systemctl start golf-backup.timer

  if ! "$venv/bin/python" "$repo/deploy/golf-check.py" http://127.0.0.1:8787/api/golf/app; then
    echo "The golf API did not start. Diagnostics:" >&2
    bash "$repo/deploy/golf-doctor.sh" >&2 || true
    exit 1
  fi
  git -C "$repo" rev-parse HEAD:golf/api >"$app/deployed" 2>/dev/null || rm -f "$app/deployed"
  echo "Golf API deployed and answering on 127.0.0.1:8787."
}

main "$@"
exit
