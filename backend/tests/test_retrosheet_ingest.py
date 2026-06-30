"""Tests for Retrosheet ingestion helpers (pure; no network)."""
from __future__ import annotations

from pathlib import Path

from app.grouping.retrosheet import (
    REQUIRED_PLAYS_COLUMNS,
    plays_path,
    season_zip_url,
    validate_plays_header,
)

# The real 2015plays.csv header (verified by downloading the actual file).
REAL_HEADER = (
    "gid,event,inning,top_bot,vis_home,site,batteam,pitteam,score_v,score_h,"
    "batter,pitcher,lp,bat_f,bathand,pithand,balls,strikes,count,pitches,nump,"
    "pa,ab,single,double,triple,hr,sh,sf,hbp,walk,k,xi,roe,fc,othout,noout,oth,"
    "bip,bunt,ground,fly,line,iw,gdp,othdp,tp,fle,wp,pb,bk,oa,di"
).split(",")


def test_real_header_passes_validation():
    assert validate_plays_header(REAL_HEADER) == []


def test_missing_columns_are_reported():
    header = [c for c in REAL_HEADER if c not in ("k", "pitches")]
    missing = validate_plays_header(header)
    assert set(missing) == {"k", "pitches"}


def test_required_columns_exist_in_real_header():
    # Guard against typos in the required set: every required column is real.
    assert REQUIRED_PLAYS_COLUMNS.issubset(set(REAL_HEADER))


def test_season_zip_url_uses_the_correct_parsed_path():
    url = season_zip_url(2015)
    assert url == "https://www.retrosheet.org/downloads/2015/2015csvs.zip"
    # NOT the dead events/{year}seve.zip path the old workflow used.
    assert "seve.zip" not in url


def test_plays_path_layout():
    p = plays_path(2020, Path("/tmp/strike-data"))
    assert p.as_posix().endswith("strike-data/retrosheet/2020/2020plays.csv")
