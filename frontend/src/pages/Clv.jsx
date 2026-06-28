import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchClv } from "../api.js";

// Closing Line Value — the sharp's truth metric. /backtest asks "did we
// profit?", /calibration asks "are our probabilities honest?"; this asks the
// price question: across every flagged bet matched to a captured closing line,
// did we consistently buy below where the market closed? Positive de-vigged CLV
// is the one academically-supported signal of real edge.

// CLV is a de-vigged probability delta; show it as signed probability-points.
const pts = (x) => (x == null ? "—" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(2)} pts`);
const pct = (x) => (x == null ? "—" : `${(x * 100).toFixed(0)}%`);

function Metric({ label, value, hint, tone }) {
  return (
    <div className={`cal-metric${tone ? ` ${tone}` : ""}`}>
      <div className="cal-metric-value">{value}</div>
      <div className="cal-metric-label">{label}</div>
      {hint && <div className="cal-metric-hint">{hint}</div>}
    </div>
  );
}

export default function Clv() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchClv());
    } catch (e) {
      setError(e.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const hasSample = data && data.n_bets > 0;
  const edgeTone = data?.mean_clv == null ? "" : data.mean_clv > 0 ? "good" : "bad";

  return (
    <div className="app">
      <header>
        <div className="nav">
          <Link to="/" className="home-link">← Home</Link>
          <Link to="/calibration" className="home-link">🎯 Calibration</Link>
        </div>
        <h1>📈 Closing Line Value</h1>
        <p className="sub">
          Did our flagged bets beat the market's closing price? Buying below where
          the line closes — positive CLV — is the one price-based proof of real
          edge, not luck.
        </p>
      </header>

      <div className="controls">
        <button onClick={load} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error">⚠ {error}</p>}

      {data && !hasSample && (
        <p className="sub" style={{ textAlign: "center", margin: "2rem 0" }}>
          {data.verdict || "No flagged bets matched a captured closing line yet."}
          {data.n_unmatched > 0 && (
            <>
              <br />
              {data.n_unmatched} flagged bet{data.n_unmatched === 1 ? "" : "s"} had
              no closing line to score against.
            </>
          )}
        </p>
      )}

      {hasSample && (
        <>
          <div className="cal-metrics">
            <Metric
              label="Mean CLV"
              value={pts(data.mean_clv)}
              hint="avg de-vigged edge vs close"
              tone={edgeTone}
            />
            <Metric
              label={data.mean_clv > 0 ? "Real price edge" : "No price edge"}
              value={data.mean_clv > 0 ? "✓" : "✗"}
              hint="positive mean CLV = edge"
              tone={edgeTone}
            />
            <Metric
              label="Beat the close"
              value={pct(data.pct_positive)}
              hint="share of bets with +CLV"
              tone={data.pct_positive == null ? "" : data.pct_positive >= 0.5 ? "good" : "warn"}
            />
            <Metric label="Median CLV" value={pts(data.median_clv)} hint="typical bet" />
            <Metric label="Scored bets" value={data.n_bets} hint="matched to a close" />
            <Metric
              label="Unmatched"
              value={data.n_unmatched}
              hint="no closing line yet"
              tone={data.n_unmatched > 0 ? "warn" : ""}
            />
          </div>

          <p className="cal-verdict">{data.verdict}</p>

          <table className="cal-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Pitcher</th>
                <th>Side</th>
                <th>CLV</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {data.bets.map((b, i) => (
                <tr key={i}>
                  <td className="cal-band">{b.date}</td>
                  <td>{b.pitcher}</td>
                  <td>{b.side}</td>
                  <td className={`cal-gap ${b.beat_close ? "ok" : "bad"}`}>{pts(b.clv)}</td>
                  <td>{b.beat_close ? "beat close ✓" : "lagged ✗"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="sub cal-foot">
            CLV is measured in de-vigged probability: positive means the market
            closed implying a higher chance for our side than the price we took.
            Needs closing lines captured near first pitch; unmatched bets aren't
            scored.
          </p>
        </>
      )}

      <footer>CLV is the only scoreboard the market can't argue with.</footer>
    </div>
  );
}
