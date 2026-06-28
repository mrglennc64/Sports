"""
EDGE% GATEKEEPER CALCULATION FOR POISSON STRIKEOUT MODEL

Code snippets for the new gatekeeper logic that replaces projection - line
with edge% (model probability - book implied probability).

This replaces the old MSE-based model evaluation with a proper edge metric.
"""

import numpy as np
from scipy.stats import poisson


# ============================================================================
# SNIPPET 1: Calculate Poisson Edge% for a Single Game
# ============================================================================

def calculate_strikeout_edge_single(
    predicted_lambda: float,
    strikeout_line: float = 5.5,
    book_odds: str = "-110"
) -> dict:
    """
    Calculate edge% for a single pitcher using Poisson regression lambda.

    Args:
        predicted_lambda: Lambda from PoissonRegressor (expected strikeouts)
        strikeout_line: The line to evaluate (e.g., 5.5)
        book_odds: Odds format (e.g., "-110" for standard -110 both sides)

    Returns:
        dict with:
            - model_prob: P(strikeouts > line) from Poisson CDF
            - book_prob: Implied probability from odds
            - edge_pct: (model_prob - book_prob) * 100
            - direction: "OVER" if positive edge, "UNDER" if negative
            - confidence: Distance from 50-50 (how extreme is the bet?)
    """
    # Calculate P(strikeouts > 5.5) = P(strikeouts >= 6)
    # For Poisson: P(X > k) = 1 - P(X <= k) = 1 - CDF(k)
    prob_over = 1 - poisson.cdf(int(np.floor(strikeout_line)), predicted_lambda)

    # Implied probability from -110 odds
    # -110 means risk $110 to win $100
    # Implied prob = 110 / (110 + 100) = 0.524
    if book_odds == "-110":
        book_prob = 110 / 210  # ~0.524
    else:
        # Handle other formats as needed
        raise NotImplementedError(f"Book odds format {book_odds} not implemented")

    # Edge percentage
    edge_pct = (prob_over - book_prob) * 100

    # Confidence is distance from 50% (how confident are we?)
    # 50% confidence = 50-50 bet (neutral)
    # 70% confidence = strong conviction (strong over/under)
    confidence = np.abs(prob_over - 0.5) * 100

    return {
        'model_prob': prob_over,
        'book_prob': book_prob,
        'edge_pct': edge_pct,
        'direction': 'OVER' if edge_pct > 0 else 'UNDER',
        'confidence': confidence
    }


# ============================================================================
# SNIPPET 2: Apply Gatekeeper Filters
# ============================================================================

def apply_edge_gatekeeper(
    predictions: list,
    edge_threshold: float = 8.0,
    confidence_threshold: float = 70.0
) -> list:
    """
    Filter predictions using edge% and confidence thresholds.

    Only plays that satisfy BOTH conditions are released:
    1. |edge%| > edge_threshold (enough edge to overcome variance)
    2. confidence > confidence_threshold (high confidence in direction)

    Args:
        predictions: List of dicts with 'edge_pct' and 'confidence' keys
        edge_threshold: Minimum |edge%| to pass filter (default 8%)
        confidence_threshold: Minimum confidence % (default 70%)

    Returns:
        Filtered list of predictions that passed both gates
    """
    filtered = []

    for pred in predictions:
        # Gate 1: Must have enough edge
        if np.abs(pred['edge_pct']) <= edge_threshold:
            continue

        # Gate 2: Must have high confidence
        if pred['confidence'] <= confidence_threshold:
            continue

        # Both gates passed
        filtered.append(pred)

    return filtered


# ============================================================================
# SNIPPET 3: Vectorized Edge Calculation (for backtesting)
# ============================================================================

