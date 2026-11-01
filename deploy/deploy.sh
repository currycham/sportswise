#!/usr/bin/env bash
# DEPLOY_HOST=ubuntu@<server> DEPLOY_KEY=~/.ssh/waywise_ed25519 bash deploy/deploy.sh [--setup]
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="${DEPLOY_HOST:?Set DEPLOY_HOST}"
KEY="${DEPLOY_KEY:-$HOME/.ssh/waywise_ed25519}"
SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o ServerAliveInterval=30 "$HOST")
export RSYNC_RSH="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"
"${SSH[@]}" 'sudo mkdir -p /srv/sportswise/app'
rsync -az --delete --rsync-path='sudo rsync' --include '.env.example' --exclude '.env' --exclude '.env.*' --exclude '.git/' --exclude '.venv/' \
  --exclude 'data/' --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude 'docs/screenshots/' \
  --exclude '.DS_Store' ./ "$HOST:/srv/sportswise/app/"
if [[ "${1:-}" == --setup ]]; then
  "${SSH[@]}" 'sudo bash /srv/sportswise/app/deploy/setup-server.sh'
fi
"${SSH[@]}" 'sudo test -f /srv/sportswise/app/.env && sudo chown -R sportswise:sportswise /srv/sportswise/app /srv/sportswise/data && sudo chmod 600 /srv/sportswise/app/.env'
"${SSH[@]}" 'sudo -u sportswise -H /srv/sportswise/venv/bin/pip install -q --disable-pip-version-check --timeout 20 --retries 1 --index-url https://mirrors.cloud.tencent.com/pypi/simple -r /srv/sportswise/app/requirements.txt'
"${SSH[@]}" 'sudo systemctl restart sportswise'
"${SSH[@]}" 'for n in $(seq 1 20); do curl -fsS http://127.0.0.1:8500/api/health && exit 0; sleep 1; done; exit 1'
printf '\nSportsWise deployed\n'
