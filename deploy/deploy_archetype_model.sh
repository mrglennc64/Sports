#!/usr/bin/env bash
set -euo pipefail

# Deploy Archetype Model - pushes archetype CSV files and tests predictor
# Usage: ./deploy/deploy_archetype_model.sh

SERVER="root@187.77.111.16"
REPO_DIR="/opt/strike"

echo "=============================================================================="
echo "Deploying Archetype Model to strike.perfecthold.online"
echo "=============================================================================="

# Step 1: Pull latest code
echo ""
echo "[1/5] Pulling latest code..."
ssh $SERVER "cd $REPO_DIR && git pull origin main"

# Step 2: Deploy archetype CSV files
echo ""
echo "[2/5] Copying archetype model data files..."
ssh $SERVER "mkdir -p $REPO_DIR/backend/data/exports"

# Copy the three required CSV files
scp data/exports/pitcher_archetypes.csv $SERVER:$REPO_DIR/backend/data/exports/
scp data/exports/batter_archetypes.csv $SERVER:$REPO_DIR/backend/data/exports/
scp data/exports/archetype_interaction_matrix.csv $SERVER:$REPO_DIR/backend/data/exports/

echo "✓ Copied 3 archetype CSV files"

# Step 3: Restart backend service
echo ""
echo "[3/5] Restarting mlb-edge service..."
ssh $SERVER "systemctl restart mlb-edge"
sleep 3

# Check if service started
ssh $SERVER "systemctl is-active mlb-edge" || {
    echo "ERROR: Service failed to start!"
    echo "Check logs with: ssh $SERVER journalctl -u mlb-edge -n 50"
    exit 1
}

echo "✓ Service restarted successfully"

# Step 4: Test archetype predictor on server
echo ""
echo "[4/5] Testing archetype predictor..."

# Run the predictor test script directly
TEST_OUTPUT=$(ssh $SERVER "cd $REPO_DIR/backend && .venv/bin/python -m app.models.archetype_predictor 2>&1" || echo "FAILED")

if echo "$TEST_OUTPUT" | grep -q "Loaded.*pitcher archetypes.*batter archetypes"; then
    echo "✓ Archetype predictor loaded successfully"
    echo "$TEST_OUTPUT" | grep "Loaded"
else
    echo "⚠ Archetype predictor test failed!"
    echo "$TEST_OUTPUT"
    exit 1
fi

# Step 5: Test API returns archetype data
echo ""
echo "[5/5] Testing API response..."

# Make a test API call and check for archetype fields
API_RESPONSE=$(curl -s "http://187.77.111.16/api/v2/slate?date=2026-06-23")

if echo "$API_RESPONSE" | jq -e '.rows[0].archetype_k_rate' > /dev/null 2>&1; then
    echo "✓ API returning archetype predictions"
    echo ""
    echo "Sample archetype data from API:"
    echo "$API_RESPONSE" | jq -r '.rows[0:2] | .[] | "\(.pitcher): archetype_k_rate=\(.archetype_k_rate // "N/A"), method=\(.archetype_method // "N/A")"'
elif echo "$API_RESPONSE" | jq -e '.rows' > /dev/null 2>&1; then
    echo "⚠ API responding but archetype fields not found"
    echo "Sample row keys:"
    echo "$API_RESPONSE" | jq '.rows[0] | keys' | head -20
else
    echo "⚠ API not returning expected format"
    echo "Response: ${API_RESPONSE:0:200}..."
fi

echo ""
echo "=============================================================================="
echo "Archetype Model Deployment Complete!"
echo "=============================================================================="
echo ""
echo "Next steps:"
echo "  1. Check logs: ssh $SERVER journalctl -u mlb-edge -f"
echo "  2. Test predictions: curl https://strike.perfecthold.online/api/v2/slate | jq '.rows[0]'"
echo "  3. Monitor archetype coverage in production data"
echo ""
