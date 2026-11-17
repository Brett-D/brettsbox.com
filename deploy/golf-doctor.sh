#!/bin/bash
# Golf tee sheet diagnostics: shows which part is broken. Read-only; safe to run any time as root.
#
#   bash /srv/brettsbox/deploy/golf-doctor.sh
set -uo pipefail

section() { printf '\n== %s\n' "$1"; }
code() { curl -s -o /dev/null -m 10 --noproxy '*' -w '%{http_code}' "$@" 2>/dev/null || echo "no answer"; }
cache_header() { curl -sI -m 10 --noproxy '*' "$@" 2>/dev/null | tr -d '\r' | grep -i '^cache-control:' || echo "(none)"; }

section "golf-api.service"
systemctl --no-pager --full status golf-api.service 2>&1 | head -n 15
section "golf-api.service log (last 40 lines)"
journalctl -u golf-api.service -n 40 --no-pager 2>&1 | tail -n 40
section "Listening on 127.0.0.1:8787"
ss -ltnp 2>/dev/null | grep -E ':8787\b' || echo "Nothing is listening on port 8787"
section "Service user can read the code"
if [ -d /opt/brettsbox-golf/api ]; then
  runuser -u brettsbox-golf -- test -r /opt/brettsbox-golf/api/app.py && echo "yes" || echo "NO: brettsbox-golf cannot read /opt/brettsbox-golf/api/app.py"
else
  echo "/opt/brettsbox-golf/api is missing: run deploy/golf-setup.sh"
fi

api_direct=$(code http://127.0.0.1:8787/api/golf/app)
api_nginx=$(code -H 'Host: brettsbox.com' http://127.0.0.1/api/golf/app)
api_public=$(code https://brettsbox.com/api/golf/app)
local_sw=$(cache_header -H 'Host: brettsbox.com' http://127.0.0.1/golf/sw.js)
public_sw=$(cache_header https://brettsbox.com/golf/sw.js)

section "HTTP checks (expect 200, 200, 200)"
echo "API directly (127.0.0.1:8787):        $api_direct"
echo "API through this nginx (127.0.0.1:80): $api_nginx"
echo "API on the public site:               $api_public"
echo "golf/sw.js caching here:    $local_sw"
echo "golf/sw.js caching publicly: $public_sw"

section "nginx configuration in use"
nginx -t 2>&1 | tail -n 2
nginx -T 2>/dev/null | grep -nE '^# configuration file|^[[:space:]]*(listen|server_name)[[:space:]]|location \^~ /(api/golf|golf)/' || echo "nginx -T failed"
echo "Listening on port 80:"
ss -Hltn 'sport = :80' 2>/dev/null | awk '{print "  " $4}'
stale_listener=no
if ss -Hltn 'sport = :80' 2>/dev/null | awk '{print $4}' | grep -qvE '^(127\.0\.0\.1|\[::1\]):80$'; then
  stale_listener=yes
fi
echo "Recent nginx errors:"
grep -E '\[(emerg|crit|alert)\]' /var/log/nginx/error.log 2>/dev/null | tail -n 4 | sed 's/^/  /' || true

section "Cloudflare tunnel"
if systemctl list-unit-files 2>/dev/null | grep -q '^cloudflared'; then
  systemctl is-active cloudflared 2>&1 | sed 's/^/cloudflared: /'
else
  echo "No cloudflared service in this container"
fi
for f in /etc/cloudflared/config.yml /etc/cloudflared/config.yaml /root/.cloudflared/config.yml; do
  [ -f "$f" ] && { echo "$f:"; grep -A8 -i '^ingress' "$f"; }
done

section "Verdict"
if [ "$api_direct" != 200 ]; then
  echo "The API itself is not answering: see the service status and log above."
elif [ "$api_nginx" != 200 ] && [ "$stale_listener" = yes ]; then
  echo "nginx is still running an old config: it listens beyond loopback, so reloads can't apply the new"
  echo "one (see \"Address already in use\" above). Fix: systemctl restart nginx"
elif [ "$api_nginx" != 200 ]; then
  echo "The API works, but this container's nginx does not relay /api/golf/. Re-run: bash /srv/brettsbox/deploy/setup.sh"
elif [ "$api_public" != 200 ]; then
  if echo "$public_sw" | grep -qi 'no-cache' ; then
    echo "This container serves the new config, but the public site still fails: check Cloudflare (caching rules, tunnel)."
  else
    echo "Everything works here, but the public site is served by a different nginx (the old config: golf/sw.js"
    echo "is cached for a week there). Point the Cloudflare tunnel at this container, or run setup.sh on the"
    echo "machine the tunnel uses."
  fi
else
  echo "All good: the golf API answers directly, through nginx and on https://brettsbox.com."
fi
