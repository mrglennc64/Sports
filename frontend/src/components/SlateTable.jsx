// Ranked edge "leaderboard" (UX nod to HOF App's leaderboard/trends views).
function edgeGrade(edge) {
  if (edge == null) return { label: "—", cls: "g-none" };
  if (edge >= 0.08) return { label: "A", cls: "g-a" };
  if (edge >= 0.05) return { label: "B", cls: "g-b" };
  if (edge >= 0.03) return { label: "C", cls: "g-c" };
  return { label: "—", cls: "g-none" };
}

const pct = (x) => (x == null ? "—" : `${(x * 100).toFixed(1)}%`);
const odds = (x) => (x == null ? "—" : x > 0 ? `+${x}` : `${x}`);

export default function SlateTable({ rows }) {
  const evaluated = rows.filter((r) => r.status === "ok");
  if (evaluated.length === 0) {
    return <p className="empty">No evaluated props for this date.</p>;
  }
  return (
    <table className="slate">
      <thead>
        <tr>
          <th>Grade</th>
          <th>Pitcher</th>
          <th>Opponent</th>
          <th>Line</th>
          <th>Pick</th>
          <th>Exp. Ks</th>
          <th>Model</th>
          <th>Fair</th>
          <th>Book</th>
          <th>Edge</th>
          <th>Kelly</th>
          <th>Book</th>
        </tr>
      </thead>
      <tbody>
        {evaluated.map((r, i) => {
          const g = edgeGrade(r.edge);
          const sideOdds = r.side === "over" ? r.over_odds : r.under_odds;
          return (
            <tr
              key={i}
              className={
                r.selected ? "carded" : r.bet ? "bet" : r.low_confidence ? "lowconf" : ""
              }
            >
              <td><span className={`grade ${g.cls}`}>{g.label}</span></td>
              <td className="pitcher">
                {r.selected && <span className="tag tag-card">⭐ #{r.card_rank}</span>}
                {r.pitcher}
                {r.bet && !r.selected && <span className="tag tag-bet">BET</span>}
                {r.bet && !r.selected && r.card_excluded && (
                  <span className="tag tag-low" title={r.card_excluded}>off card</span>
                )}
                {r.low_confidence && <span className="tag tag-low">low sample</span>}
              </td>
              <td>{r.opponent}</td>
              <td>{r.line}</td>
              <td className={`side side-${r.side}`}>{r.side?.toUpperCase()}</td>
              <td>{r.expected_ks?.toFixed(2)}</td>
              <td>{pct(r.model_prob)}</td>
              <td>{pct(r.fair_prob)}</td>
              <td>{odds(sideOdds)}</td>
              <td className={r.edge >= 0.03 ? "edge-pos" : "edge-neg"}>
                {r.edge >= 0 ? "+" : ""}
                {pct(r.edge)}
              </td>
              <td>{pct(r.kelly)}</td>
              <td className="book">{r.bookmaker}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
