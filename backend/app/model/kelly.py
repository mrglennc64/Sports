"""Kelly Criterion bet sizing for optimal bankroll growth.

Inspired by Poly-Trader's dynamic bet sizing approach.
Instead of flat 5% kelly on all bets, scale bets to edge quality.

Kelly Criterion formula:
  f* = (b*p - q) / b
  where:
    f* = fraction of bankroll to bet
    b = decimal_odds - 1
    p = probability of winning
    q = 1 - p (probability of losing)

Key insight: Larger edge = larger bet, smaller edge = smaller bet (or no bet)
"""

from dataclasses import dataclass
from typing import Optional


def american_to_decimal(american_odds: int) -> float:
    """Convert American odds to decimal.

    Args:
        american_odds: e.g., -142 or +115

    Returns:
        Decimal odds (e.g., 1.704 or 2.15)
    """
    if american_odds > 0:
        return (american_odds / 100.0) + 1
    else:
        return (100.0 / abs(american_odds)) + 1


def decimal_to_american(decimal_odds: float) -> int:
    """Convert decimal odds to American."""
    if decimal_odds >= 2.0:
        return int((decimal_odds - 1) * 100)
    else:
        return int(-100 / (decimal_odds - 1))


def calculate_kelly_fraction(
    model_probability: float,
    market_probability: float,
    american_odds: int,
    max_kelly: float = 0.05,
    kelly_fraction_fraction: float = 0.25
) -> float:
    """Calculate optimal Kelly fraction for a bet.

    Args:
        model_probability: Your model's estimated win probability (0.0-1.0)
        market_probability: Market's implied probability from odds (0.0-1.0)
        american_odds: Sportsbook odds (e.g., -142 or +115)
        max_kelly: Cap kelly at this % (default 0.05 = 5%)
        kelly_fraction_fraction: Use fraction of Kelly (default 0.25 = "quarter Kelly")
                                Reduces variance while preserving growth

    Returns:
        Suggested bet size as % of bankroll (0.0-1.0)

    Example:
        Model says 65% UNDER, market says 60% (implied by -142 odds)
        Model has +5% edge
        Kelly says bet ~2.5% of bankroll
        Quarter Kelly = 0.625% (safer growth)
    """
    # Edge = model prob - market prob
    edge = model_probability - market_probability

    # If no edge or negative edge, don't bet
    if edge <= 0:
        return 0.0

    # Convert odds to decimal
    decimal_odds = american_to_decimal(american_odds)

    # Kelly formula: f* = (b*p - q) / b
    b = decimal_odds - 1  # Return ratio
    p = model_probability  # Win probability
    q = 1 - p  # Loss probability

    kelly_full = (b * p - q) / b if b > 0 else 0

    # Use fraction of Kelly to reduce variance
    kelly = kelly_full * kelly_fraction_fraction

    # Cap at maximum
    kelly = max(0, min(kelly, max_kelly))

    return kelly


def calculate_bet_size(
    kelly_fraction: float,
    bankroll: float,
    min_bet: float = 1.0
) -> float:
    """Convert Kelly fraction to actual bet size.

    Args:
        kelly_fraction: Output from calculate_kelly_fraction (0.0-1.0)
        bankroll: Current bankroll in dollars
        min_bet: Don't bet less than this amount

    Returns:
        Suggested bet size in dollars
    """
    bet = kelly_fraction * bankroll
    return max(min_bet, bet)


@dataclass
class KellyResult:
    """Output from Kelly calculation."""
    kelly_fraction: float  # Fraction of bankroll (0.0-1.0)
    bet_size: float  # Dollar amount
    win_probability: float  # Your estimated win %
    market_probability: float  # Market's estimated win %
    edge_percentage: float  # Your advantage
    reasoning: str  # Human-readable explanation


def evaluate_bet_with_kelly(
    pitcher: str,
    model_projection: float,
    market_line: float,
    american_odds: int,
    bankroll: float = 1000.0,
    use_quarter_kelly: bool = True
) -> KellyResult:
    """End-to-end Kelly evaluation for a bet.

    This is the main entry point for converting predictions to bet sizes.

    Args:
        pitcher: Pitcher name (for reasoning)
        model_projection: Your model's K projection (e.g., 6.49)
        market_line: Sportsbook line (e.g., 7.5)
        american_odds: Sportsbook odds (e.g., -142 for UNDER)
        bankroll: Current bankroll
        use_quarter_kelly: Use 25% Kelly instead of full Kelly

    Returns:
        KellyResult with bet recommendation
    """
    # Determine if betting OVER or UNDER, using the EXACT Poisson probability
    # (replaces a fixed sigma=2.5 normal approximation that mis-sized small/large
    # lambda and ignored half-line/push handling).
    from app.model import poisson
    if model_projection > market_line:
        side = "OVER"
        model_prob = poisson.prob_over(model_projection, market_line)
    else:
        side = "UNDER"
        model_prob = poisson.prob_under(model_projection, market_line)

    # Market probability from odds
    decimal_odds = american_to_decimal(american_odds)
    market_prob = 1 / decimal_odds

    # Edge
    edge_pct = model_prob - market_prob

    # Kelly
    kelly = calculate_kelly_fraction(
        model_probability=model_prob,
        market_probability=market_prob,
        american_odds=american_odds,
        kelly_fraction_fraction=0.25 if use_quarter_kelly else 1.0
    )

    bet_size = calculate_bet_size(kelly, bankroll)

    # Reasoning
    if kelly <= 0:
        reasoning = f"No edge (model {model_prob:.1%} vs market {market_prob:.1%})"
    elif kelly < 0.001:
        reasoning = f"Edge too small ({edge_pct:.1%}), kelly < 0.1%"
    else:
        reasoning = f"{side} {market_line}: Model {model_prob:.1%} vs Market {market_prob:.1%}, Edge {edge_pct:.1%}, Bet {kelly:.2%} of bankroll (${bet_size:.0f})"

    return KellyResult(
        kelly_fraction=kelly,
        bet_size=bet_size,
        win_probability=model_prob,
        market_probability=market_prob,
        edge_percentage=edge_pct,
        reasoning=reasoning
    )
