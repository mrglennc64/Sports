# MLB-Edge: European Odds Integration — Completion Summary

**Date:** 2026-06-23  
**Status:** ✅ CSV Importer Ready | 🏗️ Live Scrapers Scaffolded

---

## ✅ Phase 1: CSV Importer (COMPLETE)

### What's Done

1. **CsvOddsProvider class** (`backend/app/data/european_odds.py`)
   - Reads strikeout props from CSV files
   - Converts decimal odds (European format) to American automatically
   - Integrates seamlessly into existing odds.py provider interface

2. **Pipeline Integration** (`backend/app/data/odds.py`)
   - Updated `get_provider()` factory to support EU providers
   - Config now supports `ODDS_PROVIDER=csv` + `ODDS_CSV_PATH` env vars

3. **Configuration Updates** (`backend/app/config.py`)
   - Added `odds_csv_path` setting
   - Updated docstring to reflect all available providers

4. **Documentation** (`CSV_IMPORTER_README.md`)
   - Step-by-step guide to export Betano/bet365/Unibet lines
   - How to configure and test the backend
   - Troubleshooting tips

5. **Example CSV** (`mlb-edge/data/strikeout_lines_example.csv`)
   - Template showing correct format

### How to Use Tonight

1. Export today's strikeout props from Betano/bet365/Unibet as CSV
2. Set env vars:
   ```powershell
   $env:ODDS_PROVIDER = "csv"
   $env:ODDS_CSV_PATH = "c:\path\to\your\lines.csv"
   ```
3. Start backend: `python -m uvicorn app.main:app --reload`
4. Check frontend: http://localhost:5173
5. Your CSV lines will now show edges calculated against your model!

### Testing Tonight's Results

Once games finish:
- Check `mlb-edge/data/pitcher_gamelogs_2024_2026.csv` for actual K results
- Compare actual vs model predictions
- Validate that the model's fair odds beat (or lose to) the book's lines

---

## 🏗️ Phase 2: Live Scrapers (SCAFFOLDED)

### What's Ready

Three provider classes are defined and stubbed:

1. **BetanoProvider** (`backend/app/data/european_odds.py`)
   - Uses Playwright for dynamic rendering
   - Points to https://www.betano.pt/baseball/mlb/
   - Stub ready for HTML/DOM structure

2. **Bet365Provider** 
   - Async Playwright-based scraper
   - Points to https://www.bet365.com
   - Stub ready for page-loading logic

3. **UnibetProvider**
   - Two-stage: try BeautifulSoup first, fall back to Playwright
   - Points to https://www.unibet.com/betting/sports/filter!1/baseball/mlb
   - Graceful degradation built in

### What's Needed to Activate Live Scrapers

To make any live scraper work, we need:

1. **HTML snapshots** — Save the strikeout props page as HTML
   - Open Betano/bet365/Unibet strikeout page in browser
   - Right-click → Save Page As → `betano_strikeouts.html`
   - Send to me or paste the HTML

2. **DOM selectors** — Identify CSS/XPath for:
   - Pitcher name container
   - Line (e.g., "5.5")
   - Over odds
   - Under odds
   - Inspector tip: right-click element → Inspect → find class/id

3. **Or API endpoints** — If available via DevTools:
   - Open Network tab
   - Filter to "XHR" requests
   - Look for API calls to fetch odds
   - Example: `https://api.betano.pt/odds?sport=baseball&prop=strikeouts`

### Implementation Steps (After HTML is Provided)

```python
# Example: once we have the Betano HTML structure
def _scrape_with_playwright(self) -> list[PropLine]:
    async with self._playwright.chromium.launch(headless=True) as browser:
        page = await browser.new_page()
        await page.goto(self.BASE_URL + self.BASEBALL_PATH)
        await page.wait_for_selector(".strikeout-prop")  # NEED THIS SELECTOR
        
        props = []
        for row in await page.query_selector_all(".strikeout-prop"):
            pitcher = await row.query_selector(".pitcher-name").inner_text()
            line = float(await row.query_selector(".line").inner_text())
            over_decimal = float(await row.query_selector(".over-odds").inner_text())
            under_decimal = float(await row.query_selector(".under-odds").inner_text())
            
            props.append(PropLine(
                pitcher_name=pitcher,
                line=line,
                over_odds=decimal_to_american(over_decimal),
                under_odds=decimal_to_american(under_decimal),
                bookmaker="betano"
            ))
        return props
```

---

## 📋 Next Steps

### Tonight (High Priority)
1. **Test CSV importer** with real Betano/bet365/Unibet lines
2. **Validate model** against actual game results
3. **Confirm edge-flagger** works end-to-end

### Tomorrow (Medium Priority)
1. **Capture HTML** from one book's strikeout page
2. **Implement live scraper** for that book first
3. **Test scraper** against real site (rate-limit aware)
4. **Scale to other two books**

### Future (Nice-to-Have)
1. **Cron job** to auto-scrape daily + export to CSV
2. **Line-movement tracking** (capture opens and closes)
3. **Multi-region support** (Betano.pt, Betano.es, Betano.de, etc.)
4. **API auth** (for books that require login)

---

## 🔧 File Changes Summary

| File | Change |
|------|--------|
| `backend/app/data/european_odds.py` | Created (3 scrapers + CSV importer) |
| `backend/app/data/odds.py` | Added EU provider support in `get_provider()` |
| `backend/app/config.py` | Added `odds_csv_path` setting |
| `mlb-edge/CSV_IMPORTER_README.md` | Documentation for CSV usage |
| `mlb-edge/data/strikeout_lines_example.csv` | Example CSV format |

---

## 🎯 Architecture

```
┌─ Get CSV or Scrape from Book ──────┐
│  CsvOddsProvider                   │
│  OR BetanoProvider / Bet365 / etc. │
└──────────────────┬──────────────────┘
                   ↓
┌─ Standardize to PropLine ──────────┐
│ pitcher_name, line,                │
│ over_odds, under_odds (American)   │
└──────────────────┬──────────────────┘
                   ↓
┌─ De-vig & Compare ─────────────────┐
│ devig_two_way()                    │
│ edge = model_prob - fair_prob      │
└──────────────────┬──────────────────┘
                   ↓
┌─ Flag Edges & Display ─────────────┐
│ /v2/slate API → React frontend     │
│ Show: pitcher, line, edge, kelly   │
└────────────────────────────────────┘
```

---

## ✨ What This Enables

- **Tonight:** Manually import Betano/bet365/Unibet lines → validate against your model
- **Tomorrow:** Auto-scrape daily → no manual export
- **Scalable:** Add more books by adding new provider classes
- **Provider-agnostic:** Same pipeline works with any odds source

Good to go! 🚀
