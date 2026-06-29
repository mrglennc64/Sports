// Turn a per-bet Kelly fraction into an actual dollar stake. The fraction is the
// group-capped Kelly (`kelly_capped`, already scaled by the Kelly slider and the
// correlated-exposure cap), so stake = fraction × bankroll. `round_to` snaps it to
// a whole-dollar increment so the wager blends in as a casual bet instead of an
// obviously-optimised number. Mirrors backend _round_to (half-up, <=0 = no round).
export function dollarStake(kellyFraction, bankroll, roundTo) {
  if (!bankroll || bankroll <= 0 || kellyFraction == null || kellyFraction <= 0)
    return null;
  const raw = kellyFraction * bankroll;
  if (!roundTo || roundTo <= 0) return Math.round(raw * 100) / 100;
  return Math.round(raw / roundTo + 1e-9) * roundTo;
}

// The Kelly fraction actually used for sizing: the group-capped value when present,
// otherwise the raw per-bet Kelly.
export function effectiveKelly(row) {
  return row.kelly_capped != null ? row.kelly_capped : row.kelly;
}

export const fmtMoney = (x) => (x == null ? "—" : `$${x.toFixed(2)}`);
