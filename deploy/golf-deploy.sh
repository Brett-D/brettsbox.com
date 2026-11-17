#!/bin/bash
# Shared by initial setup and the pull timer. Mark deployed only after a healthy restart.
set -Eeuo pipefail

main() {
  local repo=/srv/brettsbox app_dir=/opt/brettsbox-golf want status=0
  trap 'status=$?; bash /srv/brettsbox/deploy/golf-doctor.sh || true; exit "$status"' ERR
  install -d -m 755 "$app_dir"
  exec 9>/run/lock/brettsbox-golf-deploy.lock
  flock -x 9
  want=$(git -C "$repo" rev-parse HEAD:golf/api)
  if [ "${1:-}" != --force ] && [ -d "$app_dir/api" ] && \
      [ "$want" = "$(cat "$app_dir/deployed" 2>/dev/null)" ]; then
    return 0
  fi
  rm -f "$app_dir/deployed"
  [ -x "$app_dir/venv/bin/python" ] || python3 -m venv "$app_dir/venv"
  if ! sha256sum -c --status "$app_dir/requirements.sha256" 2>/dev/null; then
    "$app_dir/venv/bin/pip" install --disable-pip-version-check -q -r "$repo/golf/api/requirements.txt"
    sha256sum "$repo/golf/api/requirements.txt" >"$app_dir/requirements.sha256"
  fi
  systemctl stop golf-api.service
  rm -rf "$app_dir/api"
  cp -R "$repo/golf/api" "$app_dir/api"
  chown -R root:root "$app_dir/api"
  chmod -R u=rwX,go=rX "$app_dir/api"
  set -a
  # shellcheck source=/dev/null
  . /etc/brettsbox/golf.env
  set +a
  "$app_dir/venv/bin/python" "$app_dir/api/migrate.py"
  install -m 644 "$repo/deploy/golf-api.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl restart golf-api.service
  python3 "$repo/deploy/golf-health.py" --wait 45 http://127.0.0.1:8787/api/golf/app
  printf '%s\n' "$want" >"$app_dir/deployed"
  echo "Golf API is up on 127.0.0.1:8787."
}

main "$@"