def calculate_edges_batch(
    lambdas: np.ndarray,
    strikeout_line: float = 5.5
) -> dict:
    """
    Vectorized edge calculation for batch of predictions.

    Args:
        lambdas: Array of predicted lambda values
        strikeout_line: The line (default 5.5)

    Returns:
        dict with arrays of model_prob, edge_pct, confidence
    """
    # Vectorized Poisson CDF
    prob_over = 1 - poisson.cdf(int(np.floor(strikeout_line)), lambdas)

    # Book probability (constant)
    book_prob = 110 / 210

    # Edge percentages
    edge_pct = (prob_over - book_prob) * 100

    # Confidence (distance from 50-50)
    confidence = np.abs(prob_over - 0.5) * 100

    return {
        'model_prob': prob_over,
        'book_prob': book_prob,
        'edge_pct': edge_pct,
        'confidence': confidence
    }


# ============================================================================
# SNIPPET 4: Gatekeeper-Filtered Prediction Pipeline
# ============================================================================

def predict_and_gate(
    pitcher_id: int,
    poisson_model,
    pitcher_features: dict,
    edge_threshold: float = 8.0,
    confidence_threshold: float = 70.0,
    strikeout_line: float = 5.5
) -> dict | None:
    """
    End-to-end pipeline: predict lambda -> calculate edge -> check gates.

    Returns None if prediction fails gatekeeper filters.

    Args:
        pitcher_id: Pitcher to predict for
        poisson_model: Trained sklearn PoissonRegressor
        pitcher_features: Feature dict/array for this pitcher
        edge_threshold: Minimum |edge%|
        confidence_threshold: Minimum confidence%
        strikeout_line: Strikeout line

    Returns:
        Prediction dict if passes gates, None otherwise
    """
    # Step 1: Predict lambda
    lambda_pred = poisson_model.predict([pitcher_features])[0]

    # Step 2: Calculate edge metrics
    edge_data = calculate_strikeout_edge_single(
        lambda_pred,
        strikeout_line=strikeout_line
    )

    # Step 3: Apply gatekeeper filters
    if (np.abs(edge_data['edge_pct']) <= edge_threshold or
        edge_data['confidence'] <= confidence_threshold):
        return None  # Did not pass gates

    # Step 4: Return gated prediction
    return {
        'pitcher_id': pitcher_id,
        'lambda': lambda_pred,
        'model_prob': edge_data['model_prob'],
        'book_prob': edge_data['book_prob'],
        'edge_pct': edge_data['edge_pct'],
        'confidence': edge_data['confidence'],
        'direction': edge_data['direction'],
        'passed_gates': True
    }


# ============================================================================
# SNIPPET 5: Backtest Metrics (Win Rate, ROI)
# ============================================================================

def calculate_backtest_metrics(
    predictions: list,
    actual_strikeouts: np.ndarray,
    strikeout_line: float = 5.5,
    odds: str = "-110"
) -> dict:
    """
    Calculate backtest metrics for gated predictions.

    Args:
        predictions: List of predictions with 'model_prob', 'edge_pct'
        actual_strikeouts: Array of actual strikeout counts
        strikeout_line: Line used
        odds: Betting odds ("-110" standard)

    Returns:
        dict with win_rate, roi, profit, etc.
    """
    if not predictions:
        return {
            'num_plays': 0,
            'win_rate': None,
            'roi': None,
            'reason': 'No predictions passed gatekeeper filters'
        }

    num_plays = len(predictions)
    wins = 0
    losses = 0

    for i, pred in enumerate(predictions):
        # Determine if prediction was correct
        predicted_over = pred['model_prob'] > 0.5
        actual_over = actual_strikeouts[i] > strikeout_line

        if predicted_over == actual_over:
            wins += 1
        else:
            losses += 1

    # Win rate as percentage
    win_rate = (wins / num_plays) * 100

    # ROI calculation (assuming -110 odds)
    # Win: risk $110 to win $100 -> profit $100
    # Loss: risk $110, lose -> profit -$110
    profit_per_win = 100
    loss_per_loss = 110
    total_profit = (wins * profit_per_win) - (losses * loss_per_loss)
    total_wagered = num_plays * 110

    roi = (total_profit / total_wagered) * 100 if total_wagered > 0 else 0

    return {
        'num_plays': num_plays,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'roi': roi,
        'total_wagered': total_wagered,
        'total_profit': total_profit,
        'avg_edge_pct': np.mean([p['edge_pct'] for p in predictions])
    }


