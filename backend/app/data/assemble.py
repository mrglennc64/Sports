"""Orchestrate the MLB Stats fetchers into a full ``ProjectionInputs``.

This wires together the parsers in :mod:`app.data.mlb_stats` for one probable
start. ``umpire`` is filled from the assigned home-plate umpire when an umpire
K-tendency table is supplied (see :mod:`app.data.umpires`). When a Baseball
Savant client is supplied (see :mod:`app.data.savant`), the two Statcast-only
factors are filled too: the pitcher's swinging-strike% / CSW% and the
``pitch_mix`` matchup vs the opponent. Without it those stay ``None`` and the
model degrades to neutral, so the default behaviour is unchanged.
"""

from __future__ import annotations

from datetime import date

from app.data.client import StatsApiClient
from app.data.mlb_stats import (
    ProbableStart,
    fetch_lineup_strength,
    fetch_opponent_k_profile,
    fetch_pitcher_form,
    fetch_pitcher_workload,
    fetch_probable_starts,
)
from app.data.savant import (
    SavantClient,
    fetch_pitch_mix_matchup,
    fetch_pitcher_whiff_csw,
)
from app.data.umpires import UmpireTable, fetch_umpire_profile
from app.model.inputs import ProjectionInputs


def _season_of(on_date: str) -> int:
    return date.fromisoformat(on_date).year


async def _fetch_team_abbr(client: StatsApiClient, team_id: int) -> str | None:
    """Savant team abbreviation (e.g. 'BOS') for an MLB team id, or None."""
    try:
        payload = await client.get_json(f"/api/v1/teams/{team_id}")
    except Exception:
        return None
    teams = payload.get("teams") or []
    if not teams:
        return None
    return teams[0].get("abbreviation")


async def build_projection_inputs(
    client: StatsApiClient,
    start: ProbableStart,
    on_date: str,
    season: int | None = None,
    umpire_table: UmpireTable | None = None,
    savant: SavantClient | None = None,
) -> ProjectionInputs:
    """Assemble a full ``ProjectionInputs`` for one probable start.

    When ``umpire_table`` is supplied, the assigned home-plate umpire's K
    tendency is looked up and fed into the projection; otherwise ``umpire``
    stays ``None`` (neutral).

    When ``savant`` (a :class:`app.data.savant.SavantClient`) is supplied, the
    pitcher's ``swinging_strike_pct`` / ``csw_pct`` and the ``pitch_mix``
    matchup vs the opponent are filled from Baseball Savant. Without it those
    stay ``None`` (neutral), preserving the default behaviour.
    """
    season = season or _season_of(on_date)

    pitcher_form = await fetch_pitcher_form(
        client, start.pitcher_id, start.throws, season
    )
    workload, bullpen = await fetch_pitcher_workload(
        client, start.pitcher_id, season, today=date.fromisoformat(on_date)
    )

    # Tonight's actual nine (if posted) drives the starting-lineup K%. The
    # opponent is home exactly when the pitcher's team is NOT (``start.is_home``
    # is true when the *pitcher* is home), so the flag is inverted.
    lineup = await fetch_lineup_strength(
        client, start.game_pk, opponent_is_home=not start.is_home, season=season,
        pitcher_hand=start.throws,
    )
    lineup_k_pct = lineup.projected_lineup_k_pct if lineup else None

    opponent = await fetch_opponent_k_profile(
        client,
        start.opponent_team_id,
        season,
        today=on_date,
        lineup_k_pct=lineup_k_pct,
    )

    # No lineup posted yet: fall back to the opponent's recent team-level rate.
    if lineup is None:
        from app.model.inputs import LineupStrength

        lineup = LineupStrength(
            projected_lineup_k_pct=opponent.k_pct_starting_lineup,
            high_k_hitters_resting=0,
        )

    # Assigned home-plate umpire's K tendency (if a table was supplied).
    umpire = None
    if umpire_table:
        umpire = await fetch_umpire_profile(client, start.game_pk, umpire_table)

    # Baseball Savant: the two Statcast-only factors (filled only if a client
    # was supplied). Each fetcher degrades to neutral on missing data.
    pitch_mix = None
    if savant is not None:
        swstr, csw = await fetch_pitcher_whiff_csw(savant, start.pitcher_id, season)
        pitcher_form = pitcher_form.model_copy(
            update={"swinging_strike_pct": swstr, "csw_pct": csw}
        )
        opp_abbr = await _fetch_team_abbr(client, start.opponent_team_id)
        if opp_abbr:
            pitch_mix = await fetch_pitch_mix_matchup(
                savant, start.pitcher_id, opp_abbr, season
            )

    return ProjectionInputs(
        pitcher_name=start.pitcher_name,
        pitcher_id=start.pitcher_id,
        opponent=opponent,
        pitcher_form=pitcher_form,
        workload=workload,
        lineup=lineup,
        umpire=umpire,
        pitch_mix=pitch_mix,
        bullpen=bullpen,
    )


async def build_all_for_date(
    client: StatsApiClient,
    on_date: str,
    season: int | None = None,
    umpire_table: UmpireTable | None = None,
    savant: SavantClient | None = None,
) -> list[ProjectionInputs]:
    """Build ``ProjectionInputs`` for every probable start on ``on_date``.

    Pass ``savant`` to additionally fill the Baseball Savant factors
    (swinging-strike% / CSW% and the pitch-mix matchup).
    """
    starts = await fetch_probable_starts(client, on_date)
    return [
        await build_projection_inputs(
            client, s, on_date, season, umpire_table, savant
        )
        for s in starts
    ]
