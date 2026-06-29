"""Async daily pipeline using the v2 ensemble + bridge — the unified model.

Mirrors :mod:`app.pipeline`, but expected Ks come from the ensemble
(:mod:`app.model.projection`) fed through the Poisson / de-vig / Kelly / insight
bridge (:mod:`app.model.bridge`), using the async MLB Stats data layer
(:mod:`app.data.assemble`) plus the optional umpire and Baseball Savant inputs.

This is what the API's v2 routes serve. The original sync ``app.pipeline``
(season K/9 x multipliers) is left intact for comparison / fallback.
"""

from __future__ import annotations

from app.config import Settings
from app.config import settings as default_settings
from app.data.assemble import build_projection_inputs
from app.data.client import StatsApiClient
from app.data.mlb_stats import ProbableStart, fetch_probable_starts
from app.data.names import names_match
from app.data.odds import OddsProvider, PropLine, get_provider
from app.data.park import park_factor
from app.data.savant import SavantClient
from app.data.umpires import UmpireTable, load_umpire_table
from app.model.bridge import predict_with_ensemble
from app.model.divergence import market_divergence
from app.model.inputs import ProjectionInputs
from app.model.risk import cap_correlated
from app.model.selection import input_completeness, select_card


def _apply_group_cap(priced: list[dict], group_cap: float) -> None:
    """Annotate priced rows with a correlated-exposure cap (app.model.risk).

    Groups rows by pitcher (every leg on one arm is the same underlying outcome)
    and adds, in place: ``kelly_capped`` (stake after the group cap), ``group_capped``
    (was it scaled down), and ``kelly_group_total`` (summed raw kelly on that arm).
    Strictly additive — the original ``kelly`` is left as-is so nothing downstream
    that reads it changes; consumers opt into ``kelly_capped`` when they want the
    correlation-aware stake. Rows without a kelly (no bet) get ``kelly_capped`` 0.
    """
    keys = [str(r.get("pitcher_id") or r.get("pitcher") or i) for i, r in enumerate(priced)]
    kellys = [float(r.get("kelly") or 0.0) for r in priced]
    for row, leg in zip(priced, cap_correlated(keys, kellys, group_cap)):
        row["kelly_capped"] = round(leg.kelly_capped, 4)
        row["group_capped"] = leg.capped
        row["kelly_group_total"] = round(leg.group_total, 4)


def _load_umpires(settings: Settings) -> UmpireTable | None:
    """Load the umpire K-tendency table if one is configured and present."""
    table = load_umpire_table(settings.umpire_data_path)
    return table or None


async def predict_pitcher_ensemble(
    pitcher: str,
    line: float,
    date: str,
    over_odds: float | None = None,
    under_odds: float | None = None,
    *,
    client: StatsApiClient | None = None,
    umpire_table: UmpireTable | None = None,
    savant: SavantClient | None = None,
    settings: Settings = default_settings,
) -> dict:
    """Single-pitcher prediction via the ensemble bridge (the /v2/predict route).

    Finds the pitcher among ``date``'s probable starts (for the real opponent +
    venue), assembles point-of-game inputs, runs the ensemble -> Poisson -> edge
    path, and returns the bridge dict plus opponent / venue / park context.
    Raises ``LookupError`` if the pitcher isn't starting that day.
    """
    owns = client is None
    client = client or StatsApiClient()
    try:
        starts = await fetch_probable_starts(client, date)
        start = next(
            (s for s in starts if names_match(pitcher, s.pitcher_name)), None
        )
        if start is None:
            raise LookupError(f"No probable start found for {pitcher!r} on {date}")

        inputs = await build_projection_inputs(
            client, start, date, umpire_table=umpire_table, savant=savant
        )
        park = park_factor(start.venue_name)
        out = predict_with_ensemble(
            inputs,
            line=line,
            over_odds=over_odds,
            under_odds=under_odds,
            park=park,
            settings=settings,
        )
        out["opponent"] = start.opponent_team_name
        out["venue"] = start.venue_name
        out["park"] = park
        out["game_pk"] = start.game_pk
        out["pitcher_id"] = start.pitcher_id  # needed to settle a logged leg
        out["date"] = date
        return out
    finally:
        if owns:
            await client.aclose()


