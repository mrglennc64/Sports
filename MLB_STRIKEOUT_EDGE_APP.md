# MLB Strikeout Edge — App Documentation

*Baseball vertical only. The same backend also serves crypto / economics / earnings / AI-release
prediction verticals (Polymarket-based); those are intentionally **out of scope** for this document.*

Live site: **strike.perfecthold.online** · Repo: `github.com/mrglennc64/strike.git`

---

## 1. What it is

A quantitative **pricing engine for pitcher-strikeout over/under props**. For each day's probable
starting pitchers it estimates how many strikeouts the pitcher will record, converts that estimate
into over/under probabilities, compares those against the **vig-removed** sportsbook line, and
surfaces the bets where the model thinks the book is mispriced — sized with fractional Kelly and
translated into a plain verdict (**Strong Play / Lean / No Bet**).

> ⚠️ **It is an analytics tool, not betting advice.** It surfaces and logs signals; it does not
> place bets. An "edge" is treated as a *hypothesis* until it is validated by logged closing-line
> value (CLV). Most model-vs-market disagreements are model error, not market error.

It is built as a FastAPI backend + a React (Vite) dashboard with a **Simple** (consumer) mode and a
**Pro** (full-table) mode.

---

## 2. What it does, end to end

```
MLB Stats API ─┐
the-odds-api ──┤→  assemble inputs → ensemble projection (expected Ks)
park / umpire ─┤                       → Poisson → over/under probability
weather/etc.  ─┘                       → de-vig book odds → edge → Kelly stake
                                       → verdict + reasons (insight layer)
                                       → ranked slate + diversified bet card + CSV log
                                       → proof layer: backtest · calibration · CLV
```

1. **Pull the day's probable starters** from the free MLB Stats API (pitcher, opponent, venue).
2. **Assemble inputs** for each starter — recent form, opponent K profile, expected innings,
   lineup, umpire, pitch mix, park, weather, catcher framing, bullpen leash.
3. **Project expected strikeouts (λ)** via a weighted **ensemble** of independent estimates.
4. **Convert λ to probabilities** with a Poisson model: P(over the line), P(under the line).
5. **De-vig the book odds** (remove the bookmaker margin) to get the market's *true* probability.
6. **Measure edge** = model probability − de-vigged market probability, on the better side.
7. **Size the stake** with fractional, capped Kelly.
8. **Translate to a verdict** (Strong Play / Lean / No Bet) with plain-English reasons.
9. **Rank the slate** and select a small **bet card** (the "bet these N, not all 20" view).
10. **Log every evaluated prediction** to `data/predictions.csv` — the seed for the proof layer.
11. **Prove it** with backtest (ROI), calibration (honest probabilities?), and CLV (beat the close?).

---

## 3. How it works (the model)

### 3.1 Data inputs (`backend/app/data/`)
| Source | Used for |
|---|---|
| **MLB Stats API** (free) | probable starters, opponent, venue, lineups, recent game logs, umpire assignment |
| **the-odds-api.com** | strikeout prop lines + American odds (US books; wide `us,us2,eu` pull for arb/CLV/sharp-check) |
| **Park factors** (`park.py`) | venue strikeout boost/suppression multiplier |
| **Umpire table** (`data/umpires.json`) | home-plate ump K-tendency (assignment from MLB; tendency from a lookup like Umpire Scorecards) |
| **Baseball Savant** (optional) | whiff / CSW / pitch-mix inputs |

Pitcher and prop names are fuzzy-matched (`names.py`) so the MLB feed and the odds feed line up.

### 3.2 The projection engine — two models

**v1 "multiplier" model** (`model/expected_ks.py`, served at `/predict`, `/slate`):
```
λ = (K/9 ÷ 9) × IP_per_start × M_opp × M_park × M_form
```
Each multiplier is normalised around 1.0 so the season-rate baseline is only *adjusted*. Includes a
**spot-starter guard** (relief innings inflate season K/9 and IP/GS, so innings-per-start is clamped
and low-sample pitchers are flagged `low_confidence` and never marked a bet).

