"""Data layer: fetch MLB Stats API data into the model's input shapes."""

from __future__ import annotations

from app.data.assemble import build_all_for_date, build_projection_inputs
from app.data.client import StatsApiClient
from app.data.mlb_stats import (
    ProbableStart,
    fetch_lineup_strength,
    fetch_opponent_k_profile,
    fetch_pitcher_form,
    fetch_pitcher_workload,
    fetch_probable_starts,
    parse_innings,
)
from app.data.umpires import (
    fetch_home_plate_umpire,
    fetch_umpire_profile,
    load_umpire_table,
    umpire_profile,
)
from app.data.savant import (
    SavantClient,
    fetch_pitch_mix_matchup,
    fetch_pitcher_whiff_csw,
)
from app.data.history import (
    backtest_range,
    load_history_for_date,
    load_history_range,
    load_lines_csv,
)
# NOTE: app.data.snapshot is intentionally NOT imported here — it is a CLI run as
# ``python -m app.data.snapshot``; pre-importing it triggers a runpy warning.
# Import it directly: ``from app.data.snapshot import snapshot_lines``.

__all__ = [
    "StatsApiClient",
    "ProbableStart",
    "fetch_probable_starts",
    "fetch_pitcher_form",
    "fetch_pitcher_workload",
    "fetch_opponent_k_profile",
    "fetch_lineup_strength",
    "parse_innings",
    "build_projection_inputs",
    "build_all_for_date",
    "load_umpire_table",
    "umpire_profile",
    "fetch_home_plate_umpire",
    "fetch_umpire_profile",
    "SavantClient",
    "fetch_pitcher_whiff_csw",
    "fetch_pitch_mix_matchup",
    "load_history_for_date",
    "load_history_range",
    "load_lines_csv",
    "backtest_range",
]
