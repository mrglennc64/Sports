import { useState } from "react";

const pct = (x) => (x == null ? "—" : `${(x * 100).toFixed(1)}%`);
const odds = (x) => (x == null ? "—" : x > 0 ? `+${x}` : `${x}`);

export default function SlateTable({ rows }) {
  const [showMarketData, setShowMarketData] = useState(false);

  const evaluated = rows.filter((r) => r.status === "ok");
  if (evaluated.length === 0) {
    return <p className="empty">No evaluated props for this date.</p>;
  }
  return (
    <div>
      <button
        onClick={() => setShowMarketData(!showMarketData)}
        className="toggle-market-btn"
        style={{
          padding: '8px 16px',
          marginBottom: '16px',
          backgroundColor: showMarketData ? '#ff6b6b' : '#4CAF50',
          color: 'white',
          border: 'none',
          borderRadius: '4px',
          cursor: 'pointer',
          fontSize: '14px',
          fontWeight: 'bold'
        }}
      >
        {showMarketData ? "Mute Market Data" : "Reveal Market Data"}
      </button>
      <table className="slate">
        <thead>
          <tr>
            <th>Pitcher</th>
            <th>Opponent</th>
            <th>Line</th>
            <th>Pick</th>
            <th>Projected Ks</th>
            {showMarketData && (
              <>
                <th>Model %</th>
                <th>Fair %</th>
                <th>Odds</th>
                <th>Edge %</th>
                <th>Kelly %</th>
                <th>Book</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {evaluated.map((r, i) => {
            const sideOdds = r.side === "over" ? r.over_odds : r.under_odds;
            return (
              <tr
                key={i}
                className={
                  r.selected ? "carded" : r.low_confidence ? "lowconf" : ""
                }
              >
                <td className="pitcher">
                  {r.selected && <span className="tag tag-card">⭐ #{r.card_rank}</span>}
                  {r.pitcher}
                  {r.low_confidence && <span className="tag tag-low">low sample</span>}
                </td>
                <td>{r.opponent}</td>
                <td>{r.line}</td>
                <td className={`side side-${r.side}`}>{r.side?.toUpperCase()}</td>
                <td>{r.expected_ks?.toFixed(2)}</td>
                {showMarketData && (
                  <>
                    <td>{pct(r.model_prob)}</td>
                    <td>{pct(r.fair_prob)}</td>
                    <td>{odds(sideOdds)}</td>
                    <td className={r.edge >= 0.03 ? "edge-pos" : "edge-neg"}>
                      {r.edge >= 0 ? "+" : ""}
                      {pct(r.edge)}
                    </td>
                    <td>{pct(r.kelly)}</td>
                    <td className="book">{r.bookmaker}</td>
                  </>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
