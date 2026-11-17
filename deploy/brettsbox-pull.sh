#!/bin/sh
# Publishes whatever is on main: the site updates within a couple of minutes of a push.
set -e
cd /srv/brettsbox
git fetch -q --depth 1 origin main
git reset -q --hard origin/main

# Golf API: deploy when golf/api differs from the last version that deployed successfully, so a
# failed run (pip or PostgreSQL briefly unavailable) is simply retried two minutes later.
venv=/opt/brettsbox-golf/venv
state=/opt/brettsbox-golf/deployed
[ -f /etc/brettsbox/golf.env ] && [ -x "$venv/bin/python" ] || exit 0
want=$(git rev-parse HEAD:golf/api)
[ "$want" = "$(cat "$state" 2>/dev/null)" ] && exit 0
if ! sha256sum -c --status /opt/brettsbox-golf/requirements.sha256 2>/dev/null; then
  "$venv/bin/pip" install --disable-pip-version-check -q -r golf/api/requirements.txt
  sha256sum /srv/brettsbox/golf/api/requirements.txt >/opt/brettsbox-golf/requirements.sha256
fi
set -a
# shellcheck source=/dev/null
. /etc/brettsbox/golf.env
set +a
"$venv/bin/python" golf/api/migrate.py
systemctl restart golf-api.service
echo "$want" >"$state"