**v2 "ensemble" model** (`model/projection.py`, served at `/v2/predict`, `/v2/slate` — the default,
`EXPECTED_KS_MODEL=ensemble`): each factor produces its *own* independent strikeout estimate; the
final λ is the weighted blend. Every component is returned so a bettor sees what each lens says.

| # | Factor | Default weight | What it estimates |
|---|---|---|---|
| 1 | Opponent K profile | 0.26 | batters faced × pitcher-vs-opponent matchup K% (**log5** odds-ratio, not a naive average) |
| 2 | Pitcher recent form | 0.22 | mean Ks over recent starts (falls back to K/9) |
| 3 | Expected innings | 0.18 | the volume anchor: BF × matchup rate |
| 4 | Lineup strength | 0.09 | matchup vs tonight's actual lineup (high-K bats resting?) |
| 5 | Umpire | 0.05 | matchup × ump K factor |
| 6 | Pitch count | 0.04 | manager-hook-trimmed innings × matchup rate |
| 7 | Pitch mix | 0.04 | matchup × usage-weighted whiff factor |
| 8 | Bullpen leash | 0.04 | volume cap (opener / short leash) the book is slow to price |
| 9 | Weather | 0.04 | small K nudge (domes neutral) |
| 10 | Catcher framing | 0.04 | nudge for stolen/lost called strikes |

Weights live in `model/weights.py` and must sum to 1.0. Factors 8–10 (and umpire/mix) default to a
neutral 1.0 when their data is missing, so the projection **degrades gracefully**. The **log5**
matchup method is important: averaging regressed strikeout pitchers toward the lineup rate and made
nearly every line look like an under; log5 keeps an elite arm elite vs an average lineup.

Two flag-gated extensions exist and are **off by default**: a **type-matchup synthesis** (regress a
pitcher toward his archetype, EB-shrunk) and an **archetype-interaction** model — the latter was
disabled 2026-06-27 because a June backtest showed it made projections *worse* (MAE 1.57 vs 1.43).

### 3.3 From λ to a bet
- **Poisson** (`model/poisson.py`): `P(K > line)` and `P(K < line)`, with correct half-line vs
  integer-line push handling. (Caveat documented in code: real K counts are mildly under-dispersed
  vs Poisson, so near-line probabilities are slightly optimistic; the module is isolated so a
  negative-binomial / ML distribution can replace it without touching anything downstream.)
