#!/bin/bash
# One-time setup inside the web container (CT 140). Safe to re-run.
set -Eeuo pipefail

main() {
local status=0
trap 'status=$?; bash /srv/brettsbox/deploy/golf-doctor.sh || true; exit "$status"' ERR
apt-get install -y -qq git nginx iproute2 util-linux >/dev/null
exec 9>/run/brettsbox-golf-deploy.lock
flock -x 9
if [ -d /srv/brettsbox/.git ]; then
  git -C /srv/brettsbox fetch -q --depth 1 origin main && git -C /srv/brettsbox reset -q --hard origin/main
else
  git clone -q --depth 1 https://github.com/Brett-D/brettsbox.com.git /srv/brettsbox
fi
flock -u 9
install -m 755 /srv/brettsbox/deploy/brettsbox-pull.sh /usr/local/bin/brettsbox-pull
install -m 644 /srv/brettsbox/deploy/brettsbox-pull.service /srv/brettsbox/deploy/brettsbox-pull.timer /etc/systemd/system/
bash /srv/brettsbox/deploy/nginx-apply.sh
systemctl daemon-reload
systemctl enable --now brettsbox-pull.timer
bash /srv/brettsbox/deploy/golf-setup.sh
echo "brettsbox.com setup done. Updates are pulled every 2 minutes."
}

# Parse the whole function before git reset can replace this script.
main "$@"
