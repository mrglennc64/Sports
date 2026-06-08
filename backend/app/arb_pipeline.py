"""Cross-book arbitrage scan over a slate of strikeout props.

Glues the odds layer (:mod:`app.data.odds`, which now retains every book's
quote) to the pure arb engine (:mod:`app.model.arb`). Pulls all books' quotes
for every MLB event, merges them per pitcher, and returns ranked arbitrage
opportunities. Sync (the odds provider is sync), so the API route is sync too.
"""

from __future__ import annotations

from dataclasses import asdict

from app.config import Settings
from app.config import settings as default_settings
from app.data.odds import OddsProvider, get_provider
from app.model.arb import BookQuote, scan_quotes


def _collect_quotes(provider: OddsProvider) -> dict[str, list[BookQuote]]:
    """All books' quotes for every pitcher across every MLB event."""
    by_pitcher: dict[str, list[BookQuote]] = {}
    for event in provider.list_events():
        try:
            event_quotes = provider.get_strikeout_quotes(event.event_id)
        except Exception:  # one bad event shouldn't sink the scan
            continue
        for pitcher, prices in event_quotes.items():
            bucket = by_pitcher.setdefault(pitcher, [])
            bucket.extend(
                BookQuote(p.bookmaker, p.line, p.over_odds, p.under_odds)
                for p in prices
            )
    return by_pitcher


def scan_arbitrage(
    *,
    bankroll: float = 100.0,
    min_profit_pct: float = 0.0,
    provider: OddsProvider | None = None,
    settings: Settings = default_settings,
) -> dict:
    """Scan the current slate for cross-book strikeout arbitrage.

    Returns a JSON-able dict: the bankroll used, a count, and the ranked
    opportunities (most profitable first). ``min_profit_pct`` filters out razor-
    thin edges (e.g. 0.01 = require >=1% locked profit after stake split).
    """
    provider = provider or get_provider(
        settings.odds_provider,
        settings.odds_api_key_theoddsapi,
        settings.odds_api_key_io,
    )
    quotes = _collect_quotes(provider)
    opps = scan_quotes(quotes, bankroll=bankroll, min_profit_pct=min_profit_pct)
    return {
        "bankroll": bankroll,
        "min_profit_pct": min_profit_pct,
        "count": len(opps),
        "opportunities": [asdict(o) for o in opps],
    }
