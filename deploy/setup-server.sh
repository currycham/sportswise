#!/usr/bin/env bash
set -euo pipefail
BASE=/srv/sportswise
HERE="$(cd "$(dirname "$0")" && pwd)"
[[ $(id -u) == 0 ]] || { echo 'Run as root'; exit 1; }
id sportswise >/dev/null 2>&1 || useradd --system --home-dir "$BASE" --shell /usr/sbin/nologin sportswise
mkdir -p "$BASE/app" "$BASE/data" "$BASE/backup"
if [[ ! -x "$BASE/venv/bin/python" ]]; then python3 -m venv "$BASE/venv"; fi
chown -R sportswise:sportswise "$BASE"
chmod 750 "$BASE/data" "$BASE/backup"
install -m 644 "$HERE/sportswise.service" /etc/systemd/system/sportswise.service
install -m 755 "$HERE/sportswise-backup" /etc/cron.daily/sportswise-backup
systemctl daemon-reload
systemctl enable sportswise >/dev/null
# Install only this site's fragment. Validate and back up before adding the import.
install -m 644 "$HERE/sportswise.caddy" /etc/caddy/sportswise.caddy
cp /etc/caddy/Caddyfile "$BASE/backup/Caddyfile.before-sportswise"
if ! grep -q '^import sportswise.caddy' /etc/caddy/Caddyfile; then
  printf '\nimport sportswise.caddy\n' >> /etc/caddy/Caddyfile
fi
if ! caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
  cp "$BASE/backup/Caddyfile.before-sportswise" /etc/caddy/Caddyfile
  echo 'Caddy validation failed; import restored'; exit 1
fi
systemctl reload caddy
printf 'SportsWise service and proxy installed\n'
