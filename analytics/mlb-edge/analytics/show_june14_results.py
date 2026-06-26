import duckdb

con = duckdb.connect('../data/baseball.duckdb', read_only=True)

results = con.execute("""
    SELECT e.player_name,
           count(CASE WHEN e.events LIKE 'strikeout%' THEN 1 END) AS ks,
           count(*) AS bf,
           e.home_team, e.away_team
    FROM pa_events_reg e
    WHERE e.game_date = '2026-06-14'
    GROUP BY e.player_name, e.home_team, e.away_team
    HAVING ks >= 3
    ORDER BY ks DESC
    LIMIT 20
""").fetchall()

print('2026-06-14 Results (pitchers with 3+ K):')
print()
for name, ks, bf, home, away in results:
    print(f'{name:<30} {ks:2} K in {bf:2} BF    ({away} @ {home})')
