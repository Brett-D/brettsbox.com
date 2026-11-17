#!/bin/bash
# A reload cannot replace a wildcard listener with an overlapping loopback listener.
set -Eeuo pipefail

main() {
  local repo=${GOLF_REPO:-/srv/brettsbox} listeners action=reload status=0
  trap 'status=$?; bash /srv/brettsbox/deploy/golf-doctor.sh || true; exit "$status"' ERR
  install -m 644 "$repo/deploy/nginx-brettsbox.conf" /etc/nginx/sites-available/brettsbox
  ln -sf /etc/nginx/sites-available/brettsbox /etc/nginx/sites-enabled/brettsbox
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  listeners=$(ss -H -ltn 'sport = :80')
  if ! systemctl is-active --quiet nginx || \
      awk '$4 !~ /^(127\.[0-9.]+|\[::1\]|::1):80$/ { found=1 } END { exit !found }' <<<"$listeners"; then
    action=restart
  fi
  systemctl "$action" nginx
}

main "$@"; exit
