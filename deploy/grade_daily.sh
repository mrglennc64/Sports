#!/usr/bin/env bash
# Daily grading: grade the most-recently-completed slate (yesterday, UTC) and
# append one summary row to data/grades_daily.csv so the calibration sample
# accumulates EVERY day instead of only on the weekly report.sh run.
#
# Idempotent per date: a date already present in grades_daily.csv is skipped.
# Cron (14:00 UTC daily, after the prior night's games are final):
#   0 14 * * * /opt/strike/deploy/grade_daily.sh >> /opt/strike/data/grade-daily.log 2>&1
set -euo pipefail

APP="${APP:-/opt/strike}"

# Load secrets (PROB_SHRINKAGE, ODDS_API_KEY_THEODDSAPI, ...) the same way the
# live service and the other deploy scripts do — single source of truth.
set -a
# shellcheck disable=SC1091
[ -f /etc/mlb-edge.env ] && . /etc/mlb-edge.env
set +a

CSV="$APP/data/grades_daily.csv"
HEADER="date,n_graded,record,roi_pct,mae,bias"

# Grade the most-recently-completed slate. DATE override allowed for backfills.
DAY="${DATE:-$(date -u -d 'yesterday' +%F)}"

echo "[$(date -u +%FT%TZ)] grade_daily run for $DAY"

# Header on first run.
if [ ! -f "$CSV" ]; then
  echo "$HEADER" > "$CSV"
fi

# Idempotent: skip if this date already has a row (match start-of-line "DAY,").
if grep -q "^$DAY," "$CSV"; then
  echo "  $DAY already graded — skipping"
  exit 0
fi

cd "$APP/backend"
REPORT="$(.venv/bin/python -m app.report \
  --start "$DAY" --end "$DAY" \
  --lines "$APP/data/lines.csv" \
  --shrink "${PROB_SHRINKAGE:-1.0}")"

# --- Parse the human report defensively (blank field on no match) ---

# "  games graded: 15   (with a line: 15)"
N_GRADED="$(printf '%s\n' "$REPORT" \
  | sed -n 's/^[[:space:]]*games graded:[[:space:]]*\([0-9]\+\).*/\1/p' | head -n1)"

# "  record 7-8   win% 46.7%   units -1.73   ROI -11.5%"
RECORD="$(printf '%s\n' "$REPORT" \
  | sed -n 's/^[[:space:]]*record[[:space:]]*\([0-9]\+-[0-9]\+\).*/\1/p' | head -n1)"

# ROI from the same +EV line, e.g. "ROI -11.5%" -> "-11.5"
ROI_PCT="$(printf '%s\n' "$REPORT" \
  | sed -n 's/.*ROI[[:space:]]*\([+-]\?[0-9.]\+\)%.*/\1/p' | head -n1)"

# "  MAE  1.42   RMSE 1.88   bias +0.10  (over-projecting)"
MAE="$(printf '%s\n' "$REPORT" \
  | sed -n 's/^[[:space:]]*MAE[[:space:]]*\([0-9.]\+\).*/\1/p' | head -n1)"
BIAS="$(printf '%s\n' "$REPORT" \
  | sed -n 's/.*bias[[:space:]]*\([+-]\?[0-9.]\+\).*/\1/p' | head -n1)"

# Append exactly one row. Missing fields land as blanks (no field => no harm).
echo "$DAY,$N_GRADED,$RECORD,$ROI_PCT,$MAE,$BIAS" >> "$CSV"
echo "  appended: $DAY,$N_GRADED,$RECORD,$ROI_PCT,$MAE,$BIAS"
