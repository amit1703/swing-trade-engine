#!/bin/bash
# deploy.sh — Push updates to the live server
#
# Usage:
#   ./deploy.sh 65.21.100.42          # deploy latest code
#   ./deploy.sh 65.21.100.42 --env    # also re-copy .env (if credentials changed)
#
# Run this from your Mac after pushing to git.

set -e

SERVER_IP="${1:?Usage: ./deploy.sh SERVER_IP [--env]}"
UPDATE_ENV=false
[[ "$2" == "--env" ]] && UPDATE_ENV=true

APP_DIR="/opt/dashboard"
REPO_SUBDIR="swing-trading-dashboard"
BACKEND_DIR="$APP_DIR/$REPO_SUBDIR/backend"
FRONTEND_DIR="$APP_DIR/$REPO_SUBDIR/frontend"
ENV_FILE="$(dirname "$0")/backend/.env"

green()  { echo -e "\033[32m✓ $*\033[0m"; }
yellow() { echo -e "\033[33m→ $*\033[0m"; }

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   Swing Trading Dashboard — Deploy Update                ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "  Server : $SERVER_IP"
echo ""

# Optionally re-copy .env
if $UPDATE_ENV; then
  yellow "Updating .env on server…"
  scp "$ENV_FILE" root@"$SERVER_IP":"$BACKEND_DIR/.env"
  green ".env updated"
fi

yellow "Pulling latest code and restarting…"

ssh root@"$SERVER_IP" bash -s << REMOTE
set -e

cd $APP_DIR
git pull --quiet
echo "✓ Code updated"

# Rebuild frontend only if src files changed
cd $FRONTEND_DIR
npm install --silent
npm run build --silent
echo "✓ Frontend rebuilt"

# Restart backend
systemctl restart dashboard
sleep 2
systemctl is-active dashboard > /dev/null && echo "✓ Backend restarted" || echo "✗ Backend failed — check: journalctl -u dashboard -n 50"
REMOTE

echo ""
green "Deploy complete!"
echo "  Dashboard : http://$SERVER_IP"
echo ""
