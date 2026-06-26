import duckdb

# Connect to the database
conn = duckdb.connect('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/data/baseball.duckdb', read_only=True)

# Get all tables
print("=== ALL TABLES ===")
tables = conn.execute("SHOW TABLES").fetchall()
for table in tables:
    print(f"  {table[0]}")

print("\n=== PITCHER_ARCHETYPES_V2 SCHEMA ===")
try:
    schema = conn.execute("DESCRIBE pitcher_archetypes_v2").fetchall()
    for col in schema:
        print(f"  {col[0]}: {col[1]}")

    count = conn.execute("SELECT COUNT(*) FROM pitcher_archetypes_v2").fetchone()[0]
    print(f"\nRow count: {count}")

    print("\nSample rows:")
    sample = conn.execute("SELECT * FROM pitcher_archetypes_v2 LIMIT 3").fetchall()
    for row in sample:
        print(f"  {row}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== BATTER_ARCHETYPES_V2 SCHEMA ===")
try:
    schema = conn.execute("DESCRIBE batter_archetypes_v2").fetchall()
    for col in schema:
        print(f"  {col[0]}: {col[1]}")

    count = conn.execute("SELECT COUNT(*) FROM batter_archetypes_v2").fetchone()[0]
    print(f"\nRow count: {count}")

    print("\nSample rows:")
    sample = conn.execute("SELECT * FROM batter_archetypes_v2 LIMIT 3").fetchall()
    for row in sample:
        print(f"  {row}")
except Exception as e:
    print(f"Error: {e}")

# Check for pitcher and batter base tables
print("\n=== CHECKING FOR BASE TABLES ===")
for table_name in ['pitchers', 'batters', 'pitcher_stats', 'batter_stats']:
    try:
        count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        print(f"{table_name}: {count} rows")
    except:
        print(f"{table_name}: NOT FOUND")

conn.close()
