#!/bin/sh
# Publishes whatever is on main: the site updates within a couple of minutes of a push.
set -e
cd /srv/brettsbox
git fetch -q --depth 1 origin main
git reset -q --hard origin/main