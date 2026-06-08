"""Cross-book arbitrage scanner for two-way (over/under) strikeout props.

An arbitrage exists when you can take BOTH sides at different books and the sum
of the implied probabilities is below 1::

    1/decimal_over + 1/decimal_under < 1

The catch the naive version misses: both legs MUST be at the SAME line (Over 6.5
at one book vs Under 6.5 at another). Over 6.5 vs Under 7.5 is a *middle*, not a
locked arb, so we group quotes by line and only pair within a line.

This module is pure math (it reuses the odds conversion in :mod:`app.model.edge`)
and has no I/O — the data layer feeds it :class:`BookQuote` rows. Reality check:
true arbs are rare and short-lived; this is an inefficiency *detector*, not a
guaranteed-income machine.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.model.edge import american_to_decimal


@dataclass
class BookQuote:
    """One book's two-sided price for a pitcher at a given strikeout line."""

    bookmaker: str
    line: float
    over_odds: float
    under_odds: float


@dataclass
class ArbLeg:
    side: str  # "over" | "under"
    bookmaker: str
    american: float
    decimal: float
    stake: float
    payout: float


@dataclass
class ArbOpportunity:
    pitcher: str
    line: float
    arb_value: float  # 1/dec_over + 1/dec_under; < 1 means arbitrage
    profit_pct: float  # guaranteed return on total stake
    guaranteed_profit: float
    bankroll: float
    cross_book: bool  # legs are at two different books (a real arb, not a pricing typo)
    legs: list[ArbLeg] = field(default_factory=list)


def two_way_arb_value(decimal_over: float, decimal_under: float) -> float:
    """Sum of inverse decimal odds. < 1.0 means a locked profit exists."""
    return 1.0 / decimal_over + 1.0 / decimal_under


def split_stakes(
    bankroll: float, decimal_over: float, decimal_under: float
) -> tuple[float, float]:
    """Stakes that equalise payout on both sides (proportional to inverse odds)."""
    inv_o, inv_u = 1.0 / decimal_over, 1.0 / decimal_under
    total = inv_o + inv_u
    return bankroll * inv_o / total, bankroll * inv_u / total


def scan_pitcher(
    pitcher: str,
    quotes: list[BookQuote],
    bankroll: float = 100.0,
    min_profit_pct: float = 0.0,
) -> ArbOpportunity | None:
    """Best same-line two-way arb for one pitcher across books, or None.

    For each line, takes the best (highest-decimal) over price and best under
    price across all books; if their inverse-odds sum is < 1 it's an arb. Returns
    the most profitable line, filtered by ``min_profit_pct`` (e.g. 0.01 = 1%).
    """
    by_line: dict[float, list[BookQuote]] = defaultdict(list)
    for q in quotes:
        by_line[q.line].append(q)

    best: ArbOpportunity | None = None
    for line, line_quotes in by_line.items():
        best_over = max(line_quotes, key=lambda q: american_to_decimal(q.over_odds))
        best_under = max(line_quotes, key=lambda q: american_to_decimal(q.under_odds))
        dec_o = american_to_decimal(best_over.over_odds)
        dec_u = american_to_decimal(best_under.under_odds)

        av = two_way_arb_value(dec_o, dec_u)
        if av >= 1.0:
            continue
        profit_pct = (1.0 - av) / av
        if profit_pct < min_profit_pct:
            continue

        stake_o, stake_u = split_stakes(bankroll, dec_o, dec_u)
        payout = stake_o * dec_o  # equals stake_u * dec_u by construction
        opp = ArbOpportunity(
            pitcher=pitcher,
            line=line,
            arb_value=av,
            profit_pct=profit_pct,
            guaranteed_profit=payout - bankroll,
            bankroll=bankroll,
            cross_book=best_over.bookmaker != best_under.bookmaker,
            legs=[
                ArbLeg("over", best_over.bookmaker, best_over.over_odds, dec_o,
                       round(stake_o, 2), round(stake_o * dec_o, 2)),
                ArbLeg("under", best_under.bookmaker, best_under.under_odds, dec_u,
                       round(stake_u, 2), round(stake_u * dec_u, 2)),
            ],
        )
        if best is None or opp.profit_pct > best.profit_pct:
            best = opp
    return best


def scan_quotes(
    quotes_by_pitcher: dict[str, list[BookQuote]],
    bankroll: float = 100.0,
    min_profit_pct: float = 0.0,
) -> list[ArbOpportunity]:
    """Scan every pitcher; return arb opportunities, most profitable first."""
    opps = [
        opp
        for pitcher, quotes in quotes_by_pitcher.items()
        if (opp := scan_pitcher(pitcher, quotes, bankroll, min_profit_pct)) is not None
    ]
    opps.sort(key=lambda o: o.profit_pct, reverse=True)
    return opps
