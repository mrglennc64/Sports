"""Umpire called-strike behavior split by pitcher archetype.

Pure aggregation here; the backfill CLI (below) composes existing fetchers:
Savant statcast CSV for taken edge pitches + boxscore officials for the
home-plate umpire per game_pk. Output JSON sits alongside data/umpires.json
and is consumed by the projection's umpire factor when present.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class TakenPitch:
    umpire: str
    archetype: str
    called_strike: bool


def aggregate_csr(
    pitches: list[TakenPitch], min_taken: int = 50
) -> dict[str, dict[str, dict]]:
    by_cell: dict[tuple[str, str], list[bool]] = defaultdict(list)
    by_archetype: dict[str, list[bool]] = defaultdict(list)
    for p in pitches:
        by_cell[(p.umpire, p.archetype)].append(p.called_strike)
        by_archetype[p.archetype].append(p.called_strike)

    league = {
        arch: sum(calls) / len(calls) for arch, calls in by_archetype.items()
    }
    table: dict[str, dict[str, dict]] = defaultdict(dict)
    for (ump, arch), calls in by_cell.items():
        csr = sum(calls) / len(calls)
        table[ump][arch] = {
            "taken": len(calls),
            "csr": csr,
            "delta_vs_league": csr - league[arch],
            "reliable": len(calls) >= min_taken,
        }
    return dict(table)


# --- backfill CLI (composes existing fetchers; exercised by smoke run) --------

# Taken pitches: the batter did not swing, so the umpire made the call.
_TAKEN_DESCRIPTIONS = frozenset({"called_strike", "ball"})

# Shadow-zone approximation (feet): horizontal edge band, or vertical band
# around the batter-specific zone top/bottom.
_EDGE_X_MIN = 0.7
_EDGE_X_MAX = 1.1
_EDGE_Z_BAND = 0.2

# Savant row-limit safety: keep statcast_search windows small (well under the
# plan's <=31-day politeness cap) so one CSV never hits the export row cap.
_WINDOW_DAYS = 3
_SAVANT_PAUSE_SECONDS = 2.0
# Statcast CSV exports are generated server-side and can take a minute or
# more for an all-pitchers window; the SavantClient default (15s) is too short.
_SAVANT_TIMEOUT_SECONDS = 180.0


def _is_shadow_zone(
    plate_x: float | None,
    plate_z: float | None,
    sz_top: float | None,
    sz_bot: float | None,
) -> bool:
    """Edge pitch per the plan: |plate_x| in [0.7, 1.1] ft OR plate_z within
    0.2 ft of sz_top/sz_bot. Rows missing the needed coords are excluded."""
    if plate_x is not None and _EDGE_X_MIN <= abs(plate_x) <= _EDGE_X_MAX:
        return True
    if plate_z is not None:
        if sz_top is not None and abs(plate_z - sz_top) <= _EDGE_Z_BAND:
            return True
        if sz_bot is not None and abs(plate_z - sz_bot) <= _EDGE_Z_BAND:
            return True
    return False


def _date_windows(start: "dt.date", end: "dt.date") -> list[tuple["dt.date", "dt.date"]]:
    """Inclusive [start, end] split into consecutive _WINDOW_DAYS-day windows."""
    import datetime as dt

    windows = []
    cursor = start
    while cursor <= end:
        stop = min(cursor + dt.timedelta(days=_WINDOW_DAYS - 1), end)
        windows.append((cursor, stop))
        cursor = stop + dt.timedelta(days=1)
    return windows


async def backfill(start_date: str, end_date: str, out_path: str) -> None:
    """Build the umpire×archetype table for a date range and write JSON.

    Composes existing fetchers (no new HTTP code):

    * :class:`app.data.savant.SavantClient` ``statcast_search/csv`` for raw
      per-pitch rows (game_pk, pitcher, pitch_type, description, plate coords,
      sz_top/bot, release_speed), fetched sequentially in short date windows.
    * :func:`app.data.umpires.fetch_home_plate_umpire` (boxscore officials,
      officialType "Home Plate") for the umpire per game_pk.
    * :func:`app.model.archetypes.classify_pitcher` for the archetype.

    Pitch mix per pitcher (v1 simplification, noted per plan): computed from
    the fetched statcast rows of this date range themselves — each pitcher's
    pitch-type distribution and mean four-seam release_speed over the range —
    rather than the season pitch-arsenal leaderboard. Good enough to bucket
    archetypes; revisit if Task 18 finds the signal worth keeping.

    Shadow-zone filter: taken pitches (description called_strike/ball) with
    |plate_x| in [0.7, 1.1] ft OR plate_z within 0.2 ft of sz_top/sz_bot.
    """
    import asyncio
    import datetime as dt
    import json
    from pathlib import Path

    import httpx

    from app.data.client import StatsApiClient
    from app.data.savant import SavantClient, _parse_csv, _to_float
    from app.data.umpires import fetch_home_plate_umpire
    from app.model.archetypes import FOUR_SEAM, classify_pitcher

    start = dt.date.fromisoformat(start_date)
    end = dt.date.fromisoformat(end_date)
    if end < start:
        raise ValueError(f"end_date {end_date} before start_date {start_date}")

    # 1) Statcast rows for the range — sequential, short windows, polite pause.
    rows: list[dict[str, str]] = []
    seasons = sorted({start.year, end.year})
    async with SavantClient(timeout=_SAVANT_TIMEOUT_SECONDS) as savant:
        for lo, hi in _date_windows(start, end):
            params = {
                "all": "true",
                "type": "details",
                "player_type": "pitcher",
                "hfSea": "|".join(str(y) for y in seasons) + "|",
                "game_date_gt": lo.isoformat(),
                "game_date_lt": hi.isoformat(),
            }
            try:
                text = await savant.get_text("/statcast_search/csv", params=params)
            except httpx.HTTPError as exc:
                # One polite retry per window (Savant exports can be slow/flaky).
                print(f"savant {lo}..{hi}: {exc!r}; retrying once in 30s")
                await asyncio.sleep(30)
                text = await savant.get_text("/statcast_search/csv", params=params)
            window_rows = _parse_csv(text)
            rows.extend(window_rows)
            print(f"savant {lo}..{hi}: {len(window_rows)} pitches")
            await asyncio.sleep(_SAVANT_PAUSE_SECONDS)
    if not rows:
        raise RuntimeError("no statcast rows fetched for the range")

    # 2) Per-pitcher pitch mix (percent shares) + avg four-seam velo from rows.
    mix_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    ff_velo: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        pid = (row.get("pitcher") or "").strip()
        pitch = (row.get("pitch_type") or "").strip()
        if not pid or not pitch:
            continue
        mix_counts[pid][pitch] += 1
        if pitch in FOUR_SEAM:
            velo = _to_float(row.get("release_speed"))
            if velo is not None:
                ff_velo[pid].append(velo)

    archetype_by_pitcher: dict[str, str] = {}
    for pid, counts in mix_counts.items():
        total = sum(counts.values())
        mix = {pitch: 100.0 * n / total for pitch, n in counts.items()}
        velos = ff_velo.get(pid)
        avg_velo = sum(velos) / len(velos) if velos else None
        archetype_by_pitcher[pid] = classify_pitcher(mix, avg_velo).value

    # 3) Home-plate umpire per game_pk — sequential boxscore lookups.
    game_pks = sorted(
        {gp for row in rows if (gp := (row.get("game_pk") or "").strip())}
    )
    umpire_by_game: dict[str, str] = {}
    async with StatsApiClient() as stats:
        for game_pk in game_pks:
            name = await fetch_home_plate_umpire(stats, int(game_pk))
            if name:
                umpire_by_game[game_pk] = name
            await asyncio.sleep(0.2)
    print(f"umpires: {len(umpire_by_game)}/{len(game_pks)} games resolved")

    # 4) Filter to taken shadow-zone pitches and tag with umpire + archetype.
    taken: list[TakenPitch] = []
    for row in rows:
        desc = (row.get("description") or "").strip()
        if desc not in _TAKEN_DESCRIPTIONS:
            continue
        if not _is_shadow_zone(
            _to_float(row.get("plate_x")),
            _to_float(row.get("plate_z")),
            _to_float(row.get("sz_top")),
            _to_float(row.get("sz_bot")),
        ):
            continue
        umpire = umpire_by_game.get((row.get("game_pk") or "").strip())
        archetype = archetype_by_pitcher.get((row.get("pitcher") or "").strip())
        if not umpire or not archetype:
            continue
        taken.append(
            TakenPitch(
                umpire=umpire,
                archetype=archetype,
                called_strike=desc == "called_strike",
            )
        )
    print(f"taken shadow-zone pitches: {len(taken)}")

    # 5) Aggregate and write.
    table = aggregate_csr(taken)
    payload: dict = {
        "_meta": {
            "start_date": start_date,
            "end_date": end_date,
            "taken_pitches": len(taken),
            "games": len(umpire_by_game),
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
        **table,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out} ({len(table)} umpires)")


if __name__ == "__main__":
    import asyncio
    import sys

    asyncio.run(backfill(sys.argv[1], sys.argv[2], sys.argv[3]))
