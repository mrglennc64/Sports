#!/usr/bin/env bash
# Daily strikeout prop-line snapshot.
#
# Appends the day's pitcher-strikeout lines to /opt/strike/data/lines.csv
# (idempotent per date) so the historical backtest (app.data.history) has a
# growing, real line record to grade the model against.
#
# Loads the odds-API key from /etc/mlb-edge.env exactly like the systemd
# service, then runs the snapshot CLI. Intended to run once a day via cron near
# first pitch — see the "Daily line snapshot" section of deploy/README.md.
set -euo pipefail
APP="${APP:-/opt/strike}"

# Load secrets (ODDS_API_KEY_THEODDSAPI, etc.) into the environment so pydantic
# settings pick them up — same source of truth as the running service.
set -a
# shellcheck disable=SC1091
[ -f /etc/mlb-edge.env ] && . /etc/mlb-edge.env
set +a

cd "$APP/backend"
echo "[$(date -u +%FT%TZ)] snapshot run"
exec .venv/bin/python -m app.data.snapshot "$@"
