"""Daily-slate pipeline: stats + odds -> expected Ks -> probabilities -> edges.

Ties the data clients and model together. Pure orchestration; all maths lives in
``app.model`` and all I/O in ``app.data`` so this stays testable with fakes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings, settings as default_settings
from app.data.cache import TTLCache
from app.data.mlb import MlbClient, Start
from app.data.names import names_match
from app.data.odds import OddsProvider, PropLine, get_provider
from app.data.park import park_factor
from app.model import poisson
from app.model.edge import evaluate_prop, prob_to_american
from app.model.expected_ks import PitcherInputs, expected_strikeouts
from app.model.insight import build_insight

# Minimum starter sample to trust a projection enough to flag a bet.
MIN_STARTS = 5
MIN_INNINGS = 25.0


@dataclass
class EdgeRow:
    date: str
    pitcher: str
    opponent: str
    venue: str
    status: str                      # "ok" | "no_prop" | "no_stats"
    pitcher_id: int | None = None
    expected_ks: float | None = None
    line: float | None = None
    bookmaker: str | None = None
    side: str | None = None
    model_prob: float | None = None
    fair_prob: float | None = None
    over_odds: float | None = None
    under_odds: float | None = None
    edge: float | None = None
    kelly: float | None = None
    bet: bool = False
    low_confidence: bool = False     # small sample -> shown but never flagged BET
    # decision/insight layer (human-readable verdict)
    recommendation: str | None = None   # "Strong Play" | "Lean" | "No Bet" | "Pass"
    confidence: str | None = None       # "High" | "Medium" | "Low"
    stake_label: str | None = None      # "—" | "Small" | "Medium" | "Large"
    signal: str | None = None           # "strong" | "lean" | "avoid"
    reasons: list[str] = field(default_factory=list)
    # context for transparency
    k_per_9: float | None = None
    innings_per_start: float | None = None
    opp_k_rate: float | None = None
    park: float | None = None


@dataclass
class Slate:
    date: str
    rows: list[EdgeRow]
    skipped: int = 0
    requests_note: str = ""


def _collect_props(provider: OddsProvider) -> list[PropLine]:
    """Pull strikeout props for every MLB event and flatten to one list."""
    props: list[PropLine] = []
    for event in provider.list_events():
        try:
            props.extend(provider.get_strikeout_props(event.event_id))
        except Exception:  # one bad event shouldn't sink the whole slate
            continue
    return props


def _match_prop(start: Start, props: list[PropLine]) -> PropLine | None:
    for p in props:
        if names_match(start.pitcher_name, p.pitcher_name):
            return p
    return None


def predict_pitcher(
    pitcher: str,
    line: float,
    date: str,
    over_odds: float | None = None,
    under_odds: float | None = None,
    mlb: MlbClient | None = None,
    settings: Settings = default_settings,
) -> dict:
    """Single-pitcher manual prediction (the /predict route).

    Finds the pitcher among ``date``'s probable starts (so we get the real opponent
    and venue), computes expected Ks + Poisson over/under probabilities and fair
    odds. If book over/under odds are supplied, also returns de-vigged edge + Kelly.
    Raises LookupError if the pitcher isn't starting that day or has no stats.
    """
    mlb = mlb or MlbClient()
    start = next(
        (s for s in mlb.get_starts(date) if names_match(pitcher, s.pitcher_name)), None
    )
    if start is None:
        raise LookupError(f"No probable start found for {pitcher!r} on {date}")

    season = mlb.get_pitcher_season(start.pitcher_id)
    opp_k = mlb.get_team_k_rate(start.opponent_team_id)
    if season is None or opp_k is None:
        raise LookupError(f"No season stats available for {pitcher!r} / opponent")

    pf = park_factor(start.venue_name)
    lam = expected_strikeouts(
        PitcherInputs(
            name=start.pitcher_name,
            k_per_9=season.k_per_9,
            innings_per_start=season.innings_per_start,
            opp_k_rate=opp_k,
            park_factor=pf,
        )
    )
    p_over = poisson.prob_over(lam, line)
    p_under = poisson.prob_under(lam, line)

    result = {
        "pitcher": start.pitcher_name,
        "opponent": start.opponent_team_name,
        "venue": start.venue_name,
        "line": line,
        "expected_ks": round(lam, 3),
        "prob_over": round(p_over, 4),
        "prob_under": round(p_under, 4),
        "fair_over_odds": round(prob_to_american(p_over), 1) if p_over > 0 else None,
        "fair_under_odds": round(prob_to_american(p_under), 1) if p_under > 0 else None,
        "k_per_9": season.k_per_9,
        "innings_per_start": round(season.innings_per_start, 2),
        "opp_k_rate": round(opp_k, 4),
        "park": pf,
    }

    if over_odds is not None and under_odds is not None:
        best = evaluate_prop(
            line=line,
            over_odds=over_odds,
            under_odds=under_odds,
            model_prob_over=p_over,
            model_prob_under=p_under,
            kelly_fraction_=settings.kelly_fraction,
            kelly_cap=settings.kelly_cap,
            devig_method=settings.devig_method,
        )
        result.update(
            {
                "side": best.side,
                "model_prob": round(best.model_prob, 4),
                "fair_prob": round(best.fair_prob, 4),
                "edge": round(best.edge, 4),
                "kelly": round(best.kelly, 4),
                "bet": best.edge >= settings.min_edge and best.kelly > 0,
            }
        )
    return result


def build_slate(
    date: str,
    mlb: MlbClient | None = None,
    provider: OddsProvider | None = None,
    settings: Settings = default_settings,
) -> Slate:
    mlb = mlb or MlbClient()
    provider = provider or get_provider(
        settings.odds_provider,
        settings.odds_api_key_theoddsapi,
        settings.odds_api_key_io,
    )

    starts = mlb.get_starts(date)
    props = _collect_props(provider)
    team_k_cache = TTLCache()

    rows: list[EdgeRow] = []
    for start in starts:
        prop = _match_prop(start, props)
        if prop is None:
            rows.append(EdgeRow(date, start.pitcher_name, start.opponent_team_name,
                                start.venue_name, status="no_prop"))
            continue

        season = mlb.get_pitcher_season(start.pitcher_id)
        opp_k = team_k_cache.get(start.opponent_team_id)
        if opp_k is None:
            opp_k = mlb.get_team_k_rate(start.opponent_team_id)
            if opp_k is not None:
                team_k_cache.set(start.opponent_team_id, opp_k)

        if season is None or opp_k is None:
            rows.append(EdgeRow(date, start.pitcher_name, start.opponent_team_name,
                                start.venue_name, status="no_stats",
                                line=prop.line, bookmaker=prop.bookmaker))
            continue

        pf = park_factor(start.venue_name)
        # Trust the projection only with enough starter sample; otherwise show it but
        # never flag a bet (a 2-start line is mostly noise).
        low_conf = season.games_started < MIN_STARTS or season.innings_pitched < MIN_INNINGS
        lam = expected_strikeouts(
            PitcherInputs(
                name=start.pitcher_name,
                k_per_9=season.k_per_9,
                innings_per_start=season.innings_per_start,
                opp_k_rate=opp_k,
                park_factor=pf,
            )
        )
        p_over = poisson.prob_over(lam, prop.line)
        p_under = poisson.prob_under(lam, prop.line)
        best = evaluate_prop(
            line=prop.line,
            over_odds=prop.over_odds,
            under_odds=prop.under_odds,
            model_prob_over=p_over,
            model_prob_under=p_under,
            kelly_fraction_=settings.kelly_fraction,
            kelly_cap=settings.kelly_cap,
            devig_method=settings.devig_method,
        )
        insight = build_insight(
            side=best.side,
            edge=best.edge,
            kelly=best.kelly,
            low_confidence=low_conf,
            opp_k_rate=opp_k,
            park=pf,
            expected_ks=lam,
            line=prop.line,
            min_edge=settings.min_edge,
        )
        rows.append(
            EdgeRow(
                date=date,
                pitcher=start.pitcher_name,
                opponent=start.opponent_team_name,
                venue=start.venue_name,
                status="ok",
                pitcher_id=start.pitcher_id,
                recommendation=insight.recommendation,
                confidence=insight.confidence,
                stake_label=insight.stake_label,
                signal=insight.signal,
                reasons=insight.reasons,
                expected_ks=round(lam, 3),
                line=prop.line,
                bookmaker=prop.bookmaker,
                side=best.side,
                model_prob=round(best.model_prob, 4),
                fair_prob=round(best.fair_prob, 4),
                over_odds=prop.over_odds,
                under_odds=prop.under_odds,
                edge=round(best.edge, 4),
                kelly=round(best.kelly, 4),
                bet=best.edge >= settings.min_edge and best.kelly > 0 and not low_conf,
                low_confidence=low_conf,
                k_per_9=season.k_per_9,
                innings_per_start=round(season.innings_per_start, 2),
                opp_k_rate=round(opp_k, 4),
                park=pf,
            )
        )

    ok_rows = [r for r in rows if r.status == "ok"]
    ok_rows.sort(key=lambda r: r.edge, reverse=True)
    other = [r for r in rows if r.status != "ok"]
    return Slate(date=date, rows=ok_rows + other, skipped=len(other))
