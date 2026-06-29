#!/usr/bin/env bash
set -euo pipefail

# Redeploy script - updates code on strike.perfecthold.online
# Usage: ./deploy/redeploy.sh

SERVER="newvps"
REPO_DIR="/opt/strike"
NGINX_DIR="/var/www/strike"

echo "=============================================================================="
echo "Redeploying to strike.perfecthold.online"
echo "=============================================================================="

# Step 1: Git pull latest code
echo ""
echo "[1/7] Pulling latest code from repository..."
ssh $SERVER "cd $REPO_DIR && git pull origin main"

# Step 2: Deploy archetype model CSV files
echo ""
echo "[2/7] Deploying archetype model data..."
ssh $SERVER "mkdir -p $REPO_DIR/backend/data/exports"
scp data/exports/pitcher_archetypes.csv $SERVER:$REPO_DIR/backend/data/exports/
scp data/exports/batter_archetypes.csv $SERVER:$REPO_DIR/backend/data/exports/
scp data/exports/archetype_interaction_matrix.csv $SERVER:$REPO_DIR/backend/data/exports/

# Step 3: Rebuild backend virtualenv (in case dependencies changed)
echo ""
echo "[3/8] Updating backend dependencies..."
ssh $SERVER "cd $REPO_DIR/backend && .venv/bin/pip install -q -r requirements.txt"

# Step 4: Restart the FastAPI backend so new routes / code take effect.
# REQUIRED: nginx serves static frontend + proxies /api to this service. Without a
# restart, any new or changed backend route 404s (or runs stale code) until the
# next reboot. This is the step the old script omitted.
echo ""
echo "[4/8] Restarting backend service..."
ssh $SERVER "systemctl restart strike-backend.service"

# Step 5: Rebuild frontend with correct API base
echo ""
echo "[5/8] Rebuilding frontend..."
ssh $SERVER "cd $REPO_DIR/frontend && VITE_API_BASE=/api npm install && npm run build"

# Step 6: Copy built frontend to nginx directory
echo ""
echo "[6/8] Deploying frontend assets..."
ssh $SERVER "rm -rf $NGINX_DIR && mkdir -p $NGINX_DIR && cp -r $REPO_DIR/frontend/dist/* $NGINX_DIR/"

# Step 7: Reload nginx
echo ""
echo "[7/8] Reloading nginx..."
ssh $SERVER "nginx -t && systemctl reload nginx"

# Step 8: Verify services
echo ""
echo "[8/8] Verifying deployment..."
sleep 2

# Backend must be active (it serves every /api route)
ssh $SERVER "systemctl is-active strike-backend.service" || {
    echo "ERROR: strike-backend.service is not active!"
    echo "Check logs with: ssh $SERVER journalctl -u strike-backend.service -n 50"
    exit 1
}

# Check if nginx is running
ssh $SERVER "systemctl is-active nginx" || {
    echo "ERROR: Nginx failed to start!"
    echo "Check logs with: ssh $SERVER journalctl -u nginx -n 50"
    exit 1
}

# Test API endpoint
echo ""
echo "Testing frontend..."
API_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "https://strike.perfecthold.online/")

if [ "$API_RESPONSE" = "200" ]; then
    echo "✓ Frontend is responding (HTTP $API_RESPONSE)"
else
    echo "⚠ Frontend returned HTTP $API_RESPONSE (expected for HTTPS redirect)"
fi

echo ""
echo "=============================================================================="
echo "Deployment complete!"
echo "=============================================================================="
echo ""
echo "Frontend: https://strike.perfecthold.online"
echo "Nginx dir: $NGINX_DIR"
echo ""
echo "To check logs:"
echo "  ssh $SERVER journalctl -u nginx -f"
echo ""
echo "To verify files deployed:"
echo "  ssh $SERVER ls -la $NGINX_DIR/"
echo ""
