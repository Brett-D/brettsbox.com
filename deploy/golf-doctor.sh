#!/bin/bash
# Read-only diagnostics; deliberately do not print golf.env or database credentials.
set -uo pipefail

main() {
  local health=/srv/brettsbox/deploy/golf-health.py direct=0 nginx=0 public=0
  echo "=== Golf API service ==="
  systemctl --no-pager --full status golf-api.service || true
  journalctl --no-pager -u golf-api.service -n 50 || true
  echo "=== API directly ==="
  python3 "$health" http://127.0.0.1:8787/api/golf/app && direct=1
  echo "=== API through nginx ==="
  python3 "$health" http://127.0.0.1/api/golf/app && nginx=1
  echo "=== API on public site ==="
  python3 "$health" https://brettsbox.com/api/golf/app && public=1
  echo "=== nginx config on disk (a running master may still have the old config) ==="
  nginx -T 2>&1 || true
  echo "=== nginx listeners and recent errors ==="
  ss -ltnp '( sport = :80 or sport = :8787 )' || true
  journalctl --no-pager -u nginx -n 30 || true
  tail -n 30 /var/log/nginx/error.log 2>/dev/null || true
  echo "=== Cloudflare tunnel ==="
  systemctl --no-pager --full status cloudflared || true
  journalctl --no-pager -u cloudflared -n 30 || true
  echo "=== Verdict ==="
  if [ "$direct" != 1 ]; then
    echo "Golf API is down: check the service log, working directory and database."
  elif [ "$nginx" != 1 ]; then
    echo "API works directly but nginx is stale or misconfigured; re-run deploy/golf-setup.sh."
  elif [ "$public" != 1 ]; then
    echo "Local API and nginx work. The public site may be served by a different nginx; check that the Cloudflare tunnel points at CT 140."
  else
    echo "All good"
    return 0
  fi
  return 1
}

main "$@"