- **De-vig** (`model/edge.py`): the single most important correction over the original design docs.
  Computing implied probability as `1/odds` includes the bookmaker margin and *overstates edge on
  every bet*. Both sides are normalised to sum to 1. Two methods: `proportional` and **`shin`**
  (Shin's method, corrects favourite–longshot bias) — **`shin` is the default**.
- **Edge** = model probability − de-vigged market probability, evaluated on both sides; the
  higher-edge side wins.
- **Kelly** (`model/kelly.py`, `model/edge.py`): full Kelly `f* = (b·p − q)/b`, then **fractional**
  (default quarter-Kelly, 0.25) and **capped** (default 5% of bankroll).
- **Insight layer** (`model/insight.py`): maps the numbers to a verdict — **Strong Play** (edge ≥ 5%
  with stake), **Lean** (edge ≥ min_edge), **No Bet** / **Pass** — a confidence level, a stake label
  (Small/Medium/Large), and plain-English reasons (opponent K rate, park, projection vs line).

### 3.4 Key tunables (`backend/app/config.py`)
`MIN_EDGE` 0.03 · `KELLY_FRACTION` 0.25 · `KELLY_CAP` 0.05 · `DEVIG_METHOD` shin ·
`MIN_RECENT_STARTS` 5 (low-confidence gate) · `KELLY_GROUP_CAP` 0.08 (per-pitcher aggregate cap) ·
`PROB_SHRINKAGE` 1.0 (off by default; pulls overconfident edges toward the market — set in
production once enough graded data justifies it).

---

## 4. Features

### 4.1 Prediction & slate
- **`GET /predict`** — single pitcher, v1 multiplier model. Fair odds; adds edge + Kelly if you pass
  `over_odds`/`under_odds`.
- **`GET /slate`** — ranked +EV slate for a date (v1). **Logs every evaluated prediction** to
  `data/predictions.csv` (this is the route the daily cron hits to record the price we "took").
- **`GET /v2/predict`** — single pitcher via the ensemble.
- **`GET /v2/slate`** — the main route. Ranked +EV edges via the ensemble, plus a diversified
  **bet card**. Query params:
  - `max_bets` (default 4), `max_per_game` (default 1) — card size + diversification.
  - `select_min_edge` 0.05 / `select_max_edge` 0.20 — edge band (above the cap is treated as likely
    model error, not value).
  - `min_completeness` 0.5 — input-completeness gate (needs enough recent starts / whiff / pitch mix).
  - `kelly_fraction` (0.25–0.50, clamped) — scale every stake; keep at quarter-Kelly while the model
    is young, dial toward half only once the track record justifies it.
  - `sharp_check` (opt-in) — see §4.4.
- **`GET /verticals/mlb`** — convenience wrapper over `/v2/slate` for the multi-vertical UI.

### 4.2 The bet card
`model/selection.py` turns a full slate into a small, sane card for a real bankroll: top `max_bets`
priced bets inside the edge band, **one per game**, gated by input completeness. Card rows carry
`selected=True` + `card_rank`; excluded bets carry the reason. This is the "bet these N, not all 20"
view that the **Simple** dashboard mode shows as colored cards.

### 4.3 Risk controls
- **Correlated-exposure cap** (`model/risk.py`, `cap_correlated`): the per-bet Kelly cap can't see
  that two legs are the *same pitcher* (two books, two lines, or a re-pulled slate). This caps the
  **aggregate** stake per arm (`kelly_group_cap` 0.08, reduce-only). Adds `kelly_capped` /
  `group_capped` without touching raw `kelly`. Fixes a same-arm stacking bug.
- **Stake rounding** for camouflage (`/v2/hedge?round_to=5|10`, frontend `stake.js`): snap the dollar
  stake to a $5/$10 increment. A rounded hedge no longer perfectly equalises both outcomes, so the
  result honestly reports `profit_if_initial` / `profit_if_hedge` separately and `locked_profit` =
  the worst-case floor.

### 4.4 "Vs the field" sharp check
- **`/v2/slate?sharp_check=true`** (`model/divergence.py`): pulls the wide ~3× quote set (≈14 books)
  and **vetoes** any carded play where the model's expected Ks diverge from the **median book line**
  by more than 1.25 K. Vetoed rows stay visible (transparency) but are barred from the card — these
  are usually model errors, not market errors. Opt-in only (it costs the wide quote pull, so it
  never runs on the daily cron).
- It also surfaces **consensus** per card: how many of N books sit at the line and how tightly the
  field clusters (`ConsensusBar.jsx` renders "N/M books at <line> · WITH FIELD ✓ / OUTLIER ⚠️").
  *(Note: Pinnacle is confirmed **absent** from the-odds-api's pitcher-strikeout props, so the
  consensus is a median across all available books, not a Pinnacle reference.)*

### 4.5 Arbitrage & hedging
- **`GET /v2/arb`** (`arb_pipeline.py`, `model/arb.py`): scans the current slate for cross-book,
  same-line two-way strikeout **arbitrage** — lists the two books, the stake split, and the locked
  profit. Rare and short-lived; an inefficiency detector, not an income feed.
- **`GET /v2/hedge`** (`model/hedge.py`): for a position you *already* placed (ideally at positive
  CLV) that the line has since moved on — computes the stake to bet the other side, the capital at
  risk, and the locked result. Flags `risk_free` only when the two prices form a genuine cross-time
  arb; otherwise it's reported honestly as a capped loss.

### 4.6 Parlays
- **`POST /v2/parlay`** (`parlay_pipeline.py`, `model/parlay.py`): combines per-leg ensemble
  projections into a parlay EV + stake. Each leg's win probability comes from the model; you supply
  the book odds. **Hard rules (enforced on the live route):** legs in the same game are **rejected**
  (correlated — the naive product overstates the true joint probability) and the parlay is **capped
  at 3 legs** (`max_legs`, 2–4). `log=true` records each leg so its probability is later scored by
  `/calibration`. *(The pure-math `evaluate_parlay` only warns by default; `build_parlay` turns those
  warnings into hard rejections.)*
- **`GET /v2/parlay/suggest`** (auto-suggester, `suggest_parlays`): builds +EV parlays **only from
  today's bet-card legs** — which are already one-per-game, so independence is guaranteed by
  construction — enumerates 2..`max_legs` combinations and returns the positive-EV ones ranked by EV
  per unit. Probabilities already include the configured `PROB_SHRINKAGE`, so the reported EV is the
  honest production number, not a payout multiple dressed up as an edge. UI: the **🎲 Suggested
  Parlays** panel on the Dashboard (`SuggestedParlays.jsx`, loaded on demand).

### 4.7 The proof layer (does it actually work?)
Three different questions, three routes — all reading the same `predictions.csv` log:
- **`GET /backtest`** (`backtest/`): settle logged predictions vs actual MLB results → **hit rate,
  ROI, MAE**. "Did the flagged bets profit?"
- **`GET /calibration`** (`backtest/reliability.py`): **Brier score, log-loss, reliability curve**
  over *every* decided prediction (not just bets). "When the model says 70%, does it hit ~70%?" —
  the proof a system is calibrated rather than lucky.
- **`GET /clv`** (`backtest/clv.py`): **Closing Line Value** — did flagged bets consistently beat the
  market's *closing* price (positive de-vigged CLV)? The one academically-supported signal of real
  edge. Settles flagged bets against captured closing lines; unmatched bets are reported, not counted.
- **`GET /v2/report`**: latest plain-text weekly grading report (generated by a server cron).
- **`GET /health`**: liveness + active odds provider / de-vig method / min edge.

### 4.8 Dashboard (`frontend/`, React + Vite)
- **Simple mode** — consumer cards: 🟢 Strong / 🟡 Lean / 🔴 Avoid, confidence, plain-English
  reasons, suggested dollar stake. Math hidden.
- **Pro mode** — full table: expected Ks, model vs de-vigged probability, book odds, edge %, Kelly %,
  grade, and (with sharp-check) a "Field (books)" consensus column.
- Pages: Landing, Dashboard (slate + card, bankroll input, Kelly slider, 🔬 sharp-check toggle,
  stake-rounding selector, 🎲 Suggested Parlays), Calibration, CLV, Hedge, Research.

### 4.9 The CLV tracker (the closing-line loop) — the system's real scoreboard
`/clv` (§4.7) is the *report*; this is the **two-part loop** behind it, and it's the single most
important honesty mechanism in the whole app — *"CLV is the only scoreboard the market can't argue
with."* Backtest ROI can be luck over a short sample; **Closing Line Value** (consistently buying a
price better than where the market closes) is the one academically-supported, sample-efficient
signal that an edge is real rather than variance.

