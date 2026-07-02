import { Link } from "react-router-dom";

const FEATURES = [
  {
    icon: "🎯",
    title: "Quant pricing engine",
    body: "Real MLB data → expected strikeouts → over/under probability for every probable starter. No guessing, no placeholder stats.",
  },
  {
    icon: "📈",
    title: "True edge, vig removed",
    body: "Compares the model against de-vigged sportsbook odds (Shin's method) so the edge you see isn't just the bookmaker's margin.",
  },
  {
    icon: "🟢",
    title: "Decisions, not math",
    body: "Simple mode turns probabilities into Strong Play / Lean / No Bet with confidence and a suggested stake. Pro mode shows the full numbers.",
  },
  {
    icon: "💰",
    title: "Disciplined staking",
    body: "Quarter-Kelly bankroll sizing, capped — so a flagged edge maps to a sane bet size, never a reckless one.",
  },
  {
    icon: "🧪",
    title: "Provable, not hand-wavy",
    body: "Every prediction is logged and settled against actual results: hit rate, ROI and closing-line value. Edge you can audit.",
  },
  {
    icon: "⚾",
    title: "Built for starters' Ks",
    body: "Opponent strikeout rate, park factors and innings-per-start projections — focused on pitcher strikeout props, done properly.",
  },
];

export default function Landing() {
  return (
    <div className="landing">
      <section className="hero">
        <span className="badge">MLB · Pitcher Strikeouts</span>
        <h1>Price strikeout props like a sportsbook trader.</h1>
        <p className="lede">
          A quantitative edge engine that estimates the true probability of a pitcher's
          strikeout total and flags where the betting market is mispriced — then sizes the
          bet for you.
        </p>
        <div className="cta-row">
          <Link to="/" className="cta">Launch the Engine →</Link>
          <Link to="/research" className="cta ghost">All-Sports Edge Research</Link>
          <a
            className="cta ghost"
            href="https://github.com/mrglennc64/strike"
            target="_blank"
            rel="noreferrer"
          >
            View source
          </a>
        </div>
        <p className="disclaimer">
          Analytics tool, not betting advice. Edges are unproven until validated by logged
          closing-line value.
        </p>
      </section>

      <section className="features">
        {FEATURES.map((f) => (
          <div className="feature" key={f.title}>
            <div className="feature-icon">{f.icon}</div>
            <h3>{f.title}</h3>
            <p>{f.body}</p>
          </div>
        ))}
      </section>

      <section className="how">
        <h2>How it works</h2>
        <ol className="steps">
          <li><b>Pull</b> — probable starters, season K/9, opponent K%, park factors, live K-prop odds.</li>
          <li><b>Model</b> — expected strikeouts → Poisson over/under probability for the line.</li>
          <li><b>Compare</b> — against de-vigged book odds to measure real edge.</li>
          <li><b>Decide</b> — Strong Play / Lean / No Bet, with a Kelly-sized stake.</li>
          <li><b>Prove</b> — log every pick and settle it: hit rate, ROI, CLV.</li>
        </ol>
        <div className="cta-row center">
          <Link to="/" className="cta">Open today's slate →</Link>
        </div>
      </section>

      <footer className="landing-footer">
        Strikeout Edge · quantitative sports pricing, not gambling advice.
      </footer>
    </div>
  );
}
