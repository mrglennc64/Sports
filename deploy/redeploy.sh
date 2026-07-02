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
#
# HARDENED: `systemctl restart` can report the unit "active" while an ORPHANED
# uvicorn (started outside systemd) still holds :8077 — the new process fails to
# bind ([Errno 98] address already in use), systemd gives up, and the orphan keeps
# serving STALE code with the API still answering 200. So we don't trust is-active:
# we confirm the process that actually holds the port IS the service's MainPID, and
# evict any squatter before retrying.
echo ""
echo "[4/8] Restarting backend service (with bind verification)..."
ssh $SERVER 'bash -s' <<'REMOTE'
set -e
PORT=8077
SVC=strike-backend.service

restart() { systemctl reset-failed "$SVC" 2>/dev/null || true; systemctl restart "$SVC"; sleep 2; }
holder()  { ss -ltnp "sport = :$PORT" 2>/dev/null | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2; }

restart
if ! systemctl is-active --quiet "$SVC"; then
  echo "  service not active after restart — evicting whatever holds :$PORT"
  fuser -k "${PORT}/tcp" 2>/dev/null || true
  sleep 1
  restart
fi

MAINPID=$(systemctl show -p MainPID --value "$SVC")
HOLD=$(holder)
if [ -z "$HOLD" ]; then
  echo "  ERROR: nothing is listening on :$PORT after restart"
  journalctl -u "$SVC" -n 20 --no-pager; exit 1
fi
if [ "$HOLD" != "$MAINPID" ]; then
  # A squatter (not our new process) owns the port. Kill it and restart once more.
  echo "  :$PORT held by pid $HOLD, not service MainPID $MAINPID — evicting orphan"
  kill -9 "$HOLD" 2>/dev/null || true
  sleep 1
  restart
  MAINPID=$(systemctl show -p MainPID --value "$SVC")
  HOLD=$(holder)
  if [ "$HOLD" != "$MAINPID" ] || [ -z "$HOLD" ]; then
    echo "  ERROR: :$PORT still not owned by the service (holder=$HOLD, MainPID=$MAINPID)"
    journalctl -u "$SVC" -n 20 --no-pager; exit 1
  fi
fi
echo "  backend active on :$PORT (pid $MAINPID)"
REMOTE

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
