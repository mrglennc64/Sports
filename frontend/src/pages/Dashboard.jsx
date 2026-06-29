import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchSlate } from "../api.js";
import SlateTable from "../components/SlateTable.jsx";
import SimpleCards from "../components/SimpleCards.jsx";

function today() {
  return new Date().toISOString().slice(0, 10);
}

export default function Dashboard() {
  const [date, setDate] = useState(today());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [cardOnly, setCardOnly] = useState(false);
  const [mode, setMode] = useState("simple"); // "simple" | "pro"
  // Kelly scale: 0.25 (quarter) while the model is young; dial toward 0.5 (half)
  // only once calibration + track record justify it. Backend clamps to [0.25, 0.5].
  const [kellyFraction, setKellyFraction] = useState(0.25);
  // Sharp check: veto edges where the model is a market-consensus outlier. Costs
  // the wide (~3x) quote pull, so it's off by default and only runs on demand.
  const [sharpCheck, setSharpCheck] = useState(false);
  // Bankroll + stake rounding: turn the per-bet Kelly fraction into an actual
  // dollar stake, snapped to a whole-dollar increment so the wager blends in as a
  // casual bet rather than an obviously-optimised number. 0 = show no $ stakes.
  const [bankroll, setBankroll] = useState(0);
  const [stakeRound, setStakeRound] = useState(5);

  async function load(d, sharp = sharpCheck) {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchSlate(d, null, kellyFraction, sharp));
    } catch (e) {
      setError(e.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(date);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  let rows = data?.rows ?? [];
  if (cardOnly) rows = rows.filter((r) => r.selected);

  return (
    <div className="app">
      <header>
        <div className="nav">
          <Link to="/" className="home-link">← Home</Link>
          <Link to="/calibration" className="home-link">🎯 Calibration</Link>
          <Link to="/clv" className="home-link">📈 CLV</Link>
          <Link to="/hedge" className="home-link">🛡️ Hedge</Link>
        </div>
        <h1>⚾ Strikeout Projections</h1>
        <p className="sub">
          Pitcher strikeout projections with confidence levels.
        </p>
      </header>

      <div className="controls">
        <label>
          Date{" "}
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <button onClick={() => load(date)} disabled={loading}>
          {loading ? "Loading…" : "Load slate"}
        </button>
        <label className="toggle">
          <input
            type="checkbox"
            checked={cardOnly}
            onChange={(e) => setCardOnly(e.target.checked)}
          />
          Today's card only
        </label>
        <label className="toggle" title="Veto plays where the model disagrees with the market consensus by more than ~1 strikeout — likely a projection error, not an edge. Costs ~3x the odds quota.">
          <input
            type="checkbox"
            checked={sharpCheck}
            onChange={(e) => {
              setSharpCheck(e.target.checked);
              load(date, e.target.checked);
            }}
          />
          🔬 Sharp check
        </label>
        <div className="modes">
          <button
            className={mode === "simple" ? "active" : ""}
            onClick={() => setMode("simple")}
          >
            Simple
          </button>
          <button
            className={mode === "pro" ? "active" : ""}
            onClick={() => setMode("pro")}
          >
            Pro
          </button>
        </div>
      </div>

      <div className="kelly-control">
        <label className="kelly-label">
          <span>
            Kelly scale: <b>{kellyFraction.toFixed(2)}×</b>{" "}
            <span className="kelly-name">
              {kellyFraction <= 0.3
                ? "Quarter — young model"
                : kellyFraction < 0.45
                ? "Three-eighths — building trust"
                : "Half — proven track record"}
            </span>
          </span>
          <input
            type="range"
            min={0.25}
            max={0.5}
            step={0.05}
            value={kellyFraction}
            onChange={(e) => setKellyFraction(Number(e.target.value))}
          />
        </label>
        <p className="kelly-hint">
          Keep this at 0.25× while the sample is small. Only dial toward 0.50× once{" "}
          <Link to="/calibration">calibration</Link> and{" "}
          <Link to="/clv">CLV</Link> prove the edge is real — higher Kelly grows the
          bankroll faster but deepens drawdowns. Reload the slate to apply.
        </p>
      </div>

      <div className="bankroll-control">
        <label className="bankroll-label">
          Bankroll ($)
          <input
            type="number"
            min={0}
            step="50"
            value={bankroll}
            onChange={(e) => setBankroll(Number(e.target.value))}
            placeholder="0 = hide $ stakes"
          />
        </label>
        <label className="bankroll-label">
          Round stake
          <select
            value={stakeRound}
            onChange={(e) => setStakeRound(Number(e.target.value))}
          >
            <option value={0}>Exact</option>
            <option value={5}>Nearest $5</option>
            <option value={10}>Nearest $10</option>
          </select>
        </label>
        <p className="kelly-hint">
          Enter a bankroll to see the dollar stake per play — the capped Kelly
          fraction × bankroll, <b>rounded down</b> to a round number so it blends in
          as a casual bet <b>without ever exceeding</b> your Kelly limit. (A stake
          smaller than one increment is too small to bet.)
        </p>
      </div>

      {error && <p className="error">⚠ {error}</p>}

      {data && (
        <div className="summary">
          <span><b>{data.evaluated}</b> projected</span>
          <span>⭐ <b>{data.card_size}</b> featured</span>
          <span><b>{data.skipped}</b> unavailable</span>
          {data.sharp_check && (
            <span className="sharp-summary">
              🔬 <b>{data.sharp_vetoed}</b> vetoed (model vs market)
            </span>
          )}
        </div>
      )}

      {data &&
        (mode === "simple" ? (
          <SimpleCards rows={rows} bankroll={bankroll} stakeRound={stakeRound} />
        ) : (
          <SlateTable rows={rows} bankroll={bankroll} stakeRound={stakeRound} />
        ))}

      <footer>
        Projections based on historical data. Validate with live results.
      </footer>
    </div>
  );
}