def _collect_props(provider: OddsProvider) -> list[PropLine]:
    props: list[PropLine] = []
    for event in provider.list_events():
        try:
            props.extend(provider.get_strikeout_props(event.event_id))
        except Exception:  # one bad event shouldn't sink the slate
            continue
    return props


def _match_prop(start: ProbableStart, props: list[PropLine]) -> PropLine | None:
    for p in props:
        if names_match(start.pitcher_name, p.pitcher_name):
            return p
    return None


def _collect_quote_lines(provider: OddsProvider) -> dict[str, list[float]]:
    """Every book's strikeout LINE per pitcher, across all events (the wide pull).

    Used only by the opt-in sharp check: the median of these lines is the market
    consensus the divergence guard vetoes outliers against. Costs ~3x the props
    pull (wide regions), so this is never called on the daily cron path.
    """
    out: dict[str, list[float]] = {}
    for event in provider.list_events():
        try:
            quotes = provider.get_strikeout_quotes(event.event_id)
        except Exception:  # one bad event shouldn't sink the sharp check
            continue
        for pitcher, books in quotes.items():
            out.setdefault(pitcher, []).extend(
                b.line for b in books if b.line is not None
            )
    return out


def _match_quote_lines(pitcher_name: str, lines_by_pitcher: dict[str, list[float]]) -> list[float]:
    for name, lines in lines_by_pitcher.items():
        if names_match(pitcher_name, name):
            return lines
    return []


def _completeness(inputs: ProjectionInputs, settings: Settings) -> float:
    """How fully-supported this projection is — feeds the card completeness gate."""
    form = inputs.pitcher_form
    return input_completeness(
        starts_ok=len(form.recent_start_ks) >= settings.min_recent_starts,
        has_umpire=inputs.umpire is not None,
        has_whiff=form.csw_pct is not None or form.swinging_strike_pct is not None,
        has_pitch_mix=inputs.pitch_mix is not None and bool(inputs.pitch_mix.pitches),
    )


