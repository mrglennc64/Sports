// Central backend base URL. Override with VITE_API_BASE at build/dev time.
const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export async function fetchSlate(date, minEdge, kellyFraction) {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  if (minEdge != null && minEdge !== "") params.set("min_edge", minEdge);
  if (kellyFraction != null && kellyFraction !== "")
    params.set("kelly_fraction", kellyFraction);
  const res = await fetch(`${BASE}/v2/slate?${params.toString()}`);
  if (!res.ok) throw new Error(`slate request failed: ${res.status}`);
  return res.json();
}

// Hedge an EXISTING position: you took `stake` at `odds`, the line moved, and
// betting the opposite side now at `hedgeOdds` may lock a result. Returns the
// hedge stake, capital at risk, and locked profit (risk_free only on a true
// cross-time arb). See /v2/hedge backend.
export async function fetchHedge(stake, odds, hedgeOdds) {
  const params = new URLSearchParams({
    stake: String(stake),
    odds: String(odds),
    hedge_odds: String(hedgeOdds),
  });
  const res = await fetch(`${BASE}/v2/hedge?${params.toString()}`);
  if (!res.ok) throw new Error(`hedge request failed: ${res.status}`);
  return res.json();
}

// Reliability / calibration tracker: are the model's probabilities honest?
// Returns Brier, log-loss, ECE, the base-rate reference, and the reliability
// curve (one bucket per claimed-probability band). See /calibration backend.
export async function fetchCalibration(bins) {
  const params = new URLSearchParams();
  if (bins != null && bins !== "") params.set("bins", bins);
  const qs = params.toString();
  const res = await fetch(`${BASE}/calibration${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`calibration request failed: ${res.status}`);
  return res.json();
}

// Closing Line Value: did flagged bets beat the market's closing price?
// Returns mean/median de-vigged CLV, % of bets that beat the close, and the
// per-bet breakdown. See /clv backend.
export async function fetchClv() {
  const res = await fetch(`${BASE}/clv`);
  if (!res.ok) throw new Error(`clv request failed: ${res.status}`);
  return res.json();
}
