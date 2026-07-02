// Simple ("consumer") mode: hide the math, show a decision per HOF-style feedback.
import { dollarStake, effectiveKelly, fmtMoney } from "../stake.js";
import ConsensusBar from "./ConsensusBar.jsx";

const SIGNAL_RANK = { strong: 0, lean: 1, avoid: 2 };
const SIGNAL_EMOJI = { strong: "🟢", lean: "🟡", avoid: "🔴" };

export default function SimpleCards({ rows, bankroll = 0, stakeRound = 0 }) {
  const cards = rows
    .filter((r) => r.status === "ok")
    .sort(
      (a, b) =>
        // carded plays first, then by signal strength
        (a.selected ? 0 : 1) - (b.selected ? 0 : 1) ||
        (a.card_rank ?? 99) - (b.card_rank ?? 99) ||
        (SIGNAL_RANK[a.signal] ?? 3) - (SIGNAL_RANK[b.signal] ?? 3)
    );

  if (cards.length === 0) return <p className="empty">No props to show.</p>;

  return (
    <div className="cards">
      {cards.map((r, i) => {
        const stake =
          r.selected && !r.sharp_vetoed
            ? dollarStake(effectiveKelly(r), bankroll, stakeRound)
            : null;
        return (
        <div key={`${r.pitcher}-${r.side}-${r.line}`} className={`card sig-${r.signal}${r.selected ? " carded" : ""}${r.sharp_vetoed ? " vetoed" : ""}`}>
          <div className="card-top">
            <span className="card-signal">{SIGNAL_EMOJI[r.signal]} {r.recommendation}</span>
            {r.selected ? (
              <span className="card-badge">⭐ Card #{r.card_rank}</span>
            ) : (
              <span className="card-conf">{r.confidence} confidence</span>
            )}
          </div>
          <div className="card-pick">
            {r.pitcher} <b>{r.side?.toUpperCase()} {r.line} Ks</b>
          </div>
          <div className="card-vs">vs {r.opponent}</div>
          {typeof r.model_prob === "number" && (
            <div className="card-winprob">
              Model win prob <b>{Math.round(r.model_prob * 100)}%</b>
              <em className="card-loses">
                {" "}· loses ~{Math.round((1 - r.model_prob) * 100)}% of the time
              </em>
            </div>
          )}
          {stake != null && (
            <div className="card-stake">
              💵 Stake <b>{fmtMoney(stake)}</b>
              {stakeRound > 0 ? ` · rounded to $${stakeRound}` : ""}
            </div>
          )}
          <ConsensusBar row={r} />
          <ul className="card-reasons">
            {(r.reasons ?? []).slice(0, 3).map((reason, j) => (
              <li key={j}>{reason}</li>
            ))}
          </ul>
        </div>
        );
      })}
    </div>
  );
}
