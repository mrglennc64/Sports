import { useState } from "react";
import { Link } from "react-router-dom";
import { fetchHedge } from "../api.js";

// Hedge an EXISTING position — the CLV-lock calculator. You took an early bet at
// a price you liked; the line moved. This computes the stake on the OPPOSITE side
// that equalises payout across both outcomes, and whether that locks a profit (a
// true cross-time arb) or merely caps a loss. Mirrors the /v2/hedge backend.

const money = (x) => (x == null ? "—" : `$${x.toFixed(2)}`);
const oddsFmt = (x) =>
  x === "" || x == null ? "—" : Number(x) > 0 ? `+${x}` : `${x}`;

export default function Hedge() {
  const [stake, setStake] = useState("100");
  const [odds, setOdds] = useState("115");
  const [hedgeOdds, setHedgeOdds] = useState("105");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function calc() {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchHedge(Number(stake), Number(odds), Number(hedgeOdds)));
    } catch (e) {
      setError(e.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header>
        <div className="nav">
          <Link to="/" className="home-link">← Home</Link>
          <Link to="/clv" className="home-link">📈 CLV</Link>
        </div>
        <h1>🛡️ Hedge Calculator</h1>
        <p className="sub">
          You took an early bet at a price you liked and the line moved. This finds
          the stake on the <b>opposite</b> side that equalises your payout — locking
          a guaranteed result if the two prices cross into an arb, or capping the
          loss if they don't.
        </p>
      </header>

      <div className="hedge-form">
        <label>
          Original stake ($)
          <input
            type="number"
            value={stake}
            min={0}
            step="0.01"
            onChange={(e) => setStake(e.target.value)}
          />
        </label>
        <label>
          Original odds (American)
          <input
            type="number"
            value={odds}
            onChange={(e) => setOdds(e.target.value)}
          />
          <small>the price you ALREADY took, e.g. +115</small>
        </label>
        <label>
          Hedge odds (American)
          <input
            type="number"
            value={hedgeOdds}
            onChange={(e) => setHedgeOdds(e.target.value)}
          />
          <small>opposite side available NOW, e.g. +105 or -120</small>
        </label>
        <button onClick={calc} disabled={loading}>
          {loading ? "Calculating…" : "Calculate hedge"}
        </button>
      </div>

      {error && <p className="error">⚠ {error}</p>}

      {data && (
        <>
          <div
            className={`hedge-verdict ${data.risk_free ? "locked" : "capped"}`}
          >
            {data.risk_free
              ? "✅ Risk-free lock — guaranteed profit on either outcome"
              : "⚠️ No free money — this caps a loss rather than locking a profit"}
          </div>

          <div className="hedge-results">
            <div className="hedge-cell highlight">
              <div className="hedge-cell-value">{money(data.hedge_stake)}</div>
              <div className="hedge-cell-label">HEDGE STAKE</div>
              <div className="hedge-cell-hint">
                bet this at {oddsFmt(data.hedge_odds)} on the opposite side
              </div>
            </div>
            <div
              className={`hedge-cell highlight ${
                data.locked_profit >= 0 ? "good" : "bad"
              }`}
            >
              <div className="hedge-cell-value">{money(data.locked_profit)}</div>
              <div className="hedge-cell-label">LOCKED PROFIT</div>
              <div className="hedge-cell-hint">
                {data.roi_pct >= 0 ? "+" : ""}
                {data.roi_pct}% on capital at risk
              </div>
            </div>
            <div className="hedge-cell">
              <div className="hedge-cell-value">{money(data.total_outlay)}</div>
              <div className="hedge-cell-label">Capital at risk</div>
              <div className="hedge-cell-hint">original + hedge stake</div>
            </div>
            <div className="hedge-cell">
              <div className="hedge-cell-value">{money(data.locked_return)}</div>
              <div className="hedge-cell-label">Locked return</div>
              <div className="hedge-cell-hint">same on either outcome</div>
            </div>
          </div>

          <p className="sub hedge-foot">
            The hedge stake equalises your gross return whether the original side
            wins or loses. A guaranteed profit exists only when the two prices form
            an arb across time (sum of inverse decimals &lt; 1) — otherwise locking
            a smaller loss can still be the right risk decision, which is why this
            reports a capped loss honestly instead of hiding it.
          </p>
        </>
      )}

      <footer>Lock the value you already captured — don't give it back to variance.</footer>
    </div>
  );
}
