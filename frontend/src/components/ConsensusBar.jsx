// "You vs the field" scoreboard. Renders only when the sharp check has run and
// matched book lines for this pitcher (row.consensus_line present). Surfaces the
// market consensus you ALREADY pull from ~14 books — how tightly the field agrees
// on the line, and whether your model sits with the field or is an outlier. No
// scraping: this is the the-odds-api wide pull, made visible per card.
export default function ConsensusBar({ row }) {
  if (row?.consensus_line == null || row?.consensus_n_books == null) return null;

  const n = row.consensus_n_books;
  const atLine = row.consensus_at_line;
  const gap = row.consensus_k_gap;
  const outlier = !!row.sharp_vetoed;
  const range =
    row.consensus_line_low != null && row.consensus_line_high != null
      ? row.consensus_line_low === row.consensus_line_high
        ? `${row.consensus_line_low}`
        : `${row.consensus_line_low}–${row.consensus_line_high}`
      : null;

  return (
    <div className={`consensus ${outlier ? "outlier" : "withfield"}`} title={row.sharp_note}>
      <div className="consensus-head">
        <span className="consensus-title">📊 vs the field</span>
        <span className={`consensus-verdict ${outlier ? "bad" : "good"}`}>
          {outlier ? "⚠️ OUTLIER" : "✓ WITH FIELD"}
        </span>
      </div>
      <div className="consensus-stats">
        <span>
          <b>{atLine}</b>/{n} books at {row.consensus_line}
          {range && range !== `${row.consensus_line}` ? ` (range ${range})` : ""}
        </span>
        <span>
          model {row.expected_ks?.toFixed(1)} ·{" "}
          {gap >= 0 ? "+" : ""}
          {gap?.toFixed?.(1) ?? gap} Ks vs consensus
        </span>
      </div>
    </div>
  );
}
