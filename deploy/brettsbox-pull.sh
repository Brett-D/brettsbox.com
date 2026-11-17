#!/bin/bash
# Publishes whatever is on main: the site updates within a couple of minutes of a push.
set -Eeuo pipefail

main() {
local status=0
trap 'status=$?; bash /srv/brettsbox/deploy/golf-doctor.sh || true; exit "$status"' ERR
cd /srv/brettsbox
exec 9>/run/brettsbox-golf-deploy.lock
flock -x 9
git fetch -q --depth 1 origin main
git reset -q --hard origin/main
flock -u 9

# Golf API: deploy when golf/api differs from the last version that deployed successfully, so a
# failed run (pip or PostgreSQL briefly unavailable) is simply retried two minutes later.
[ -f /etc/brettsbox/golf.env ] || return 0
bash /srv/brettsbox/deploy/golf-deploy.sh
}

main "$@"
