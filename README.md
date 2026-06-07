# MLB Strikeout Edge Platform

A quantitative pricing engine for **pitcher-strikeout over/under props**. It pulls
real MLB data, estimates each starter's expected strikeouts, converts that to
over/under probabilities, compares them against **de-vigged** sportsbook odds, and
surfaces +EV plays with Kelly-sized stakes — then translates the math into plain
human decisions (Strong Play / Lean / No Bet).

> ⚠️ **Analytics tool, not betting advice.** It surfaces and logs signals; it does not
> place bets. Edges are unproven until validated by logged closing-line value (CLV).

This is the first **runnable** version of the blueprint in the `../*.pdf` docs — which
were all design-only and used placeholder stats. See *Correctness notes* below for the
real math bugs those blueprints contained that this implementation fixes.

---

## Architecture

```
MLB Stats API ─┐
the-odds-api ──┤→ pipeline ─→ expected Ks (Poisson) ─→ de-vig + edge + Kelly
park factors ──┘                                          ─→ decision/insight layer
                                                          ─→ ranked slate + CSV log
FastAPI (/health /predict /slate)  ←→  React (Vite) dashboard: Simple + Pro modes
```

| Layer | Files |
|---|---|
| Math engine | `backend/app/model/poisson.py`, `edge.py` (odds, **de-vig**, Kelly), `expected_ks.py`, `insight.py` |
| Data | `backend/app/data/mlb.py` (free MLB API), `odds.py` (provider adapter), `park.py`, `names.py`, `cache.py` |
| Orchestration | `backend/app/pipeline.py`, `log/predictions.py` |
| API | `backend/app/main.py` |
| Frontend | `frontend/` (React + Vite, Simple/Pro modes) |

---

## Correctness notes (fixes over the source PDFs)

1. **De-vig the book odds.** The PDFs computed implied probability as `1/odds`, which
   includes the bookmaker margin and *overstates edge on every bet*. We normalise the
   over/under pair so it sums to 1. Two methods: `proportional` and **`shin`**
   (Shin's method, corrects favorite–longshot bias; adapted from the `mberk/shin` and
   `goto_conversion` projects on GitHub's `betting` topic). Default: `shin`.
2. **Half-line handling.** "Over 6.5" = `P(K ≥ 7)`, with integer-line pushes handled.
3. **Normalised opponent factor.** `M_opp = opp_K% / league_avg_K%` instead of a magic
   constant.
4. **Spot-starter guard.** Season `IP/GS` and `K/9` get inflated by relief appearances
   (e.g. a pitcher with 2 starts but 31 relief innings). Innings-per-start is clamped to
   a starter-plausible range and low-sample pitchers are flagged `low_confidence` and
   never marked a bet.
5. **Fractional Kelly + cap.** Quarter-Kelly, hard-capped at 5% of bankroll.
6. **Poisson caveat.** Strikeouts are mildly under-dispersed vs Poisson; the model layer
   is isolated so a negative-binomial or ML/Monte-Carlo distribution can replace it
   without touching the edge engine or API.

---

## Setup

### Backend (Python 3.11+)

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env              # then put your real odds key in .env (gitignored)
```

`.env` keys:

| var | meaning |
|---|---|
| `ODDS_PROVIDER` | `theoddsapi` (confirmed working) or `oddsapiio` |
| `ODDS_API_KEY_THEODDSAPI` | your the-odds-api.com key (32-hex) |
| `ODDS_API_KEY_IO` | your odds-api.io/oddspapi.io key (UUID; adapter not yet implemented) |
| `MIN_EDGE` | min edge to flag a bet (default 0.03) |
| `KELLY_FRACTION` / `KELLY_CAP` | staking (default 0.25 / 0.05) |
| `DEVIG_METHOD` | `shin` or `proportional` |

Run it:

```bash
uvicorn app.main:app --reload --port 8000
pytest                            # 50 tests: math, data (mocked), pipeline, insight
```

### Frontend

```bash
cd frontend
npm install
npm run dev                       # http://localhost:5173  (expects backend on :8000)
```

---

## API

| Route | Description |
|---|---|
| `GET /health` | liveness + active config |
| `GET /predict?pitcher=&line=&date=&over_odds=&under_odds=` | single pitcher (matched to that day's starts); fair odds, plus edge/Kelly if book odds given |
| `GET /slate?date=&min_edge=` | ranked +EV slate for a date; logs every evaluated prediction to `data/predictions.csv` |

Example:

```bash
curl "localhost:8000/predict?pitcher=Nola&line=5.5&over_odds=-115&under_odds=-105"
curl "localhost:8000/slate?min_edge=0.05"
```

---

## Dashboard

- **Simple mode** — consumer cards: colored verdict (🟢 Strong / 🟡 Lean / 🔴 Avoid),
  confidence, plain-English reasons, suggested stake. Math hidden.
- **Pro mode** — full table: expected Ks, model vs de-vigged probability, book odds,
  edge %, Kelly %, grade. (UX patterns inspired by HOF App's leaderboard/trends views.)

---

## Prediction logging → the path to *proving* edge

Every evaluated start is appended to `data/predictions.csv` (line, λ, model prob,
de-vigged implied, edge, Kelly). This is the seed for the next phase: a backtest/CLV
tracker that checks whether the model actually beat closing lines. **Until that exists,
treat all flagged edges as hypotheses** — a crude Poisson model will disagree with the
market often, and most of those disagreements are model error, not market error.

## Roadmap (out of scope for v1)

- Backtest + CLV tracker (consumes `predictions.csv` vs closing lines)
- Monte-Carlo / negative-binomial probability engine; XGBoost λ-correction
- Recent-form (`M_form`) and RHP/LHP opponent splits; real park factors
- Discord/Telegram alerts; second odds-provider adapter; multi-book line shopping
- Auth, deployment (Docker), SaaS packaging
