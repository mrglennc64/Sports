// Simple ("consumer") mode: hide the math, show a decision per HOF-style feedback.
const SIGNAL_RANK = { strong: 0, lean: 1, avoid: 2 };
const SIGNAL_EMOJI = { strong: "🟢", lean: "🟡", avoid: "🔴" };

export default function SimpleCards({ rows }) {
  const cards = rows
    .filter((r) => r.status === "ok")
    .sort(
      (a, b) =>
        (SIGNAL_RANK[a.signal] ?? 3) - (SIGNAL_RANK[b.signal] ?? 3) ||
        b.edge - a.edge
    );

  if (cards.length === 0) return <p className="empty">No props to show.</p>;

  return (
    <div className="cards">
      {cards.map((r, i) => (
        <div key={i} className={`card sig-${r.signal}`}>
          <div className="card-top">
            <span className="card-signal">{SIGNAL_EMOJI[r.signal]} {r.recommendation}</span>
            <span className="card-conf">{r.confidence} confidence</span>
          </div>
          <div className="card-pick">
            {r.pitcher} <b>{r.side?.toUpperCase()} {r.line} Ks</b>
          </div>
          <div className="card-vs">vs {r.opponent}</div>
          <ul className="card-reasons">
            {r.reasons.slice(0, 3).map((reason, j) => (
              <li key={j}>{reason}</li>
            ))}
          </ul>
          <div className="card-stake">
            Suggested stake: <b>{r.stake_label}</b>
            {r.stake_label !== "—" && r.kelly != null && (
              <span className="muted"> ({(r.kelly * 100).toFixed(1)}% bankroll)</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
