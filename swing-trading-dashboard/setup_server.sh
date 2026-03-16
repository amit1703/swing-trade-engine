#!/bin/bash
# setup_server.sh — One-time VPS setup for Swing Trading Dashboard
#
# Run this from your Mac AFTER creating the VPS:
#   chmod +x setup_server.sh
#   ./setup_server.sh 65.21.100.42
#
# What it does:
#   1. Installs system dependencies (nginx, python, node)
#   2. Clones the repo
#   3. Sets up Python virtualenv + installs requirements
#   4. Copies your .env credentials securely (never goes to git)
#   5. Builds the React frontend
#   6. Creates systemd service (auto-restart on crash/reboot)
#   7. Configures nginx (serves frontend + proxies /api)
#   8. Opens firewall

set -e

# ── Config ────────────────────────────────────────────────────────────────────
SERVER_IP="${1:?Usage: ./setup_server.sh SERVER_IP}"
REPO="https://github.com/amit1703/swing-trade-engine.git"
APP_DIR="/opt/dashboard"
REPO_SUBDIR="swing-trading-dashboard"
BACKEND_DIR="$APP_DIR/$REPO_SUBDIR/backend"
FRONTEND_DIR="$APP_DIR/$REPO_SUBDIR/frontend"
ENV_FILE="$(dirname "$0")/backend/.env"   # your local .env

# ── Colour helpers ────────────────────────────────────────────────────────────
green()  { echo -e "\033[32m✓ $*\033[0m"; }
yellow() { echo -e "\033[33m→ $*\033[0m"; }
red()    { echo -e "\033[31m✗ $*\033[0m"; exit 1; }

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   Swing Trading Dashboard — Server Setup                 ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "  Server : $SERVER_IP"
echo "  Repo   : $REPO"
echo ""

# ── Preflight: check .env exists locally ─────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
  red ".env not found at $ENV_FILE — create it first (see .env.example)"
fi
green ".env found locally"

# ── Copy .env to server ───────────────────────────────────────────────────────
yellow "Copying .env to server…"
ssh root@"$SERVER_IP" "mkdir -p $BACKEND_DIR"
scp "$ENV_FILE" root@"$SERVER_IP":"$BACKEND_DIR/.env"
green ".env copied"

# ── Remote setup ──────────────────────────────────────────────────────────────
yellow "Running server setup (this takes ~3 minutes)…"

ssh root@"$SERVER_IP" bash -s << REMOTE
set -e

# ── 1. System packages ────────────────────────────────────────────────────────
echo "→ Installing system packages…"
apt-get update -qq
apt-get install -y -qq nginx git python3-pip python3-venv

# Node.js 20
if ! command -v node &> /dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null 2>&1
  apt-get install -y -qq nodejs
fi
echo "✓ System packages installed  (node $(node -v), python $(python3 --version))"

# ── 2. Clone / pull repo ──────────────────────────────────────────────────────
echo "→ Cloning repo…"
if [ -d "$APP_DIR/.git" ]; then
  cd $APP_DIR && git pull --quiet
  echo "✓ Repo updated"
else
  rm -rf $APP_DIR
  git clone --quiet $REPO $APP_DIR
  echo "✓ Repo cloned"
fi

# ── 3. Python virtualenv ──────────────────────────────────────────────────────
echo "→ Setting up Python environment…"
cd $BACKEND_DIR
python3 -m venv venv
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "✓ Python environment ready"

# ── 4. Build frontend ─────────────────────────────────────────────────────────
echo "→ Building frontend…"
cd $FRONTEND_DIR
npm install --silent
npm run build --silent
echo "✓ Frontend built (dist/ ready)"

# ── 5. systemd service ────────────────────────────────────────────────────────
echo "→ Creating systemd service…"
cat > /etc/systemd/system/dashboard.service << 'SERVICE'
[Unit]
Description=Swing Trading Dashboard Backend
After=network.target

[Service]
User=root
WorkingDirectory=BACKEND_DIR_PLACEHOLDER
Environment="PATH=BACKEND_DIR_PLACEHOLDER/venv/bin"
EnvironmentFile=BACKEND_DIR_PLACEHOLDER/.env
ExecStart=BACKEND_DIR_PLACEHOLDER/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

# Replace placeholder with actual path
sed -i "s|BACKEND_DIR_PLACEHOLDER|$BACKEND_DIR|g" /etc/systemd/system/dashboard.service

systemctl daemon-reload
systemctl enable dashboard
systemctl restart dashboard
sleep 2
systemctl is-active dashboard > /dev/null && echo "✓ Backend service running" || echo "✗ Backend service failed — check: journalctl -u dashboard -n 50"

# ── 6. nginx config ───────────────────────────────────────────────────────────
echo "→ Configuring nginx…"
cat > /etc/nginx/sites-available/dashboard << NGINX
server {
    listen 80;
    server_name _;

    # Serve React frontend (built static files)
    root $FRONTEND_DIR/dist;
    index index.html;

    # All /api/* → FastAPI backend
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        client_max_body_size 10m;
    }

    # React Router — all other routes serve index.html
    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
NGINX

# Enable site, disable default
ln -sf /etc/nginx/sites-available/dashboard /etc/nginx/sites-enabled/dashboard
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx
echo "✓ nginx configured"

# ── 7. Firewall ───────────────────────────────────────────────────────────────
echo "→ Configuring firewall…"
ufw --force reset > /dev/null 2>&1
ufw default deny incoming > /dev/null 2>&1
ufw default allow outgoing > /dev/null 2>&1
ufw allow ssh > /dev/null 2>&1
ufw allow 80/tcp > /dev/null 2>&1
ufw --force enable > /dev/null 2>&1
echo "✓ Firewall enabled (ssh + port 80 open)"

echo ""
echo "══════════════════════════════════════════════"
echo "  Setup complete!"
echo "══════════════════════════════════════════════"
REMOTE

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
green "Server setup complete!"
echo ""
echo "  Dashboard : http://$SERVER_IP"
echo "  Backend   : http://$SERVER_IP/api/regime"
echo ""
echo "  Check logs  : ssh root@$SERVER_IP 'journalctl -u dashboard -f'"
echo "  Restart app : ssh root@$SERVER_IP 'systemctl restart dashboard'"
echo ""
