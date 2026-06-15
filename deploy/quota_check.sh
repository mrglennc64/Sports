#!/usr/bin/env bash
# Daily the-odds-api quota watch.
#
# Checks the remaining monthly request count via the FREE /v4/sports endpoint
# (it costs 0 quota and returns the x-requests-remaining header), logs it, and
# when the count drops below QUOTA_WARN_THRESHOLD writes a loud WARNING plus a
# flag file (data/quota_low.flag) so it's easy to spot that the-odds-api is
# about to run dry — the cue to flip ODDS_PROVIDER to the oddsapiio spare.
#
# Loads the key from /etc/mlb-edge.env exactly like the systemd service. Intended
# to run once a day via cron, just before the snapshot — see deploy/README.md.
set -euo pipefail
APP="${APP:-/opt/strike}"
THRESHOLD="${QUOTA_WARN_THRESHOLD:-75}"
FLAG="$APP/data/quota_low.flag"

# Load secrets (ODDS_API_KEY_THEODDSAPI) into the environment.
set -a
# shellcheck disable=SC1091
[ -f /etc/mlb-edge.env ] && . /etc/mlb-edge.env
set +a

TS="$(date -u +%FT%TZ)"
KEY="${ODDS_API_KEY_THEODDSAPI:-}"
if [ -z "$KEY" ]; then
  echo "[$TS] quota-check ERROR: ODDS_API_KEY_THEODDSAPI not set"
  exit 1
fi

# -D - dumps response headers; body is discarded. /v4/sports does not bill quota.
HEADERS="$(curl -s -m 20 -D - -o /dev/null \
  "https://api.the-odds-api.com/v4/sports?apiKey=$KEY")"
REMAIN="$(printf '%s' "$HEADERS" | awk -F': ' 'tolower($1)=="x-requests-remaining"{gsub(/\r/,"",$2);print $2}')"
USED="$(printf '%s' "$HEADERS" | awk -F': ' 'tolower($1)=="x-requests-used"{gsub(/\r/,"",$2);print $2}')"

if [ -z "$REMAIN" ]; then
  echo "[$TS] quota-check ERROR: no x-requests-remaining header (key invalid or rate-limited?)"
  printf '%s' "$HEADERS" | head -1
  exit 1
fi

echo "[$TS] the-odds-api remaining=$REMAIN used=${USED:-?} (warn<$THRESHOLD)"
if [ "$REMAIN" -lt "$THRESHOLD" ]; then
  echo "[$TS] *** WARNING: the-odds-api quota LOW ($REMAIN left). Flip to the spare:"
  echo "        sed -i 's/^ODDS_PROVIDER=.*/ODDS_PROVIDER=oddsapiio/' /etc/mlb-edge.env && systemctl restart mlb-edge ***"
  echo "$TS remaining=$REMAIN" > "$FLAG"
else
  rm -f "$FLAG"
fi
