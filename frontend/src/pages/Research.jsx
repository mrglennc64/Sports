import { Link } from "react-router-dom";

// Snapshot of the All-Sports Edge Finder research (internal project, 2026-06-11).
// Source of truth: allsports repo — docs/research/ + `python -m edgefinder`.
const RANKINGS = [
  {
    rank: 1, sport: "MLB strikeout props", score: "7.50",
    verdict: "The baseline. Best public data in sports (Statcast), every US book, daily slates. Weakness is our own calibration — unproven until the backtest says otherwise.",
  },
  {
    rank: 2, sport: "Tennis", score: "6.75",
    verdict: "The recommended next sport. Free Sackmann data back to 1968, proven Elo + serve/return templates, soft feed-priced Challenger/ITF lines. Low stake capacity is the catch.",
  },
  {
    rank: 3, sport: "Horse racing", score: "5.85",
    verdict: "The only market that never bans winners; pari-mutuel pools absorb size. Costs: paid per-card data (Equibase) and 15–25% takeout vs rebated syndicates. Benter's blueprint still works.",
  },
  {
    rank: 4, sport: "Cricket", score: "5.55",
    verdict: "Best free granular dataset anywhere (Cricsheet, 22k matches ball-by-ball) — and the worst US access. Free umpire LBW-tendency tables are an unowned angle.",
  },
  {
    rank: 5, sport: "Table tennis", score: "5.10",
    verdict: "Huge-handle single-feed 24/7 market a simple Elo can dent — but winners get cut to $5–$50 and documented match-fixing poisons the results data. Sandbox only.",
  },
  {
    rank: 6, sport: "Bowling", score: "5.05",
    verdict: "Real emerging data edge (published oil patterns, LaneTalk, Specto tracking) against one book (BetRivers, ~12 states) that isn't modeling pattern fit. Hobby-sized market.",
  },
  {
    rank: 7, sport: "Track & field", score: "4.80",
    verdict: "Highly modelable, effectively unbettable: US books price it ~2 weeks a year. Re-score before each Worlds and LA 2028.",
  },
  {
    rank: 8, sport: "Padel / pickleball", score: "4.10",
    verdict: "Watch list. One US book (FanDuel) for pickleball, zero for padel, official data locked at Genius Sports. $225M of Apollo money says re-score annually.",
  },
];

const INSIGHTS = [
  {
    icon: "🏦",
    title: "Don't beat the house — understand it",
    body: "The balanced book is a myth: sharp books move lines on WHO bets, retail books manage risk by limiting winners. Individual lines are wrong all the time — early, niche, props. Low limits are the book telling you its own line is soft.",
  },
  {
    icon: "📡",
    title: "Niche lines come from one feed",
    body: "Cricket, table tennis and low-tier tennis are priced by a Sportradar/Genius duopoly and replicated across dozens of books. One flawed model, everywhere at once — that's what an exploitable niche looks like. The toll: low limits, short account life.",
  },
  {
    icon: "📏",
    title: "CLV is the only honest scoreboard",
    body: "Beating the sharp closing line proves edge before results do — it's also exactly what books track to find and limit winners. The real objective is edge × limit × account lifetime, not edge alone.",
  },
  {
    icon: "🐎",
    title: "Pari-mutuel never bans winners",
    body: "Horse pools are the structural outlier: you beat the crowd, not the house, and the track happily takes your action forever. The price is 15–25% takeout and paid data — Benter's conditional-logit + odds-blend is the documented path.",
  },
  {
    icon: "🧑‍⚖️",
    title: "Officials are a real, partly unpriced signal",
    body: "Flat MLB umpire effects are commoditized; umpire × pitcher-archetype interactions are not — that study is running in this engine now. Most exploitable overall: cricket umpire LBW tendencies, buildable free from Cricsheet, published by no one.",
  },
  {
    icon: "🤖",
    title: "A daily agent watches the data",
    body: "A scheduled watcher checks Sackmann's tennis repos, the Hugging Face Hub and Cricsheet for new data every morning and writes a report — so the research stays current without anyone remembering to look.",
  },
];

export default function Research() {
  return (
    <div className="landing">
      <section className="hero">
        <span className="badge">Internal · All-Sports Edge Research</span>
        <h1>Which sport gives us the biggest edge?</h1>
        <p className="lede">
          Eight sports scored on data availability, line softness, market access,
          modelability, stake capacity and live-data speed — each score backed by a
          sourced research profile. Verdict: tennis is next; horse racing is the
          funded-track alternative.
        </p>
        <div className="cta-row">
          <Link to="/" className="cta ghost">← Back to Strikeout Edge</Link>
        </div>
      </section>

      <section className="how">
        <h2>The ranking</h2>
        <table className="slate">
          <thead>
            <tr>
              <th>#</th>
              <th>Sport</th>
              <th>Score</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {RANKINGS.map((r) => (
              <tr key={r.sport}>
                <td>{r.rank}</td>
                <td className="pitcher">{r.sport}</td>
                <td>{r.score}</td>
                <td>{r.verdict}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="disclaimer">
          Weighted rubric: data 25% · line softness 25% · market access 20% ·
          modelability 15% · stake capacity 10% · live speed 5%. Full profiles with
          dataset disclosure tables and sources live in the internal allsports repo.
        </p>
      </section>

      <section className="features">
        {INSIGHTS.map((f) => (
          <div className="feature" key={f.title}>
            <div className="feature-icon">{f.icon}</div>
            <h3>{f.title}</h3>
            <p>{f.body}</p>
          </div>
        ))}
      </section>

      <footer className="landing-footer">
        Internal research snapshot · regenerate with <code>python -m edgefinder</code> ·
        not betting advice.
      </footer>
    </div>
  );
}
