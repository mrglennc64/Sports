import duckdb
import sys

# Connect to the database
conn = duckdb.connect('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/data/baseball.duckdb', read_only=True)

output_lines = []

def add_line(line=""):
    """Add a line to the output buffer"""
    output_lines.append(line)
    print(line)

# ========== PITCHER ARCHETYPES ==========
add_line("=" * 80)
add_line("PITCHER ARCHETYPES (2026 Season)")
add_line("=" * 80)
add_line()

pitcher_archetypes = conn.execute("""
    SELECT
        cluster,
        rank,
        label,
        size,
        k,
        bb,
        whiff,
        chase,
        velo,
        gb,
        brl
    FROM pitcher_archetypes_v2
    WHERE season = 2026
    ORDER BY rank
""").fetchall()

total_pitchers = sum([p[3] for p in pitcher_archetypes])
add_line(f"Total Pitchers Clustered: {total_pitchers}")
add_line(f"Number of Clusters: {len(pitcher_archetypes)}")
add_line()

for archetype in pitcher_archetypes:
    cluster, rank, label, size, k, bb, whiff, chase, velo, gb, brl = archetype

    add_line(f"Cluster {cluster}: {label.upper()}")
    add_line(f"  Rank: #{rank}")
    add_line(f"  Size: {size} pitchers ({100 * size / total_pitchers:.1f}%)")
    add_line(f"  Statistics:")
    add_line(f"    Strikeout Rate (K%): {k:.1f}%")
    add_line(f"    Walk Rate (BB%):     {bb:.1f}%")
    add_line(f"    Whiff Rate:          {whiff:.1f}%")
    add_line(f"    Chase Rate:          {chase:.1f}%")
    add_line(f"    Velocity (MPH):      {velo:.1f}")
    add_line(f"    Ground Ball Rate:    {gb:.1f}%")
    add_line(f"    Barrel Rate:         {brl:.1f}%")

    # Find sample players from this cluster
    sample_players = conn.execute(f"""
        SELECT
            p.player_id,
            p.name,
            ps.pa,
            ps.k_percent,
            ps.bb_percent,
            ps.whiff_percent
        FROM pitchers p
        JOIN pitcher_statcast ps ON p.player_id = ps.player_id AND ps.season = 2026
        WHERE p.cluster_v2 = {cluster} AND p.season = 2026
        ORDER BY ps.pa DESC
        LIMIT 5
    """).fetchall()

    if sample_players:
        add_line(f"  Sample Players (by PA):")
        for player in sample_players:
            player_id, name, pa, k_pct, bb_pct, whiff_pct = player
            add_line(f"    - {name} (PA: {int(pa)}, K: {k_pct:.1f}%, BB: {bb_pct:.1f}%, Whiff: {whiff_pct:.1f}%)")

    add_line()

# ========== BATTER ARCHETYPES ==========
add_line("=" * 80)
add_line("BATTER ARCHETYPES (2026 Season)")
add_line("=" * 80)
add_line()

batter_archetypes = conn.execute("""
    SELECT
        cluster,
        rank,
        label,
        size,
        k,
        bb,
        chase,
        zcon,
        ev,
        la,
        brl,
        sb
    FROM batter_archetypes_v2
    WHERE season = 2026
    ORDER BY rank
""").fetchall()

total_batters = sum([b[3] for b in batter_archetypes])
add_line(f"Total Batters Clustered: {total_batters}")
add_line(f"Number of Clusters: {len(batter_archetypes)}")
add_line()

for archetype in batter_archetypes:
    cluster, rank, label, size, k, bb, chase, zcon, ev, la, brl, sb = archetype

    add_line(f"Cluster {cluster}: {label.upper()}")
    add_line(f"  Rank: #{rank}")
    add_line(f"  Size: {size} batters ({100 * size / total_batters:.1f}%)")
    add_line(f"  Statistics:")
    add_line(f"    Strikeout Rate (K%):    {k:.1f}%")
    add_line(f"    Walk Rate (BB%):        {bb:.1f}%")
    add_line(f"    Chase Rate:             {chase:.1f}%")
    add_line(f"    Zone Contact (Z-Con%):  {zcon:.1f}%")
    add_line(f"    Exit Velocity (MPH):    {ev:.1f}")
    add_line(f"    Launch Angle:           {la:.1f}°")
    add_line(f"    Barrel Rate:            {brl:.1f}%")
    add_line(f"    Stolen Bases (avg):     {sb:.2f}")

    # Find sample players from this cluster
    sample_players = conn.execute(f"""
        SELECT
            b.player_id,
            b.name,
            bs.pa,
            bs.k_percent,
            bs.bb_percent,
            bs.oz_swing_percent,
            bs.iz_contact_percent
        FROM batters b
        JOIN batter_statcast bs ON b.player_id = bs.player_id AND bs.season = 2026
        WHERE b.cluster_v2 = {cluster} AND b.season = 2026
        ORDER BY bs.pa DESC
        LIMIT 5
    """).fetchall()

    if sample_players:
        add_line(f"  Sample Players (by PA):")
        for player in sample_players:
            player_id, name, pa, k_pct, bb_pct, chase_pct, z_contact = player
            add_line(f"    - {name} (PA: {int(pa)}, K: {k_pct:.1f}%, BB: {bb_pct:.1f}%, Chase: {chase_pct:.1f}%, Z-Con: {z_contact:.1f}%)")

    add_line()

# ========== SUMMARY ==========
add_line("=" * 80)
add_line("ARCHETYPE SUMMARY")
add_line("=" * 80)
add_line()
add_line("PITCHER ARCHETYPES:")
for archetype in pitcher_archetypes:
    cluster, rank, label, size, k, bb, whiff, chase, velo, gb, brl = archetype
    add_line(f"  {rank}. {label} (n={size})")

add_line()
add_line("BATTER ARCHETYPES:")
for archetype in batter_archetypes:
    cluster, rank, label, size, k, bb, chase, zcon, ev, la, brl, sb = archetype
    add_line(f"  {rank}. {label} (n={size})")

add_line()
add_line("=" * 80)
add_line(f"Generated: 2026-06-26")
add_line("=" * 80)

# Write to file
output_path = 'C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/analytics/existing_archetype_profiles.txt'
with open(output_path, 'w') as f:
    f.write('\n'.join(output_lines))

print(f"\nReport saved to: {output_path}")

conn.close()
