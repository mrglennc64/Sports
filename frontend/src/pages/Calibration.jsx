import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchCalibration } from "../api.js";

// Are the model's probabilities honest? Surfaces the /calibration reliability
// tracker: when the model claims 70%, does it hit ~70% over a large sample?
// This is the proof a system is calibrated rather than lucky — scored across
// EVERY decided prediction, not just flagged +EV bets.

const pct = (x) => (x == null ? "—" : `${(x * 100).toFixed(1)}%`);
const num = (x, d = 3) => (x == null ? "—" : x.toFixed(d));

function Metric({ label, value, hint, tone }) {
  return (
    <div className={`cal-metric${tone ? ` ${tone}` : ""}`}>
      <div className="cal-metric-value">{value}</div>
      <div className="cal-metric-label">{label}</div>
      {hint && <div className="cal-metric-hint">{hint}</div>}
    </div>
  );
}

// One reliability-curve bucket: claimed band, sample size, and a paired bar
// comparing claimed probability against the realized win rate. When the two
// bars line up, that bucket is well calibrated.
function Bin({ b }) {
  const predW = Math.round(Math.min(Math.max(b.avg_predicted, 0), 1) * 100);
  const actW = Math.round(Math.min(Math.max(b.actual_rate, 0), 1) * 100);
  const gapTone = Math.abs(b.gap) < 0.05 ? "ok" : Math.abs(b.gap) < 0.1 ? "warn" : "bad";
  return (
    <tr>
      <td className="cal-band">
        {pct(b.lo)}–{pct(b.hi)}
      </td>
      <td className="cal-n">{b.n}</td>
      <td className="cal-bars">
        <div className="cal-bar-row">
          <span className="cal-bar-tag">claimed</span>
          <div className="cal-bar-track">
            <div className="cal-bar cal-bar-pred" style={{ width: `${predW}%` }} />
          </div>
          <span className="cal-bar-val">{pct(b.avg_predicted)}</span>
        </div>
        <div className="cal-bar-row">
          <span className="cal-bar-tag">actual</span>
          <div className="cal-bar-track">
            <div className="cal-bar cal-bar-act" style={{ width: `${actW}%` }} />
          </div>
          <span className="cal-bar-val">{pct(b.actual_rate)}</span>
        </div>
      </td>
      <td className={`cal-gap ${gapTone}`}>
        {b.gap > 0 ? "+" : ""}
        {pct(b.gap)}
      </td>
    </tr>
  );
}

export default function Calibration() {
  const [data, setData] = useState(null);
  const [bins, setBins] = useState(10);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function load(n) {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchCalibration(n));
    } catch (e) {
      setError(e.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(bins);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const hasSample = data && data.n > 0;
  const skillTone = data?.skill == null ? "" : data.skill ? "good" : "bad";

  return (
    <div className="app">
      <header>
        <div className="nav">
          <Link to="/" className="home-link">← Home</Link>
          <Link to="/clv" className="home-link">📈 CLV</Link>
        </div>
        <h1>🎯 Calibration Tracker</h1>
        <p className="sub">
          Are the model's probabilities honest? When it says 70%, does it happen
          ~70% of the time — across every decided prediction, not just the bets
          we flagged.
        </p>
      </header>

      <div className="controls">
        <label>
          Buckets{" "}
          <input
            type="number"
            min={2}
            max={50}
            value={bins}
            onChange={(e) => setBins(Number(e.target.value))}
            style={{ width: "4rem" }}
          />
        </label>
        <button onClick={() => load(bins)} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error">⚠ {error}</p>}

      {data && !hasSample && (
        <p className="sub" style={{ textAlign: "center", margin: "2rem 0" }}>
          {data.verdict || "No decided predictions with a logged probability yet."}
        </p>
      )}

      {hasSample && (
        <>
          <div className="cal-metrics">
            <Metric
              label="Brier score"
              value={num(data.brier)}
              hint={`vs ${num(data.reference_brier)} base-rate`}
              tone={skillTone}
            />
            <Metric
              label={data.skill ? "Beats base rate" : "No edge yet"}
              value={data.skill ? "✓" : "✗"}
              hint="Brier below reference = skill"
              tone={skillTone}
            />
            <Metric label="Log loss" value={num(data.log_loss)} hint="punishes confident misses" />
            <Metric
              label="ECE"
              value={pct(data.ece)}
              hint="mean calibration error"
              tone={data.ece == null ? "" : data.ece < 0.05 ? "good" : data.ece < 0.1 ? "warn" : "bad"}
            />
            <Metric label="Claimed avg" value={pct(data.avg_predicted)} hint="mean model prob" />
            <Metric label="Realized" value={pct(data.base_rate)} hint="actual win rate" />
            <Metric label="Sample" value={data.n} hint="decided predictions" />
          </div>

          <p className="cal-verdict">{data.verdict}</p>

          <table className="cal-table">
            <thead>
              <tr>
                <th>Claimed band</th>
                <th>n</th>
                <th>Claimed vs actual</th>
                <th>Gap</th>
              </tr>
            </thead>
            <tbody>
              {data.bins.map((b, i) => (
                <Bin key={i} b={b} />
              ))}
            </tbody>
          </table>
          <p className="sub cal-foot">
            Gap = actual − claimed. Positive means the model was underconfident in
            that band; negative means overconfident. Pushes and pre-probability
            rows are excluded.
          </p>
        </>
      )}

      <footer>Calibration is the proof a system is honest, not lucky.</footer>
    </div>
  );
}
