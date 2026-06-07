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
  const [betsOnly, setBetsOnly] = useState(false);
  const [mode, setMode] = useState("simple"); // "simple" | "pro"

  async function load(d) {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchSlate(d));
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
  if (betsOnly) rows = rows.filter((r) => r.bet);

  return (
    <div className="app">
      <header>
        <div className="nav">
          <Link to="/" className="home-link">← Home</Link>
        </div>
        <h1>⚾ Strikeout Edge — Engine</h1>
        <p className="sub">
          Model-priced pitcher-strikeout props vs. de-vigged sportsbook odds.
          Signals only — verify before betting.
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
            checked={betsOnly}
            onChange={(e) => setBetsOnly(e.target.checked)}
          />
          Sharp bets only
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

      {error && <p className="error">⚠ {error}</p>}

      {data && (
        <div className="summary">
          <span><b>{data.evaluated}</b> evaluated</span>
          <span><b>{data.bets}</b> flagged bets</span>
          <span><b>{data.skipped}</b> skipped (no prop / no stats)</span>
        </div>
      )}

      {data &&
        (mode === "simple" ? (
          <SimpleCards rows={rows} />
        ) : (
          <SlateTable rows={rows} />
        ))}

      <footer>
        Edges are unproven until validated by logged CLV. This is an analytics tool,
        not betting advice.
      </footer>
    </div>
  );
}
