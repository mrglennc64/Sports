#!/usr/bin/env python3
"""
Build pitcher archetype x batter archetype interaction matrix.

Analyzes how different pitcher types perform against different batter types
by aggregating plate appearance outcomes and computing key rates (K%, BB%, HR%).
"""

import duckdb
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# Paths
DB_PATH = Path(__file__).parent.parent / 'data' / 'baseball.duckdb'
EXPORT_DIR = Path(__file__).parent.parent / 'data' / 'exports'
EXPORT_DIR.mkdir(exist_ok=True)

def main():
    print("Building pitcher x batter archetype interaction matrix...")

    # Connect to database
    conn = duckdb.connect(str(DB_PATH), read_only=True)

    # Load archetype labels
    print("\n=== Loading archetype labels ===")
    pitcher_labels = conn.execute('''
        SELECT cluster, label
        FROM pitcher_archetypes_v2
    ''').fetchdf()

    batter_labels = conn.execute('''
        SELECT cluster, label
        FROM batter_archetypes_v2
    ''').fetchdf()

    print(f"Pitcher archetypes: {len(pitcher_labels)}")
    print(f"Batter archetypes: {len(batter_labels)}")

    # Build interaction matrix
    print("\n=== Computing interaction matrix ===")
    query = '''
    SELECT
        p.cluster_v2 as pitcher_archetype,
        pa.label as pitcher_label,
        b.cluster_v2 as batter_archetype,
        ba.label as batter_label,
        COUNT(*) as total_pa,
        SUM(CASE WHEN e.events = 'strikeout' THEN 1 ELSE 0 END) as k_count,
        SUM(CASE WHEN e.events = 'walk' THEN 1 ELSE 0 END) as bb_count,
        SUM(CASE WHEN e.events = 'home_run' THEN 1 ELSE 0 END) as hr_count,
        SUM(CASE WHEN e.events IN ('single', 'double', 'triple', 'home_run', 'walk', 'hit_by_pitch') THEN 1 ELSE 0 END) as on_base_count
    FROM pa_events e
    JOIN pitchers p ON e.pitcher = p.player_id AND e.season = p.season
    JOIN batters b ON e.batter = b.player_id AND e.season = b.season
    JOIN pitcher_archetypes_v2 pa ON p.cluster_v2 = pa.cluster
    JOIN batter_archetypes_v2 ba ON b.cluster_v2 = ba.cluster
    WHERE e.game_date >= '2024-01-01'
      AND p.cluster_v2 IS NOT NULL
      AND b.cluster_v2 IS NOT NULL
    GROUP BY p.cluster_v2, pa.label, b.cluster_v2, ba.label
    ORDER BY p.cluster_v2, b.cluster_v2
    '''

    df = conn.execute(query).fetchdf()
    conn.close()

    # Compute rates
    df['k_pct'] = (df['k_count'] / df['total_pa'] * 100).round(2)
    df['bb_pct'] = (df['bb_count'] / df['total_pa'] * 100).round(2)
    df['hr_pct'] = (df['hr_count'] / df['total_pa'] * 100).round(2)
    df['obp'] = (df['on_base_count'] / df['total_pa'] * 100).round(2)

    print(f"\nTotal cells: {len(df)}")
    print(f"Expected (6x7): {6 * 7}")

    # Report sparse data
    print("\n=== Sparse data warning ===")
    sparse = df[df['total_pa'] < 50]
    if len(sparse) > 0:
        print(f"Cells with <50 PAs: {len(sparse)}")
        for _, row in sparse.iterrows():
            print(f"  P{row['pitcher_archetype']} x B{row['batter_archetype']}: {row['total_pa']} PAs")
    else:
        print("No cells with <50 PAs")

    # Summary stats
    print("\n=== Summary statistics ===")
    print(f"PA range: {df['total_pa'].min():,} - {df['total_pa'].max():,}")
    print(f"K% range: {df['k_pct'].min():.1f}% - {df['k_pct'].max():.1f}%")
    print(f"BB% range: {df['bb_pct'].min():.1f}% - {df['bb_pct'].max():.1f}%")
    print(f"HR% range: {df['hr_pct'].min():.1f}% - {df['hr_pct'].max():.1f}%")

    # Save full matrix
    output_path = EXPORT_DIR / 'archetype_interaction_matrix.csv'
    df.to_csv(output_path, index=False)
    print(f"\nSaved to: {output_path}")

    # Create K% heatmap
    print("\n=== Creating K% heatmap ===")
    pivot = df.pivot(
        index='pitcher_label',
        columns='batter_label',
        values='k_pct'
    )

    plt.figure(figsize=(14, 8))
    sns.heatmap(
        pivot,
        annot=True,
        fmt='.1f',
        cmap='RdYlGn_r',
        center=22,
        cbar_kws={'label': 'Strikeout %'},
        linewidths=0.5
    )
    plt.title('Strikeout Rate by Pitcher x Batter Archetype', fontsize=14, pad=20)
    plt.xlabel('Batter Archetype', fontsize=11)
    plt.ylabel('Pitcher Archetype', fontsize=11)
    plt.xticks(rotation=45, ha='right')
    plt.yticks(rotation=0)
    plt.tight_layout()

    heatmap_path = Path(__file__).parent / 'archetype_k_rate_heatmap.png'
    plt.savefig(heatmap_path, dpi=150, bbox_inches='tight')
    print(f"Saved heatmap to: {heatmap_path}")

    # Find extreme matchups
    print("\n=== Extreme matchups ===")
    print("\nHighest K% matchups:")
    top_k = df.nlargest(3, 'k_pct')[['pitcher_label', 'batter_label', 'k_pct', 'total_pa']]
    for _, row in top_k.iterrows():
        print(f"  {row['k_pct']:.1f}% - {row['pitcher_label']} vs {row['batter_label']} ({row['total_pa']:,} PA)")

    print("\nLowest K% matchups:")
    bottom_k = df.nsmallest(3, 'k_pct')[['pitcher_label', 'batter_label', 'k_pct', 'total_pa']]
    for _, row in bottom_k.iterrows():
        print(f"  {row['k_pct']:.1f}% - {row['pitcher_label']} vs {row['batter_label']} ({row['total_pa']:,} PA)")

    print("\nHighest HR% matchups:")
    top_hr = df.nlargest(3, 'hr_pct')[['pitcher_label', 'batter_label', 'hr_pct', 'total_pa']]
    for _, row in top_hr.iterrows():
        print(f"  {row['hr_pct']:.1f}% - {row['pitcher_label']} vs {row['batter_label']} ({row['total_pa']:,} PA)")

    print("\n=== DONE ===")
    print(f"Matrix dimensions: {len(pitcher_labels)} pitchers x {len(batter_labels)} batters")
    print(f"Total PA analyzed: {df['total_pa'].sum():,}")

if __name__ == '__main__':
    main()
