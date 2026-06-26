import duckdb

conn = duckdb.connect('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/data/baseball.duckdb', read_only=True)

print("=== PITCHERS TABLE SCHEMA ===")
schema = conn.execute("DESCRIBE pitchers").fetchall()
for col in schema:
    print(f"  {col[0]}: {col[1]}")

print("\n=== SAMPLE PITCHERS ===")
sample = conn.execute("SELECT * FROM pitchers LIMIT 2").fetchall()
for row in sample:
    print(f"  {row}")

print("\n=== BATTERS TABLE SCHEMA ===")
schema = conn.execute("DESCRIBE batters").fetchall()
for col in schema:
    print(f"  {col[0]}: {col[1]}")

print("\n=== SAMPLE BATTERS ===")
sample = conn.execute("SELECT * FROM batters LIMIT 2").fetchall()
for row in sample:
    print(f"  {row}")

print("\n=== PITCHER_STATCAST TABLE SCHEMA ===")
schema = conn.execute("DESCRIBE pitcher_statcast").fetchall()
for col in schema:
    print(f"  {col[0]}: {col[1]}")

print("\n=== BATTER_STATCAST TABLE SCHEMA ===")
schema = conn.execute("DESCRIBE batter_statcast").fetchall()
for col in schema:
    print(f"  {col[0]}: {col[1]}")

conn.close()
