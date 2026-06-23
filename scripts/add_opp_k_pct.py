"""Annotate the gameLog CSVs with an as-of opponent K% (leak-safe).

For each start vs opponent T on date D, opp_k_pct = T's batting strikeouts /
plate appearances over all of T's games STRICTLY BEFORE D that season. Early
in a season (thin prior sample) we fall back to T's full PRIOR-season K%, then
to league average. Two extra columns are written so the user can judge trust:

  opp_k_pct   the as-of opponent strikeout rate going into the game
  opp_k_pa    plate appearances behind that number (0 = a fallback was used)

Team batting logs are pulled once (30 teams x 3 seasons ~= 90 calls), turned
into date-sorted inclusive prefix sums, then joined to every start.
"""
import csv
import json
import time
import urllib.request
from bisect import bisect_left
from collections import defaultdict

SEASONS = [2024, 2025, 2026]
LEAGUE_AVG_K = 0.223
FILES = [
    "mlb-edge/data/all_starters_gamelogs_2024_2026.csv",
    "mlb-edge/data/pitcher_gamelogs_2024_2026.csv",
]


def get_json(url, retries=3):
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception:
            time.sleep(1.5 * (i + 1))
    return {}


def team_batting_log(team_id, season):
    """Per-game (date, K, PA) for a team's hitters that season, date-sorted."""
    data = get_json(
        f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
        f"?stats=gameLog&group=hitting&season={season}&gameType=R"
    )
    out = []
    for blk in data.get("stats", []):
        for sp in blk.get("splits", []):
            st = sp.get("stat", {})
            d = sp.get("date", "")
            k = int(st.get("strikeOuts") or 0)
            pa = int(st.get("plateAppearances") or 0)
            if d and pa:
                out.append((d, k, pa))
    out.sort(key=lambda x: x[0])
    return out


def main():
    id2abbr = {
        t["id"]: t.get("abbreviation", "")
        for t in get_json("https://statsapi.mlb.com/api/v1/teams?sportId=1").get("teams", [])
    }

    # abbr -> season -> (dates[], preK[], prePA[])   inclusive prefix sums
    idx = defaultdict(dict)
    # abbr -> season -> full-season K%   (prior-season fallback source)
    full = defaultdict(dict)
    for tid, abbr in id2abbr.items():
        if not abbr:
            continue
        for s in SEASONS:
            log = team_batting_log(tid, s)
            dates, preK, prePA = [], [], []
            tk = tp = 0
            for d, k, pa in log:
                tk += k
                tp += pa
                dates.append(d)
                preK.append(tk)
                prePA.append(tp)
            idx[abbr][s] = (dates, preK, prePA)
            full[abbr][s] = (tk / tp) if tp else None
    print(f"built batting index for {len(idx)} teams", flush=True)

    def lookup(abbr, season, date):
        season = int(season)
        dates, preK, prePA = idx.get(abbr, {}).get(season, ([], [], []))
        i = bisect_left(dates, date)  # strictly-before games are indices [0, i-1]
        if i > 0 and prePA[i - 1] >= 50:
            return round(preK[i - 1] / prePA[i - 1], 4), prePA[i - 1]
        prior = full.get(abbr, {}).get(season - 1)
        if prior is not None:
            return round(prior, 4), 0
        return LEAGUE_AVG_K, 0

    for path in FILES:
        rows = list(csv.DictReader(open(path, encoding="utf-8")))
        for r in rows:
            kpct, pa = lookup(r["opponent"], r["season"], r["date"])
            r["opp_k_pct"] = kpct
            r["opp_k_pa"] = pa
        cols = list(rows[0].keys())
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        asof_n = sum(1 for r in rows if r["opp_k_pa"])
        print(f"{path}: annotated {len(rows)} rows "
              f"({asof_n} true as-of, {len(rows) - asof_n} fallback)", flush=True)


if __name__ == "__main__":
    main()
