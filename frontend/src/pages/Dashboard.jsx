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

  async function load(d) {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchSlate(d, null, kellyFraction));
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

      {error && <p className="error">⚠ {error}</p>}

      {data && (
        <div className="summary">
          <span><b>{data.evaluated}</b> projected</span>
          <span>⭐ <b>{data.card_size}</b> featured</span>
          <span><b>{data.skipped}</b> unavailable</span>
        </div>
      )}

      {data &&
        (mode === "simple" ? (
          <SimpleCards rows={rows} />
        ) : (
          <SlateTable rows={rows} />
        ))}

      <footer>
        Projections based on historical data. Validate with live results.
      </footer>
    </div>
  );
}
