#!/usr/bin/env bash
# Weekly grading report: grade accumulated lines.csv against actual results
# and publish to data/reports/ (served at GET /v2/report).
# Cron (Thursdays 04:00 UTC, before the weekly summary routine reads it):
#   0 4 * * 4 /opt/strike/deploy/report.sh >> /opt/strike/data/report-cron.log 2>&1
set -euo pipefail

APP=/opt/strike
set -a
. /etc/mlb-edge.env
set +a

mkdir -p "$APP/data/reports"
STAMP=$(date -u +%F)
OUT="$APP/data/reports/report-$STAMP.txt"

echo "[$(date -u +%FT%TZ)] weekly report run"
cd "$APP/backend"
# Grade with the same shrink the live engine applies (PROB_SHRINKAGE from
# /etc/mlb-edge.env), so the calibration table reflects production behavior.
.venv/bin/python -m app.report --lines "$APP/data/lines.csv" --shrink "${PROB_SHRINKAGE:-1.0}" > "$OUT"
cp "$OUT" "$APP/data/reports/report-latest.txt"
echo "wrote $OUT"
