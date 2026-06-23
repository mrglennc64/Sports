#!/usr/bin/env python3
"""Test CSV importer directly."""
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(r"c:\Users\carin\OneDrive\Dokument\stike\mlb-edge\backend")
sys.path.insert(0, str(backend_path))

from app.data.european_odds import CsvOddsProvider

csv_file = r"c:\Users\carin\OneDrive\Dokument\stike\mlb-edge\validate_littell_today.csv"

print("=" * 70)
print("TESTING CSV IMPORTER")
print("=" * 70)
print(f"\nLoading CSV from: {csv_file}")

try:
    provider = CsvOddsProvider(csv_path=csv_file)
    props = provider.get_strikeout_props()
    
    print(f"\n[OK] SUCCESS: Loaded {len(props)} strikeout props\n")
    print(f"{'Pitcher':<20} {'Line':<6} {'Over':<10} {'Under':<10} {'Bookmaker':<10}")
    print("-" * 70)
    
    for p in props:
        print(f"{p.pitcher_name:<20} {p.line:<6.1f} {p.over_odds:<10.2f} {p.under_odds:<10.2f} {p.bookmaker:<10}")
    
    print("\n[OK] CSV importer is working!")
    
except Exception as e:
    print(f"\n[FAIL] FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