async def build_slate_ensemble(
    date: str,
    *,
    client: StatsApiClient | None = None,
    provider: OddsProvider | None = None,
    umpire_table: UmpireTable | None = None,
    savant: SavantClient | None = None,
    settings: Settings = default_settings,
    max_bets: int = 4,
    max_per_game: int = 1,
    select_min_edge: float = 0.05,
    select_max_edge: float = 0.20,
    min_completeness: float = 0.5,
    sharp_check: bool = False,
    divergence_threshold: float = 1.25,
) -> dict:
    """Ranked +EV pitcher-strikeout edges for ``date`` via the ensemble bridge.

    Every probable start is projected; starts matched to a sportsbook prop also
    get a de-vigged edge + Kelly + verdict. Rows are returned with the priced
    edges first (highest edge first), then the projection-only rows.

    A small **bet card** is also selected (:func:`app.model.selection.select_card`):
    the top ``max_bets`` priced bets inside the ``[select_min_edge,
    select_max_edge]`` band, diversified to ``max_per_game`` per game and gated by
    input ``min_completeness``. Card rows carry ``selected=True`` + ``card_rank``;
    other bets carry ``card_excluded`` with the reason. This is the "bet these N,
    not all 20" view for a small bankroll.
    """
    owns = client is None
    client = client or StatsApiClient()
    provider = provider or get_provider(
        settings.odds_provider,
        settings.odds_api_key_theoddsapi,
        settings.odds_api_key_io,
    )
    try:
        starts = await fetch_probable_starts(client, date)
        props = _collect_props(provider)

        priced: list[dict] = []
        unpriced: list[dict] = []
        for start in starts:
            # Skip prediction if probable pitcher not announced (show as TBD in frontend)
            if not start.pitcher_id or start.pitcher_name == "TBD":
                # Return minimal info to show game in UI with TBD status
                tbd_out = {
                    "pitcher": "TBD",
                    "opponent": start.opponent_team_name,
                    "venue": start.venue_name,
                    "game_pk": start.game_pk,
                    "status": "probable_not_announced",
                    "message": "Probable pitcher not yet announced"
                }
                unpriced.append(tbd_out)
                continue

            inputs = await build_projection_inputs(
                client, start, date, umpire_table=umpire_table, savant=savant
            )
            park = park_factor(start.venue_name)
            prop = _match_prop(start, props)
            line = prop.line if prop else 0.5  # placeholder; only used when priced
            out = predict_with_ensemble(
                inputs,
                line=line,
                over_odds=prop.over_odds if prop else None,
                under_odds=prop.under_odds if prop else None,
                park=park,
                settings=settings,
            )
            out["opponent"] = start.opponent_team_name
            out["venue"] = start.venue_name
            out["park"] = park
            out["game_pk"] = start.game_pk
            out["pitcher_id"] = start.pitcher_id  # correlation key for the group cap
            out["completeness"] = round(_completeness(inputs, settings), 3)
            if prop is not None:
                out["bookmaker"] = prop.bookmaker
                out["status"] = "ok"
                priced.append(out)
            else:
                # No prop: drop the placeholder-line betting fields, keep projection.
                for k in ("line", "prob_over", "prob_under", "fair_over_odds", "fair_under_odds"):
                    out.pop(k, None)
                out["status"] = "no_prop"
                unpriced.append(out)

        # Cap correlated exposure (same pitcher across books/lines/re-pulls) before
        # ranking + card selection. Additive: adds kelly_capped, leaves kelly intact.
        _apply_group_cap(priced, settings.kelly_group_cap)

        # Opt-in sharp check: veto edges where the model is a market outlier. Costs
        # the wide (~3x) quote pull, so it only runs when explicitly requested.
        sharp_vetoed = 0
        if sharp_check:
            lines_by_pitcher = _collect_quote_lines(provider)
            for row in priced:
                lines = _match_quote_lines(row.get("pitcher", ""), lines_by_pitcher)
                proj = row.get("expected_ks")
                if proj is None or not lines:
                    continue
                view = market_divergence(proj, lines, threshold=divergence_threshold)
                if view is None:
                    continue
                row["consensus_line"] = view.consensus_line
                row["consensus_k_gap"] = view.k_gap
                row["consensus_n_books"] = view.n_books
                row["consensus_at_line"] = view.n_at_consensus
                row["consensus_line_low"] = view.line_low
                row["consensus_line_high"] = view.line_high
                row["consensus_agreement_pct"] = view.agreement_pct
                row["sharp_vetoed"] = view.diverges
                row["sharp_note"] = view.reason
                if view.diverges:
                    sharp_vetoed += 1

        priced.sort(key=lambda r: r.get("edge", float("-inf")), reverse=True)
        # A vetoed edge (model far from market consensus) is kept in the rows for
        # transparency but barred from the bet card — it's likely a model error.
        card_candidates = [r for r in priced if not r.get("sharp_vetoed")]
        card = select_card(
            card_candidates,
            max_bets=max_bets,
            max_per_game=max_per_game,
            min_edge=select_min_edge,
            max_edge=select_max_edge,
            min_completeness=min_completeness,
        )
        rows = priced + unpriced
        result = {
            "date": date,
            "count": len(rows),
            "evaluated": len(priced),
            "bets": sum(1 for r in priced if r.get("bet")),
            "skipped": len(unpriced),
            "card_size": len(card),
            "card": card,
            "rows": rows,
        }
        if sharp_check:
            result["sharp_check"] = True
            result["sharp_vetoed"] = sharp_vetoed
        return result
    finally:
        if owns:
            await client.aclose()
