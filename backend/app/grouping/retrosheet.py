"""Retrosheet play-by-play ingestion (verified against the real 2015 schema).

Downloads the per-season CSV bundles from Retrosheet's *parsed* downloads — no
Chadwick C-tool needed, contrary to the older workflow. Each season zip
(``{year}csvs.zip``) contains ``{year}plays.csv`` (~110 MB, ~195k plays/season),
which is the play-by-play we cluster on.

Verified columns we actually use (the real header, not guessed names):
  batter, pitcher        — player ids
  bathand, pithand       — handedness (platoon splits)
  balls, strikes, count  — count leverage
  pitches                — pitch-RESULT string, e.g. "CSFBBX" (C=called strike,
                           S=swinging strike, B=ball, F=foul, X=ball in play).
                           NOT pitch types — those need Statcast.
  pa, ab, k, walk, hbp, single..hr, sf, sh  — outcome events
  bip, ground, fly, line, bunt               — batted-ball type (contact profile)

Example (verified):
    from app.grouping.retrosheet import download_seasons, DATA_DIR
    download_seasons(range(2015, 2026))   # -> DATA_DIR/retrosheet/{year}/{year}plays.csv
"""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

# Default local store (offline only — never the server). Override with STRIKE_DATA_DIR.
DATA_DIR = Path(os.environ.get("STRIKE_DATA_DIR", r"C:\strike-data"))

_BASE = "https://www.retrosheet.org/downloads/{year}/{year}csvs.zip"

# Files we keep from each season zip (lean: play-by-play + game context).
_KEEP_SUFFIXES = ("plays.csv", "gameinfo.csv")

# Columns the feature layer relies on — used to fail loudly if Retrosheet ever
# changes the schema, instead of silently producing empty features.
REQUIRED_PLAYS_COLUMNS = frozenset({
    "gid", "batter", "pitcher", "bathand", "pithand",
    "balls", "strikes", "count", "pitches",
    "pa", "ab", "k", "walk", "hbp", "bip", "ground", "fly", "line",
})


def season_zip_url(year: int) -> str:
    return _BASE.format(year=year)


def retrosheet_dir(data_dir: Path = DATA_DIR) -> Path:
    return Path(data_dir) / "retrosheet"


def plays_path(year: int, data_dir: Path = DATA_DIR) -> Path:
    return retrosheet_dir(data_dir) / str(year) / f"{year}plays.csv"


def validate_plays_header(header_columns) -> list[str]:
    """Return the list of REQUIRED columns missing from a plays.csv header (empty = OK)."""
    present = set(header_columns)
    return sorted(REQUIRED_PLAYS_COLUMNS - present)


def download_season(year: int, data_dir: Path = DATA_DIR, *, force: bool = False) -> Path:
    """Download + extract one season's play-by-play. Returns the plays.csv path.

    Skips the download if the plays.csv already exists (unless ``force``). Raises
    on HTTP failure or a schema mismatch (missing required columns).
    """
    out_dir = retrosheet_dir(data_dir) / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{year}plays.csv"
    if target.exists() and not force:
        return target

    req = Request(season_zip_url(year), headers={"User-Agent": "strike-grouping/1.0"})
    with urlopen(req, timeout=120) as resp:  # noqa: S310 (trusted host)
        blob = resp.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            if name.endswith(_KEEP_SUFFIXES):
                z.extract(name, out_dir)
                extracted = out_dir / name
                # Some zips nest a folder; flatten to out_dir/{basename}.
                if extracted != out_dir / Path(name).name:
                    extracted.replace(out_dir / Path(name).name)

    if not target.exists():
        raise FileNotFoundError(f"{year}plays.csv not found in the season zip for {year}")

    with target.open("r", encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split(",")
    missing = validate_plays_header(header)
    if missing:
        raise ValueError(f"{year}plays.csv missing required columns: {missing}")
    return target


def download_seasons(years, data_dir: Path = DATA_DIR, *, force: bool = False) -> dict[int, Path]:
    """Download a range of seasons. Returns {year: plays_path}. Prints progress."""
    out: dict[int, Path] = {}
    for year in years:
        path = download_season(year, data_dir, force=force)
        size_mb = path.stat().st_size / 1e6
        print(f"[retrosheet] {year}: {path}  ({size_mb:.0f} MB)")
        out[year] = path
    return out
