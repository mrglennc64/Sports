import { useState } from "react";
import { fetchParlaySuggestions } from "../api.js";

// Auto-suggested +EV parlays built from today's bet card. Loaded ON DEMAND (the
// button) because it rebuilds the full slate server-side. Every suggestion is
// independent-by-construction (the card is one bet per game) and capped at 3 legs
// — the same hard rules the backend enforces. EV here is the honest production
// number (probabilities already include the configured shrinkage).
export default function SuggestedParlays({ date, bankroll = 0, stakeRound = 5 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [maxLegs, setMaxLegs] = useState(3);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchParlaySuggestions(date, maxLegs, 6));
    } catch (e) {
      setError(e.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  function dollarStake(kelly) {
    if (!bankroll || !kelly || kelly <= 0) return null;
    const raw = kelly * bankroll;
    if (!stakeRound) return `$${raw.toFixed(2)}`;
    const snapped = Math.floor(raw / stakeRound) * stakeRound;
    return snapped >= stakeRound ? `$${snapped}` : "too small";
  }

  return (
    <section className="parlay-suggest">
      <div className="parlay-head">
        <h2>🎲 Suggested Parlays</h2>
        <span className="parlay-sub">
          +EV combinations of today's card legs — independent (one game each),
          capped at 3 legs.
        </span>
      </div>

      <div className="parlay-controls">
        <label>
          Max legs{" "}
          <select
            value={maxLegs}
            onChange={(e) => setMaxLegs(Number(e.target.value))}
          >
            <option value={2}>2</option>
            <option value={3}>3</option>
          </select>
        </label>
        <button onClick={load} disabled={loading}>
          {loading ? "Building…" : "Suggest parlays"}
        </button>
      </div>

      {error && <p className="error">⚠ {error}</p>}

      {data && data.n_suggestions === 0 && (
        <p className="parlay-empty">
          No +EV parlays from today's card ({data.eligible_legs} eligible leg
          {data.eligible_legs === 1 ? "" : "s"}). A parlay needs at least two
          independent +EV legs.
        </p>
      )}

      {data && data.n_suggestions > 0 && (
        <div className="parlay-list">
          {data.suggestions.map((s, i) => {
            const stake = dollarStake(s.kelly);
            return (
              <div className="parlay-card" key={i}>
                <div className="parlay-card-top">
                  <span className="parlay-legs-count">{s.n_legs}-leg</span>
                  {s.risk && (
                    <span
                      className={`parlay-risk risk-${s.risk.tier}`}
                      title="Risk tier from the parlay's own win probability + leg count (not CLV — there isn't enough graded data yet)."
                    >
                      {s.risk.tier} risk
                    </span>
                  )}
                  <span className="parlay-ev">
                    +{(s.ev_per_unit * 100).toFixed(1)}% EV
                  </span>
                  <span className="parlay-payout">
                    {s.book_decimal.toFixed(2)}× payout
                  </span>
                </div>
                <ul className="parlay-leg-list">
                  {s.legs.map((leg, j) => (
                    <li key={j}>
                      <span className="leg-label">{leg.label}</span>
                      <span className="leg-odds">
                        {leg.american_odds > 0
                          ? `+${leg.american_odds}`
                          : leg.american_odds}{" "}
                        · {(leg.model_prob * 100).toFixed(0)}%
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="parlay-card-bottom">
                  <span>
                    Win prob <b>{(s.model_prob * 100).toFixed(1)}%</b>
                    {s.risk && (
                      <em className="parlay-loses"> · loses {s.risk.loses_about}</em>
                    )}
                  </span>
                  <span>
                    Kelly <b>{(s.kelly * 100).toFixed(2)}%</b>
                  </span>
                  {stake && (
                    <span>
                      Stake <b>{stake}</b>
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {data && (
        <p className="parlay-note">
          ⚠ Parlay EV compounds your edge <i>and</i> your model error. These are
          unproven until validated by CLV — treat them as the boldest, highest-
          variance slice of the card.
        </p>
      )}
    </section>
  );
}
