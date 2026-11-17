#!/bin/bash
# Install the site's nginx config and make sure nginx is really running it. Run as root; used by
# setup.sh and golf-setup.sh.
#
# `systemctl reload nginx` reports success even when nginx can't apply the new config. Moving from
# the original `listen 80` (0.0.0.0:80) to the loopback-only listeners is such a case: the running
# nginx still holds 0.0.0.0:80, binding 127.0.0.1:80 fails with "Address already in use", and it
# quietly keeps serving the old config. So restart whenever nginx listens beyond loopback.
set -euo pipefail

main() {
  local repo=${GOLF_REPO:-/srv/brettsbox}
  install -m 644 "$repo/deploy/nginx-brettsbox.conf" /etc/nginx/sites-available/brettsbox
  ln -sf /etc/nginx/sites-available/brettsbox /etc/nginx/sites-enabled/brettsbox
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  if ! systemctl is-active --quiet nginx; then
    systemctl start nginx
  elif ss -Hltn 'sport = :80' | awk '{print $4}' | grep -qvE '^(127\.0\.0\.1|\[::1\]):80$'; then
    echo "nginx is still listening beyond loopback (an older config); restarting it to apply the new one."
    systemctl restart nginx
  else
    systemctl reload nginx
  fi
}

main "$@"
exit
