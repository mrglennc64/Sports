#!/usr/bin/env bash
# Line-movement / CLV capture. Run TWICE a day to record each strikeout prop at
# "open" (early) and "close" (near first pitch), so we can measure line movement
# and closing-line value — the one price-based edge the research supports.
#   ARG: open | close   (defaults to close)
# Crons:
#   0 13 * * * /opt/strike/deploy/line_capture.sh open  >> /opt/strike/data/line_capture.log 2>&1
#   15 22 * * * /opt/strike/deploy/line_capture.sh close >> /opt/strike/data/line_capture.log 2>&1
set -euo pipefail
APP="${APP:-/opt/strike}"
TAG="${1:-close}"

set -a
# shellcheck disable=SC1091
[ -f /etc/mlb-edge.env ] && . /etc/mlb-edge.env
set +a

cd "$APP/backend"
exec .venv/bin/python -m app.data.line_capture "$TAG" --csv "$APP/data/line_history.csv"
