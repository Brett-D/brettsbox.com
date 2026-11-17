#!/bin/bash
# One-time setup inside the web container (CT 140). Safe to re-run.
# Everything runs from main(), which bash reads in full before starting: the git reset below
# replaces this very file, and bash must not pick up the new copy halfway through.
set -e

main() {
  apt-get install -y -qq git nginx iproute2 >/dev/null
  if [ -d /srv/brettsbox/.git ]; then
    git -C /srv/brettsbox fetch -q --depth 1 origin main && git -C /srv/brettsbox reset -q --hard origin/main
  else
    git clone -q --depth 1 https://github.com/Brett-D/brettsbox.com.git /srv/brettsbox
  fi
  install -m 755 /srv/brettsbox/deploy/brettsbox-pull.sh /usr/local/bin/brettsbox-pull
  install -m 644 /srv/brettsbox/deploy/brettsbox-pull.service /srv/brettsbox/deploy/brettsbox-pull.timer /etc/systemd/system/
  bash /srv/brettsbox/deploy/nginx-apply.sh
  systemctl daemon-reload
  systemctl enable --now brettsbox-pull.timer
  echo "brettsbox.com setup done. Updates are pulled every 2 minutes."

  # The golf tee sheet (https://brettsbox.com/golf/) and its API. Fails loudly, with diagnostics,
  # unless the API answers directly and through nginx.
  bash /srv/brettsbox/deploy/golf-setup.sh
}

main "$@"
exit
