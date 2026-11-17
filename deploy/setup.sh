#!/bin/bash
# One-time setup inside the web container (CT 140). Safe to re-run.
set -e
apt-get install -y -qq git nginx >/dev/null
if [ -d /srv/brettsbox/.git ]; then
  git -C /srv/brettsbox fetch -q --depth 1 origin main && git -C /srv/brettsbox reset -q --hard origin/main
else
  git clone -q --depth 1 https://github.com/Brett-D/brettsbox.com.git /srv/brettsbox
fi
install -m 755 /srv/brettsbox/deploy/brettsbox-pull.sh /usr/local/bin/brettsbox-pull
install -m 644 /srv/brettsbox/deploy/brettsbox-pull.service /srv/brettsbox/deploy/brettsbox-pull.timer /etc/systemd/system/
install -m 644 /srv/brettsbox/deploy/nginx-brettsbox.conf /etc/nginx/sites-available/brettsbox
ln -sf /etc/nginx/sites-available/brettsbox /etc/nginx/sites-enabled/brettsbox
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
systemctl daemon-reload
systemctl enable --now brettsbox-pull.timer
echo "brettsbox.com setup done. Updates are pulled every 2 minutes."

# The golf tee sheet (https://brettsbox.com/golf/) and its API. A failure here leaves the site running.
bash /srv/brettsbox/deploy/golf-setup.sh || echo "Golf setup did not finish; see golf/README.md." >&2
