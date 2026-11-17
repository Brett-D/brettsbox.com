#!/bin/sh
# Nightly dump of the golf database (custom format, restore with pg_restore). Run by
# golf-backup.service as root; keeps GOLF_BACKUP_DAYS days (default 30) in /var/backups/brettsbox-golf.
set -eu
: "${GOLF_DATABASE_URL:?GOLF_DATABASE_URL is not set}"
dir=${GOLF_BACKUP_DIR:-/var/backups/brettsbox-golf}
keep=${GOLF_BACKUP_DAYS:-30}
umask 077
mkdir -p "$dir"
file="$dir/golf-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --format=custom --no-owner --no-privileges --file="$file.partial" --dbname="$GOLF_DATABASE_URL"
mv "$file.partial" "$file"
find "$dir" -type f -name 'golf-*.dump' -mtime +"$keep" -delete
echo "Golf backup written to $file"
