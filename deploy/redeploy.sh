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
ssh $SERVER "rm -rf /var/www/strike && mkdir -p /var/www/strike && cp -r $REPO_DIR/frontend/dist/* /var/www/strike/"

# Step 6: Restart backend service
echo ""
echo "[6/7] Restarting backend service..."
ssh $SERVER "systemctl restart mlb-edge"

# Step 7: Verify services
echo ""
echo "[7/7] Verifying deployment..."
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
