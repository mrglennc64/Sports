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


async def build_slate_ensemble(
    date: str,
    *,
    client: StatsApiClient | None = None,
    provider: OddsProvider | None = None,
    umpire_table: UmpireTable | None = None,
    savant: SavantClient | None = None,
    settings: Settings = default_settings,
) -> dict:
    """Ranked +EV pitcher-strikeout edges for ``date`` via the ensemble bridge.

    Every probable start is projected; starts matched to a sportsbook prop also
    get a de-vigged edge + Kelly + verdict. Rows are returned with the priced
    edges first (highest edge first), then the projection-only rows.
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

        priced.sort(key=lambda r: r.get("edge", float("-inf")), reverse=True)
        rows = priced + unpriced
        return {
            "date": date,
            "count": len(rows),
            "evaluated": len(priced),
            "bets": sum(1 for r in priced if r.get("bet")),
            "rows": rows,
        }
    finally:
        if owns:
            await client.aclose()
