# CSV Odds Importer: Quick Start

**Goal:** Use manually-exported Betano/bet365/Unibet strikeout lines with your model's edge-flagger, tonight.

## Step 1: Export Today's Strikeout Lines

From Betano, bet365, or Unibet, manually export today's strikeout props into a CSV file with this format:

```csv
pitcher_name,line,over_odds,under_odds,bookmaker
Sale,5.5,1.95,1.85,betano
Crochet,5.5,1.92,1.88,bet365
Skubal,5.5,1.90,1.90,unibet
```

**Important:** 
- `over_odds` and `under_odds` must be **DECIMAL odds** (European format, e.g., 1.95)
- Not American odds (e.g., -105)
- The system will auto-convert decimal → American for the downstream pipeline

**Example:** Betano shows "1.95" for Sale Over 5.5 → enter `1.95` in `over_odds`

---

## Step 2: Save the CSV

Save the file as (or similar):
```
mlb-edge/data/betano_strikeout_lines_2026-06-23.csv
```

---

## Step 3: Configure the Backend

Add this to `backend/.env`:

```env
ODDS_PROVIDER=csv
ODDS_CSV_PATH=../data/betano_strikeout_lines_2026-06-23.csv
```

Or set environment variables before running:

```powershell
$env:ODDS_PROVIDER = "csv"
$env:ODDS_CSV_PATH = "../data/betano_strikeout_lines_2026-06-23.csv"
python -m uvicorn app.main:app --reload
```

---

## Step 4: Test the Backend

```bash
curl http://localhost:8000/v2/slate
```

The response should show your CSV pitchers with edges calculated against your model's fair odds:

```json
{
  "date": "2026-06-23",
  "rows": [
    {
      "pitcher": "Sale",
      "opponent": "CLE",
      "line": 5.5,
      "side": "OVER",
      "model_prob": 0.803,
      "fair_prob": 0.512,
      "over_odds": -105,
      "edge": 0.291,
      "kelly": 0.032,
      "bet": true,
      "signal": "strong",
      "bookmaker": "betano"
    },
    ...
  ]
}
```

---

## Step 5: Check the Frontend

Open http://localhost:5173 and you should see your CSV data displayed with edge calculations.

---

## Troubleshooting

### "CSV file not found"
- Check the path: is `ODDS_CSV_PATH` absolute or relative?
- If relative, it's relative to the current working directory when you start the backend
- Tip: Use absolute path: `ODDS_CSV_PATH=/full/path/to/betano_lines_2026-06-23.csv`

### "Parse error" on a row
- Check that decimal odds are numbers (e.g., `1.95`, not `1.95%`)
- Check that `line` is a valid number (e.g., `5.5`, not `5.5+`)
- Check for leading/trailing spaces in pitcher names

### Wrong edge/kelly numbers
- Confirm your decimal odds are correct
- Reminder: 1.95 decimal = -105 American (roughly); the system converts automatically

---

## Next: Live Scrapers

Once you validate the CSV importer works with tonight's results, we'll implement live scrapers for Betano/bet365/Unibet so you don't need to export manually each day.

For that, we'll need:
1. **HTML snapshots or screenshots** of each book's strikeout props page
2. **DOM class/id selectors** (e.g., `class="pitcher-row"`) for the elements we need to extract
3. **Or API endpoints** if the books expose them (reverse-engineered from browser DevTools)