**Part 1 — capture the closing lines (you can't reconstruct them; you must record them going
forward).**
- `python -m app.data.line_capture [open|close]` (`app/data/line_capture.py`) appends a timestamped
  snapshot of every strikeout prop to **`data/line_history.csv`**
  (`date,captured_at,tag,pitcher,line,over_odds,under_odds`). Append-only, cheap (single-region props
  pull), tagged `open` or `close` so you also get the open→close *movement* (the size of the
  inefficiency), not just the close.
- Cron: **`strike-clv-capture.timer` @ 22:50 UTC** runs `line_capture close`. *(There is also a
  helper `capture_closing_lines` inside `backtest/clv.py` that writes an untagged closing file; the
  report reads either — when a `tag` column exists it keeps only `close` rows.)*

**Part 2 — settle flagged bets against the close (`clv_report` in `backtest/clv.py`, served at
`/clv`).**
- Takes **only flagged bets** from `predictions.csv` (`bet=True`) that carry **both** over/under
  prices — de-vig needs both sides, so one-sided rows like parlay legs are skipped.
- **Joins** each bet to its closing line by `date` + fuzzy pitcher-name match (`names_match`), taking
  the **latest** capture as the true close.
- Computes **de-vigged CLV** for the side we took = *(de-vigged closing probability for our side)* −
  *(de-vigged probability of the price we bet at)*. **Positive = we bought below where the market
  closed.** CLV is reported in **probability points**, not odds.
