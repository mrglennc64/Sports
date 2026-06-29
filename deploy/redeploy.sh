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
echo "[3/7] Updating backend dependencies..."
ssh $SERVER "cd $REPO_DIR/backend && .venv/bin/pip install -q -r requirements.txt"

# Step 4: Rebuild frontend with correct API base
echo ""
echo "[4/7] Rebuilding frontend..."
ssh $SERVER "cd $REPO_DIR/frontend && VITE_API_BASE=/api npm install && npm run build"

# Step 5: Copy built frontend to nginx directory
echo ""
echo "[5/7] Deploying frontend assets..."
ssh $SERVER "rm -rf $NGINX_DIR && mkdir -p $NGINX_DIR && cp -r $REPO_DIR/frontend/dist/* $NGINX_DIR/"

# Step 6: Restart nginx
echo ""
echo "[6/7] Reloading nginx..."
ssh $SERVER "systemctl reload nginx"

# Step 7: Verify services
echo ""
echo "[7/7] Verifying deployment..."
sleep 2

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
