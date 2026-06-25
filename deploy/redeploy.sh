#!/usr/bin/env bash
set -euo pipefail

# Redeploy script - updates code on strike.perfecthold.online
# Usage: ./deploy/redeploy.sh

SERVER="root@187.77.111.16"
REPO_DIR="/opt/strike"

echo "=============================================================================="
echo "Redeploying MLB Strikeout Edge to strike.perfecthold.online"
echo "=============================================================================="

# Step 1: Git pull latest code
echo ""
echo "[1/6] Pulling latest code from repository..."
ssh $SERVER "cd $REPO_DIR && git pull origin main"

# Step 2: Rebuild backend virtualenv (in case dependencies changed)
echo ""
echo "[2/6] Updating backend dependencies..."
ssh $SERVER "cd $REPO_DIR/backend && .venv/bin/pip install -q -r requirements.txt"

# Step 3: Rebuild frontend with correct API base
echo ""
echo "[3/6] Rebuilding frontend..."
ssh $SERVER "cd $REPO_DIR/frontend && VITE_API_BASE=/api npm install && npm run build"

# Step 4: Copy built frontend to nginx directory
echo ""
echo "[4/6] Deploying frontend assets..."
ssh $SERVER "rm -rf /var/www/strike && mkdir -p /var/www/strike && cp -r $REPO_DIR/frontend/dist/* /var/www/strike/"

# Step 5: Restart backend service
echo ""
echo "[5/6] Restarting backend service..."
ssh $SERVER "systemctl restart mlb-edge"

# Step 6: Verify services
echo ""
echo "[6/6] Verifying deployment..."
sleep 2

# Check if service is running
ssh $SERVER "systemctl is-active mlb-edge" || {
    echo "ERROR: Backend service failed to start!"
    echo "Check logs with: ssh $SERVER journalctl -u mlb-edge -n 50"
    exit 1
}

# Test API endpoint
echo ""
echo "Testing API endpoint..."
API_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "http://187.77.111.16/api/v2/slate")

if [ "$API_RESPONSE" = "200" ]; then
    echo "✓ API is responding (HTTP $API_RESPONSE)"
else
    echo "⚠ API returned HTTP $API_RESPONSE"
fi

echo ""
echo "=============================================================================="
echo "Deployment complete!"
echo "=============================================================================="
echo ""
echo "Site: https://strike.perfecthold.online/app"
echo "API:  https://strike.perfecthold.online/api/v2/slate"
echo ""
echo "To check logs:"
echo "  ssh $SERVER journalctl -u mlb-edge -f"
echo ""
echo "To verify correct pitchers:"
echo "  curl https://strike.perfecthold.online/api/v2/slate?date=2026-06-23 | jq '.rows[0:3] | .[].pitcher'"
echo ""
