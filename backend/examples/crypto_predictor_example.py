#!/usr/bin/env python
"""
Example usage of the CryptoEventPredictor module.

Run with:
    python examples/crypto_predictor_example.py
"""

import asyncio
import json
from app.crypto_predictor import CryptoEventPredictor, predict_crypto_event


async def example_single_event():
    """Predict a single crypto event."""
    print("=" * 60)
    print("Example 1: Single Event Prediction")
    print("=" * 60)

    predictor = CryptoEventPredictor()

    # Predict Bitcoin > $150k by Dec 2026
    result = await predictor.predict_event("bitcoin_150k_dec")

    print(f"\nEvent: {result.event}")
    print(f"Timestamp: {result.timestamp}")
    print(f"Data Quality: {result.data_quality:.1%}")

    for pred in result.predictions:
        print(f"\n  Prediction for: {pred.event}")
        print(f"  → Model Probability: {pred.predicted_probability:.1%}")
        print(f"  → Confidence: {pred.confidence:.1%}")

        if pred.polymarket_probability is not None:
            print(f"  → Polymarket Reference: {pred.polymarket_probability:.1%}")

        if pred.edge is not None:
            edge_str = f"+{pred.edge:.1%}" if pred.edge > 0 else f"{pred.edge:.1%}"
            print(f"  → Edge vs Market: {edge_str}")

        if pred.key_factors:
            print(f"  → Key Factors:")
            for factor, importance in sorted(
                pred.key_factors.items(), key=lambda x: x[1], reverse=True
            ):
                print(f"      • {factor}: {importance:.1%}")


async def example_all_events():
    """Predict all defined events."""
    print("\n" + "=" * 60)
    print("Example 2: All Events Prediction")
    print("=" * 60)

    predictor = CryptoEventPredictor()
    results = await predictor.predict_all()

    for result in results:
        print(f"\n{result.event}")
        print(f"  Timestamp: {result.timestamp}")
        print(f"  Data Quality: {result.data_quality:.1%}")

        for pred in result.predictions:
            print(f"\n    {pred.event}")
            print(f"      Model: {pred.predicted_probability:.1%}")
            if pred.edge is not None:
                print(f"      Edge: {pred.edge:+.1%}")
            print(f"      Confidence: {pred.confidence:.1%}")


async def example_convenience_function():
    """Use the convenience function directly."""
    print("\n" + "=" * 60)
    print("Example 3: Convenience Function")
    print("=" * 60)

    result = await predict_crypto_event("ethereum_etf")

    print(f"\nEvent: {result.event}")
    for pred in result.predictions:
        print(f"  {pred.event}: {pred.predicted_probability:.1%}")


async def example_json_response():
    """Show JSON-serializable response format."""
    print("\n" + "=" * 60)
    print("Example 4: JSON Response Format")
    print("=" * 60)

    predictor = CryptoEventPredictor()
    result = await predictor.predict_event("solana_300")

    # Convert to JSON-compatible dict
    response = {
        "event": result.event,
        "timestamp": result.timestamp,
        "data_quality": result.data_quality,
        "predictions": [
            {
                "event": pred.event,
                "predicted_probability": pred.predicted_probability,
                "confidence": pred.confidence,
                "polymarket_probability": pred.polymarket_probability,
                "edge": pred.edge,
                "key_factors": pred.key_factors,
                "updated_at": pred.updated_at,
            }
            for pred in result.predictions
        ],
    }

    print(json.dumps(response, indent=2))


async def example_event_details():
    """Show detailed event information."""
    print("\n" + "=" * 60)
    print("Example 5: Event Details and Configuration")
    print("=" * 60)

    predictor = CryptoEventPredictor()

    print("\nAvailable Events:")
    for event_key, config in predictor.EVENTS.items():
        print(f"\n  {event_key}:")
        print(f"    Name: {config['name']}")
        print(f"    Description: {config['description']}")
        print(f"    Symbols: {', '.join(config['symbols'])}")


async def example_feature_breakdown():
    """Show feature engineering for a symbol."""
    print("\n" + "=" * 60)
    print("Example 6: Feature Engineering Breakdown")
    print("=" * 60)

    predictor = CryptoEventPredictor()

    # Fetch data for Bitcoin
    symbol_data = await predictor._fetch_symbol_data("bitcoin", days_lookback=30)

    print(f"\nFeatures for {symbol_data['symbol'].upper()}:")
    features = symbol_data["features"]

    # Group features by category
    price_features = {
        k: v
        for k, v in features.items()
        if k.startswith(("price", "market", "volume", "sma", "volatility"))
    }
    onchain_features = {
        k: v for k, v in features.items() if k.startswith(("whale", "exchange"))
    }
    options_features = {
        k: v for k, v in features.items() if k.startswith(("implied", "put_call"))
    }
    sentiment_features = {
        k: v for k, v in features.items() if k.startswith(("sentiment", "mention"))
    }

    print("\n  Price-based:")
    for k, v in price_features.items():
        print(f"    {k}: {v:.6g}")

    print("\n  On-chain:")
    for k, v in onchain_features.items():
        print(f"    {k}: {v:.6g}")

    print("\n  Options:")
    for k, v in options_features.items():
        print(f"    {k}: {v:.6g}")

    print("\n  Sentiment:")
    for k, v in sentiment_features.items():
        if isinstance(v, bool):
            print(f"    {k}: {v}")
        else:
            print(f"    {k}: {v:.6g}")


async def main():
    """Run all examples."""
    try:
        await example_single_event()
        await example_all_events()
        await example_convenience_function()
        await example_json_response()
        await example_event_details()
        await example_feature_breakdown()

        print("\n" + "=" * 60)
        print("All examples completed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
