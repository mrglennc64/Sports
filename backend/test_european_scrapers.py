#!/usr/bin/env python3
"""
Test script for European odds scrapers.

Usage:
    python test_european_scrapers.py           # Test all
    python test_european_scrapers.py --betano  # Test Betano only
    python test_european_scrapers.py --bet365  # Test bet365 only
    python test_european_scrapers.py --unibet  # Test Unibet only
    python test_european_scrapers.py --csv     # Test CSV importer

All tests are headless by default (no visible browser).
Pass --headless=false to see the browser in action (useful for debugging).
"""
import sys
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.data.european_odds import (
    BetanoProvider,
    Bet365Provider,
    UnibetProvider,
    CsvOddsProvider,
)


def test_betano(headless: bool = True):
    """Test Betano scraper."""
    print("\n" + "=" * 60)
    print("Testing BETANO Scraper")
    print("=" * 60)
    
    try:
        provider = BetanoProvider(headless=headless)
        props = provider.get_strikeout_props()
        
        if props:
            print(f"✅ SUCCESS: Scraped {len(props)} props\n")
            for p in props[:5]:  # Show first 5
                print(f"  {p.pitcher_name:20} {p.line:5.1f}K  "
                      f"Over: {p.over_odds:7.2f}  Under: {p.under_odds:7.2f}")
            if len(props) > 5:
                print(f"  ... and {len(props) - 5} more")
        else:
            print("⚠️  No props found (page may have loaded but no strikeouts found)")
        
        return len(props) > 0
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_bet365(headless: bool = True):
    """Test bet365 scraper."""
    print("\n" + "=" * 60)
    print("Testing BET365 Scraper")
    print("=" * 60)
    
    try:
        provider = Bet365Provider(headless=headless)
        props = provider.get_strikeout_props()
        
        if props:
            print(f"✅ SUCCESS: Scraped {len(props)} props\n")
            for p in props[:5]:
                print(f"  {p.pitcher_name:20} {p.line:5.1f}K  "
                      f"Over: {p.over_odds:7.2f}  Under: {p.under_odds:7.2f}")
            if len(props) > 5:
                print(f"  ... and {len(props) - 5} more")
        else:
            print("⚠️  No props found (page may have loaded but no strikeouts found)")
        
        return len(props) > 0
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_unibet(headless: bool = True):
    """Test Unibet scraper."""
    print("\n" + "=" * 60)
    print("Testing UNIBET Scraper")
    print("=" * 60)
    
    try:
        provider = UnibetProvider(headless=headless)
        props = provider.get_strikeout_props()
        
        if props:
            print(f"✅ SUCCESS: Scraped {len(props)} props\n")
            for p in props[:5]:
                print(f"  {p.pitcher_name:20} {p.line:5.1f}K  "
                      f"Over: {p.over_odds:7.2f}  Under: {p.under_odds:7.2f}")
            if len(props) > 5:
                print(f"  ... and {len(props) - 5} more")
        else:
            print("⚠️  No props found (page may have loaded but no strikeouts found)")
        
        return len(props) > 0
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_csv():
    """Test CSV importer."""
    print("\n" + "=" * 60)
    print("Testing CSV Importer")
    print("=" * 60)
    
    # Create a test CSV
    test_csv_path = Path(__file__).parent / "test_lines.csv"
    test_csv_path.write_text(
        "pitcher_name,line,over_odds,under_odds,bookmaker\n"
        "Sale,5.5,1.95,1.85,betano\n"
        "Crochet,5.5,1.92,1.88,bet365\n"
        "Skubal,5.5,1.90,1.90,unibet\n"
    )
    
    try:
        provider = CsvOddsProvider(csv_path=str(test_csv_path))
        props = provider.get_strikeout_props()
        
        if props and len(props) == 3:
            print(f"✅ SUCCESS: Loaded {len(props)} props from CSV\n")
            for p in props:
                print(f"  {p.pitcher_name:20} {p.line:5.1f}K  "
                      f"Over: {p.over_odds:7.2f}  Under: {p.under_odds:7.2f}  "
                      f"({p.bookmaker})")
        else:
            print(f"❌ Expected 3 props, got {len(props)}")
        
        test_csv_path.unlink()  # Clean up
        return len(props) == 3
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test European odds scrapers")
    parser.add_argument("--betano", action="store_true", help="Test Betano only")
    parser.add_argument("--bet365", action="store_true", help="Test bet365 only")
    parser.add_argument("--unibet", action="store_true", help="Test Unibet only")
    parser.add_argument("--csv", action="store_true", help="Test CSV importer")
    parser.add_argument("--headless", default="true", help="Run headless (true/false)")
    
    args = parser.parse_args()
    headless = args.headless.lower() == "true"
    
    # Determine which tests to run
    all_tests = not any([args.betano, args.bet365, args.unibet, args.csv])
    
    results = {}
    
    if args.betano or all_tests:
        print("⏳ Starting Betano scraper...")
        results["Betano"] = test_betano(headless)
    
    if args.bet365 or all_tests:
        print("⏳ Starting bet365 scraper...")
        results["bet365"] = test_bet365(headless)
    
    if args.unibet or all_tests:
        print("⏳ Starting Unibet scraper...")
        results["Unibet"] = test_unibet(headless)
    
    if args.csv or all_tests:
        print("⏳ Testing CSV importer...")
        results["CSV"] = test_csv()
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    total = len(results)
    passed = sum(results.values())
    print(f"\nTotal: {passed}/{total} passed")
    
    sys.exit(0 if passed == total else 1)
