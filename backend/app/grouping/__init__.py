"""Historical grouping engine (offline).

Builds the 10-year play-by-play foundation that the group-vs-group baseline rests
on. This package is OFFLINE tooling — it is NOT imported by the live API; it runs
locally to download data, engineer features, and cluster pitchers/batters into
GROUPS (not "archetypes") from real play-by-play patterns.

Data sources (verified):
  * Retrosheet per-season CSVs — parsed play-by-play (no Chadwick needed):
    https://www.retrosheet.org/downloads/{year}/{year}csvs.zip  -> {year}plays.csv
    Event-level: counts, batted-ball type (GB/FB/LD), pitch-result strings
    (C/S/B/F/X), handedness. NO pitch types, launch angle, or exit velocity.
  * Statcast / Baseball Savant (via app.grouping.statcast) — the pitch-physics
    layer Retrosheet lacks: pitch types, whiff-by-type, launch/exit velocity.
"""