- Aggregates into a `ClvReport`: `n_bets` (matched), `n_unmatched` (no usable close yet),
  `mean_clv`, `median_clv`, `pct_positive` (share that beat the close), `total_clv`, and a one-line
  `verdict` — with a **"small sample, provisional"** flag below n=50.

**Frontend** (`pages/Clv.jsx` → `fetchClv()` → `GET /clv`): metric cards (Mean CLV, "real price edge
✓/✗", Beat-the-close %, Median, Scored, Unmatched), the verdict line, and a per-bet table
(date · pitcher · side · CLV · beat/lagged). Green when mean CLV > 0.

**Two caveats baked into the data (carry these forward):**
- **Day games are missed.** The single 22:50 UTC capture is tuned for the night slate; day-game
  closes (~1 pm ET) aren't captured, so those bets show up as `n_unmatched`. Add a ~16:50 UTC capture
  if day games matter.
- **No bookmaker column.** `line_history.csv` stores one closing line per pitcher (whatever single
  book the props pull returned), so CLV is measured against **that** book's close, **not** a
  sharp/Pinnacle reference (Pinnacle is absent from the-odds-api pitcher-K props). Also note the
  report de-vigs with the **`proportional`** method by default, whereas the slate defaults to
  `shin` — a deliberate, documented difference, but worth knowing when comparing numbers.

---

## 5. Daily data pipeline (server, UTC)

Two systemd timers feed the proof layer:
- **`strike-slate.timer`** @ 13:00 UTC → curls `/slate`, which **logs predictions** (the price we
  "took") to `data/predictions.csv`. *(The v1 `/slate` logs; v2 `/slate` does not.)*
- **`strike-clv-capture.timer`** @ 22:50 UTC → captures **closing lines** to `data/line_history.csv`,
  which `/clv` settles against. *(Single nightly capture is tuned for the night slate; day-game
  closes ~1pm ET are missed and show up as `n_unmatched` in `/clv`.)*

---

## 6. Deployment (reference)

- VPS **`kv8`** (Hostinger KVM8, host `srv1786182`; the box my older notes also
  call `newvps` — kv4 + kv6 were migrated onto it ~2026-06-27). `ssh kv8`. App dir `/opt/strike`,
  tracks `origin/main`.
- Backend: **`strike-backend.service`** (systemd) → `uvicorn app.main:app` on **127.0.0.1:8077**;
  nginx proxies **/api → 8077**. Frontend static in `/var/www/strike`.
- Deploy: `deploy/redeploy.sh` (`git pull`, rebuild frontend, reload nginx). It does **not** restart
  the backend — for any backend route/code change, `systemctl restart strike-backend.service`
  yourself or the new route 404s. *(Gotcha: redeploy.sh restarts the wrong, inactive `mlb-edge`
  unit and hardcodes a stale IP — deploy backend changes manually.)*
- Deploy line is the clone `…\stike\mlb-edge\`; commit straight to `main`, push, then deploy.

---

## 7. Status & honesty notes

- Edges are **unproven until validated by logged CLV.** A crude Poisson model disagrees with the
  market often, and most disagreements are model error — hence the sharp-check veto, the edge-band
  cap, the low-confidence gate, and quarter-Kelly defaults.
- Pure-logic modules (risk, hedge, arb, CLV report, ensemble pipeline, parlay) are unit-tested and
  green; the only failing tests are live-network/integration smoke tests.
- Explicitly **not built** (declined): mug-betting / profiling-evasion automation, and a 10-site
  tout-pick scraper (no free, scrapable source of pitcher-K *picks* exists; the wide book pull
  already provides line consensus).