# ============================================================================
# SNIPPET 6: Example Usage
# ============================================================================

if __name__ == '__main__':
    # Example: Single prediction
    print("=" * 70)
    print("EXAMPLE 1: Single Game Edge Calculation")
    print("=" * 70)

    lambda_pred = 6.2  # Poisson regression predicts 6.2 expected Ks
    edge_info = calculate_strikeout_edge_single(lambda_pred, strikeout_line=5.5)

    print(f"\nPitcher predicted lambda: {lambda_pred:.2f}")
    print(f"  P(Over 5.5): {edge_info['model_prob']:.3f}")
    print(f"  Book implied: {edge_info['book_prob']:.3f}")
    print(f"  Edge%: {edge_info['edge_pct']:+.2f}%")
    print(f"  Confidence: {edge_info['confidence']:.1f}%")
    print(f"  Direction: {edge_info['direction']}")

    # Check gatekeeper
    passes_edge = np.abs(edge_info['edge_pct']) > 8.0
    passes_confidence = edge_info['confidence'] > 70.0

    print(f"\nGatekeeper checks:")
    print(f"  |edge%| > 8.0? {passes_edge} ({edge_info['edge_pct']:+.2f}%)")
    print(f"  confidence > 70%? {passes_confidence} ({edge_info['confidence']:.1f}%)")
    print(f"  RELEASE PLAY? {passes_edge and passes_confidence}")

    # Example: Batch edge calculation
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Vectorized Edge Calculation")
    print("=" * 70)

    lambdas = np.array([4.2, 5.8, 6.5, 3.1, 7.2])
    edges = calculate_edges_batch(lambdas)

    print(f"\nBatch of 5 predictions:")
    for i, lam in enumerate(lambdas):
        print(f"  [{i+1}] lambda={lam:.1f} -> "
              f"P(Over)={edges['model_prob'][i]:.3f}, "
              f"edge={edges['edge_pct'][i]:+.2f}%, "
              f"conf={edges['confidence'][i]:.0f}%")

    # Example: Gatekeeper filter
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Gatekeeper Filter Application")
    print("=" * 70)

    predictions = [
        {'edge_pct': edge, 'confidence': conf}
        for edge, conf in zip(edges['edge_pct'], edges['confidence'])
    ]

    filtered = apply_edge_gatekeeper(predictions, edge_threshold=8.0, confidence_threshold=70.0)

    print(f"\nStarting predictions: {len(predictions)}")
    print(f"Passed filters (|edge%|>8.0, conf>70%): {len(filtered)}")
    if filtered:
        for pred in filtered:
            print(f"  -> {pred['edge_pct']:+.2f}% edge, {pred['confidence']:.0f}% confidence")
    else:
        print("  -> None passed filters")

    # Example: Backtest metrics
    print("\n" + "=" * 70)
    print("EXAMPLE 4: Backtest Metrics")
    print("=" * 70)

    if filtered:
        # Simulate actual results
        actual = np.array([6, 4, 7])  # Actual strikeouts
        metrics = calculate_backtest_metrics(filtered, actual[:len(filtered)])

        print(f"\nBacktest Results:")
        print(f"  Plays: {metrics['num_plays']}")
        print(f"  Wins: {metrics['wins']}")
        print(f"  Losses: {metrics['losses']}")
        print(f"  Win Rate: {metrics['win_rate']:.1f}%")
        print(f"  ROI: {metrics['roi']:+.1f}%")
        print(f"  Profit: ${metrics['total_profit']}")
