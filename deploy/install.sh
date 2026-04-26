#!/bin/bash
# Run once on the EC2 instance to install and enable both systemd services.
# Usage: bash deploy/install.sh

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY_DIR="$REPO_DIR/deploy"

echo "==> Installing Python deps for Flask backend..."
/home/ubuntu/miniconda/bin/pip install -r "$REPO_DIR/backend/requirements.txt" -q

echo "==> Installing Python deps for FastAPI backend..."
/home/ubuntu/miniconda/bin/pip install -r "$REPO_DIR/requirements.txt" -q

echo "==> Copying systemd service files..."
sudo cp "$DEPLOY_DIR/medpage-backend.service" /etc/systemd/system/
sudo cp "$DEPLOY_DIR/medpage-fastapi.service" /etc/systemd/system/

echo "==> Reloading systemd and enabling services..."
sudo systemctl daemon-reload
sudo systemctl enable medpage-backend medpage-fastapi
sudo systemctl restart medpage-backend medpage-fastapi

echo ""
echo "==> Status:"
sudo systemctl status medpage-backend --no-pager -l
sudo systemctl status medpage-fastapi --no-pager -l

echo ""
echo "Done. Both services will now start automatically on reboot."
echo ""
echo "Useful commands:"
echo "  sudo systemctl status medpage-backend"
echo "  sudo systemctl status medpage-fastapi"
echo "  sudo journalctl -u medpage-backend -f"
echo "  sudo journalctl -u medpage-fastapi -f"
echo "  sudo systemctl restart medpage-backend"
