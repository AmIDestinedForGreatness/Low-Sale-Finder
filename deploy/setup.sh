#!/bin/bash
# Yujin's Pokestop - Oracle VM first-time setup.
# Run once, after the repo has been copied to /home/ubuntu/low-sale-finder.
# Usage: bash deploy/setup.sh
set -euo pipefail

cd /home/ubuntu/low-sale-finder

echo "== apt update + base packages =="
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git curl unzip

echo "== python venv =="
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "== playwright chromium + its OS-level deps (needed for fb_feed.py) =="
python -m playwright install --with-deps chromium

echo "== logs dir for the systemd services below =="
mkdir -p logs

echo "== installing systemd services =="
sudo cp deploy/pokestop-feed.service /etc/systemd/system/
sudo cp deploy/pokestop-fb.service   /etc/systemd/system/
sudo cp deploy/pokestop-bot.service  /etc/systemd/system/
sudo cp deploy/pokestop-dash.service /etc/systemd/system/
sudo systemctl daemon-reload

echo "== opening dashboard port 5000 on this VM's own firewall (ufw), if active =="
if command -v ufw >/dev/null 2>&1; then
  sudo ufw allow 5000/tcp || true
fi

cat <<'EOF'

Setup done. Before starting anything:
  1. Confirm config.py is in place (copied separately, gitignored - not part of this script).
  2. Confirm ~/.claude/local-secrets/low-sale-finder.env.local exists with DISCORD_BOT_TOKEN=... (config.py reads it from there).
  3. Confirm fb_profile/ (the logged-in Facebook browser session) was copied over.
  4. In the Oracle Console: add an Ingress Rule for TCP port 5000 on the VCN's Security List (separate from this VM's own ufw - both must allow it).

Then start everything:
  sudo systemctl enable --now pokestop-feed pokestop-fb pokestop-bot pokestop-dash

Check status / logs:
  sudo systemctl status pokestop-feed
  tail -f logs/*.log
EOF
