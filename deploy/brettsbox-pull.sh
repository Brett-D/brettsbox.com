#!/bin/sh
# Publishes whatever is on main: the site updates within a couple of minutes of a push.
set -e
cd /srv/brettsbox
git fetch -q --depth 1 origin main
git reset -q --hard origin/main

# Golf API: redeploy when golf/api differs from the last version that deployed successfully, so a
# failed run (pip or PostgreSQL briefly unavailable) is simply retried two minutes later.
[ -f /etc/brettsbox/golf.env ] && [ -x /opt/brettsbox-golf/venv/bin/python ] || exit 0
[ "$(git rev-parse HEAD:golf/api)" = "$(cat /opt/brettsbox-golf/deployed 2>/dev/null)" ] && exit 0
exec bash /srv/brettsbox/deploy/golf-deploy.sh
