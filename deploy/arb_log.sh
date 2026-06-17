#!/usr/bin/env bash
# Arb frequency logger — snapshot /v2/arb and append any cross-book arbitrage
# opportunities to data/arb_log.csv, to learn HOW OFTEN and HOW BIG arbs appear
# (the question that decides whether arbing is a real, repeatable edge).
#
# QUOTA REALITY: a wide (us,us2,eu / ~12-book incl. Pinnacle) arb scan costs ~42
# the-odds-api requests. The free tier is 500/MONTH and the daily line snapshot
# already consumes most of it, so this is QUOTA-GUARDED: it SKIPS when remaining
# quota is below ARB_MIN_QUOTA, to avoid starving the snapshot/calibration data.
# A meaningful arb study (multiple scans/day) needs a PAID odds tier.
#
# Cron (once daily; the guard auto-pauses it once quota runs low):
#   0 21 * * * /opt/strike/deploy/arb_log.sh >> /opt/strike/data/arb_log.run.log 2>&1
set -euo pipefail
export APP="${APP:-/opt/strike}"
export MIN_QUOTA="${ARB_MIN_QUOTA:-120}"
API="${ARB_API:-https://strike.perfecthold.online/api/v2/arb?bankroll=1000&min_profit_pct=0}"
export CSV="$APP/data/arb_log.csv"
HEADER="ts,pitcher,line,profit_pct,guaranteed_profit,over_book,over_american,under_book,under_american,remaining_quota"

set -a
# shellcheck disable=SC1091
[ -f /etc/mlb-edge.env ] && . /etc/mlb-edge.env
set +a

export TS="$(date -u +%FT%TZ)"
KEY="${ODDS_API_KEY_THEODDSAPI:-}"
[ -f "$CSV" ] || echo "$HEADER" > "$CSV"

# Remaining quota via the FREE /sports endpoint (0 request cost).
export REMAIN="$(curl -s -m 20 -D - -o /dev/null \
  "https://api.the-odds-api.com/v4/sports?apiKey=$KEY" \
  | awk -F': ' 'tolower($1)=="x-requests-remaining"{gsub(/\r/,"",$2);print $2}')"
REMAIN="${REMAIN:-0}"

if [ -z "$REMAIN" ] || [ "$REMAIN" -lt "$MIN_QUOTA" ]; then
  echo "[$TS] arb_log SKIP: quota ${REMAIN:-?} < $MIN_QUOTA (preserving snapshot budget)"
  exit 0
fi

echo "[$TS] arb_log scan (quota $REMAIN)"
RESP="$(curl -s -m 60 "$API")"
printf '%s' "$RESP" | "$APP/backend/.venv/bin/python" -c "
import json, sys, os
ts=os.environ['TS']; rem=os.environ['REMAIN']; csv=os.environ['CSV']
try:
    d=json.load(sys.stdin)
except Exception as e:
    print(f'  parse error: {e}'); sys.exit(0)
rows=[]
for o in d.get('opportunities', []):
    legs={l['side']: l for l in o.get('legs', [])}
    ov=legs.get('over', {}); un=legs.get('under', {})
    rows.append(','.join(str(x) for x in [
        ts, o.get('pitcher',''), o.get('line',''),
        round(o.get('profit_pct',0)*100, 3), round(o.get('guaranteed_profit',0), 2),
        ov.get('bookmaker',''), ov.get('american',''),
        un.get('bookmaker',''), un.get('american',''), rem]))
with open(csv, 'a') as f:
    for r in rows: f.write(r + '\n')
print(f'  {len(rows)} arb(s) found, appended (scan saw count={d.get(\"count\",0)})')
"
