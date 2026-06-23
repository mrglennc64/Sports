"""Pull per-start gameLogs for EVERY pitcher who started in 2024-2026.

Free MLB StatsAPI only. Produces one CSV the user can backtest a strikeout
model against. NOTE: contains actual results (K/IP/BF/...) but NO betting
lines — free historical strikeout lines do not exist, so this supports
projection-accuracy backtests, not ROI.
"""
import csv
import json
import time
import urllib.request

SEASONS = [2024, 2025, 2026]
OUT = "mlb-edge/data/all_starters_gamelogs_2024_2026.csv"
COLS = ["season", "date", "pitcher", "pitcher_id", "throws", "team", "opponent",
        "is_home", "IP", "K", "BF", "pitches", "H", "BB", "ER", "HR"]


def get_json(url, retries=3):
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception:
            time.sleep(1.5 * (i + 1))
    return {}


def team_abbr_map():
    data = get_json("https://statsapi.mlb.com/api/v1/teams?sportId=1")
    return {t["id"]: t.get("abbreviation", "") for t in data.get("teams", [])}


def starter_ids(season):
    """Every pitcher with >=1 game started that season."""
    url = (f"https://statsapi.mlb.com/api/v1/stats?stats=season&group=pitching"
           f"&season={season}&sportId=1&limit=3000&gameType=R&playerPool=All")
    data = get_json(url)
    ids = {}
    for blk in data.get("stats", []):
        for sp in blk.get("splits", []):
            st = sp.get("stat", {})
            if int(st.get("gamesStarted") or 0) >= 1:
                pl = sp.get("player", {})
                ids[pl.get("id")] = pl.get("fullName", "")
    return ids


def main():
    abbr = team_abbr_map()
    # Union of starter ids across all seasons (a 2024 starter may not start in 2026).
    all_ids = {}
    for s in SEASONS:
        for pid, name in starter_ids(s).items():
            all_ids.setdefault(pid, name)
    print(f"found {len(all_ids)} distinct starters across {SEASONS}", flush=True)

    rows = []
    for n, (pid, name) in enumerate(all_ids.items(), 1):
        if pid is None:
            continue
        for season in SEASONS:
            payload = get_json(
                f"https://statsapi.mlb.com/api/v1/people/{pid}"
                f"?hydrate=stats(group=[pitching],type=[gameLog],season={season})"
            )
            people = payload.get("people") or []
            if not people:
                continue
            throws = (people[0].get("pitchHand") or {}).get("code", "")
            stats = people[0].get("stats") or []
            splits = stats[0].get("splits") if stats else []
            for sp in (splits or []):
                st = sp.get("stat", {})
                if not st.get("gamesStarted"):
                    continue
                opp_id = (sp.get("opponent") or {}).get("id")
                team_id = (sp.get("team") or {}).get("id")
                rows.append({
                    "season": season,
                    "date": sp.get("date", ""),
                    "pitcher": name,
                    "pitcher_id": pid,
                    "throws": throws,
                    "team": abbr.get(team_id, ""),
                    "opponent": abbr.get(opp_id, ""),
                    "is_home": sp.get("isHome", ""),
                    "IP": st.get("inningsPitched", ""),
                    "K": st.get("strikeOuts", ""),
                    "BF": st.get("battersFaced", ""),
                    "pitches": st.get("numberOfPitches", ""),
                    "H": st.get("hits", ""),
                    "BB": st.get("baseOnBalls", ""),
                    "ER": st.get("earnedRuns", ""),
                    "HR": st.get("homeRuns", ""),
                })
        if n % 25 == 0:
            print(f"  {n}/{len(all_ids)} pitchers, {len(rows)} starts so far", flush=True)

    rows.sort(key=lambda r: (r["pitcher"], r["date"]))
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"DONE: wrote {len(rows)} starts to {OUT}", flush=True)


if __name__ == "__main__":
    main()
