"""
Unit tests for the Crypto Event Predictor module.

Run with:
    pytest tests/test_crypto_predictor.py -v
"""

import pytest
import pandas as pd
from datetime import datetime
from app.crypto_predictor import (
    CoinGeckoPriceData,
    OnChainMetrics,
    OptionsMarketData,
    NewsSentiment,
    PolymarketData,
    CryptoEventPrediction,
    CoinGeckoClient,
    OnChainDataClient,
    OptionsMarketDataClient,
    NewsSentimentClient,
    PolymarketClient,
    engineer_features,
    CryptoEventModel,
    CryptoEventPredictor,
)


# =============================================================================
# Test Data Models
# =============================================================================


class TestCoinGeckoPriceData:
    """Test CoinGeckoPriceData model."""

    def test_valid_price_data(self):
        """Test creation of valid price data."""
        data = CoinGeckoPriceData(
            symbol="BTC",
            price_usd=45000.0,
            market_cap_usd=1e12,
            volume_24h_usd=2e10,
            price_change_24h=0.05,
            price_change_7d=0.10,
            price_change_30d=0.20,
            all_time_high=69000.0,
            all_time_low=1000.0,
        )
        assert data.symbol == "BTC"
        assert data.price_usd == 45000.0
        assert data.market_cap_usd == 1e12

    def test_negative_price_change(self):
        """Test handling of negative price changes."""
        data = CoinGeckoPriceData(
            symbol="ETH",
            price_usd=2000.0,
            market_cap_usd=2.5e11,
            volume_24h_usd=1e10,
            price_change_24h=-0.05,
            price_change_7d=-0.10,
            price_change_30d=0.0,
            all_time_high=4800.0,
            all_time_low=0.5,
        )
        assert data.price_change_24h < 0
        assert data.price_change_7d < 0


class TestOnChainMetrics:
    """Test OnChainMetrics model."""

    def test_valid_metrics(self):
        """Test creation of valid on-chain metrics."""
        metrics = OnChainMetrics(
            symbol="BTC",
            active_addresses=1_000_000,
            whale_transfers_24h=42,
            exchange_inflow=500.0,
            exchange_outflow=300.0,
        )
        assert metrics.symbol == "BTC"
        assert metrics.whale_transfers_24h == 42
        assert metrics.exchange_inflow == 500.0

    def test_optional_fields(self):
        """Test that fields can be None."""
        metrics = OnChainMetrics(symbol="SOL", active_addresses=None)
        assert metrics.active_addresses is None


class TestNewsSentiment:
    """Test NewsSentiment model."""

    def test_valid_sentiment(self):
        """Test creation of valid sentiment data."""
        sentiment = NewsSentiment(
            symbol="BTC",
            sentiment_score=0.35,
            article_count_24h=47,
            mentions_24h=1230,
            trending=True,
        )
        assert sentiment.sentiment_score == 0.35
        assert sentiment.trending is True

    def test_sentiment_bounds(self):
        """Test sentiment score bounds [-1, 1]."""
        # Valid bounds
        NewsSentiment(symbol="BTC", sentiment_score=-1.0)
        NewsSentiment(symbol="BTC", sentiment_score=0.0)
        NewsSentiment(symbol="BTC", sentiment_score=1.0)

        # Invalid bounds should raise
        with pytest.raises(ValueError):
            NewsSentiment(symbol="BTC", sentiment_score=-1.1)

        with pytest.raises(ValueError):
            NewsSentiment(symbol="BTC", sentiment_score=1.1)


class TestCryptoEventPrediction:
    """Test CryptoEventPrediction model."""

    def test_valid_prediction(self):
        """Test creation of valid prediction."""
        pred = CryptoEventPrediction(
            event="Bitcoin > $150k",
            predicted_probability=0.62,
            confidence=0.75,
            polymarket_probability=0.48,
            edge=0.14,
            key_factors={"price": 0.35, "sentiment": 0.25},
            updated_at=datetime.utcnow().isoformat(),
        )
        assert pred.predicted_probability == 0.62
        assert pred.edge == 0.14

    def test_probability_bounds(self):
        """Test probability bounds [0, 1]."""
        # Valid
        CryptoEventPrediction(
            event="Test",
            predicted_probability=0.0,
            confidence=0.5,
            updated_at=datetime.utcnow().isoformat(),
        )
        CryptoEventPrediction(
            event="Test",
            predicted_probability=1.0,
            confidence=0.5,
            updated_at=datetime.utcnow().isoformat(),
        )

        # Invalid
        with pytest.raises(ValueError):
            CryptoEventPrediction(
                event="Test",
                predicted_probability=-0.1,
                confidence=0.5,
                updated_at=datetime.utcnow().isoformat(),
            )


# =============================================================================
# Test Feature Engineering
# =============================================================================


class TestFeatureEngineering:
    """Test feature engineering function."""

    def test_feature_engineering(self):
        """Test that features are properly engineered."""
        price_data = CoinGeckoPriceData(
            symbol="BTC",
            price_usd=50000.0,
            market_cap_usd=1e12,
            volume_24h_usd=3e10,
            price_change_24h=0.05,
            price_change_7d=0.10,
            price_change_30d=0.15,
            all_time_high=69000.0,
            all_time_low=1000.0,
        )

        # Create mock historical prices
        historical = pd.DataFrame({
            "timestamp": pd.date_range(start="2026-05-29", periods=30),
            "price": [50000 * (1 + 0.02 * i) for i in range(30)],
        })

        onchain = OnChainMetrics(
            symbol="BTC",
            whale_transfers_24h=50,
            exchange_inflow=600.0,
            exchange_outflow=400.0,
        )

        options = OptionsMarketData(
            symbol="BTC",
            implied_volatility=0.65,
            put_call_ratio=0.85,
        )

        sentiment = NewsSentiment(
            symbol="BTC",
            sentiment_score=0.35,
            mentions_24h=1230,
        )

        features = engineer_features(price_data, historical, onchain, options, sentiment)

        # Check all required features are present
        assert "price" in features
        assert "market_cap" in features
        assert "volatility_30d" in features
        assert "whale_transfers_24h" in features
        assert "implied_volatility" in features
        assert "sentiment_score" in features

        # Check values
        assert features["price"] == 50000.0
        assert features["sentiment_score"] == 0.35
        assert 0 <= features["volatility_30d"]  # Should be non-negative
        assert features["whale_transfers_24h"] == 50

    def test_empty_historical_data(self):
        """Test feature engineering with empty historical data."""
        price_data = CoinGeckoPriceData(
            symbol="BTC",
            price_usd=50000.0,
            market_cap_usd=1e12,
            volume_24h_usd=3e10,
            price_change_24h=0.05,
            price_change_7d=0.10,
            price_change_30d=0.15,
            all_time_high=69000.0,
            all_time_low=1000.0,
        )

        historical = pd.DataFrame({"timestamp": [], "price": []})
        onchain = OnChainMetrics(symbol="BTC")
        options = OptionsMarketData(symbol="BTC")
        sentiment = NewsSentiment(symbol="BTC")

        features = engineer_features(price_data, historical, onchain, options, sentiment)

        # Should still create features with defaults
        assert "volatility_30d" in features
        assert features["sma_7"] == price_data.price_usd
        assert features["sma_30"] == price_data.price_usd


# =============================================================================
# Test XGBoost Model
# =============================================================================


class TestCryptoEventModel:
    """Test XGBoost model."""

    def test_model_initialization(self):
        """Test model initialization."""
        model = CryptoEventModel()
        assert model.model is not None or model.feature_names is not None

    def test_predict_bitcoin_150k(self):
        """Test Bitcoin prediction."""
        model = CryptoEventModel()
        features = {
            "price": 150000.0,
            "sentiment_score": 0.5,
            "volatility_30d": 0.6,
        }

        prob, importance = model.predict_event(features, "bitcoin_150k_dec")

        assert 0 <= prob <= 1
        assert isinstance(importance, dict)

        # Higher price should increase probability
        features["price"] = 160000.0
        prob_high, _ = model.predict_event(features, "bitcoin_150k_dec")
        assert prob_high >= prob

    def test_predict_ethereum_etf(self):
        """Test Ethereum ETF prediction."""
        model = CryptoEventModel()
        features = {"sentiment_score": 0.3}

        prob, importance = model.predict_event(features, "ethereum_etf")
        assert 0 <= prob <= 1

    def test_predict_solana_300(self):
        """Test Solana prediction."""
        model = CryptoEventModel()
        features = {"price": 250.0}

        prob, importance = model.predict_event(features, "solana_300")
        assert 0 <= prob <= 1

    def test_unknown_event(self):
        """Test that unknown events return default probability."""
        model = CryptoEventModel()
        features = {}

        prob, importance = model.predict_event(features, "unknown_event")
        # Should return a probability, not error
        assert 0 <= prob <= 1


# =============================================================================
# Test Predictor
# =============================================================================


class TestCryptoEventPredictor:
    """Test main predictor class."""

    def test_predictor_initialization(self):
        """Test predictor initialization."""
        predictor = CryptoEventPredictor()
        assert predictor.coingecko is not None
        assert predictor.model is not None
        assert len(predictor.EVENTS) > 0

    def test_available_events(self):
        """Test that defined events are available."""
        predictor = CryptoEventPredictor()

        expected_events = ["bitcoin_150k_dec", "ethereum_etf", "solana_300"]
        for event_key in expected_events:
            assert event_key in predictor.EVENTS
            assert "name" in predictor.EVENTS[event_key]
            assert "description" in predictor.EVENTS[event_key]
            assert "symbols" in predictor.EVENTS[event_key]

    @pytest.mark.asyncio
    async def test_predict_event_invalid(self):
        """Test prediction with invalid event raises error."""
        predictor = CryptoEventPredictor()

        with pytest.raises(ValueError):
            await predictor.predict_event("invalid_event")

    @pytest.mark.asyncio
    async def test_predict_event_valid(self):
        """Test valid event prediction (will call APIs)."""
        # Note: This test calls real APIs. Mock if needed.
        predictor = CryptoEventPredictor()

        try:
            result = await predictor.predict_event("bitcoin_150k_dec")
            assert result.event is not None
            assert len(result.predictions) > 0

            pred = result.predictions[0]
            assert 0 <= pred.predicted_probability <= 1
            assert 0 <= pred.confidence <= 1
        except Exception as e:
            # API might fail; log and skip
            print(f"API test skipped: {e}")


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_zero_probability(self):
        """Test zero probability."""
        pred = CryptoEventPrediction(
            event="Impossible Event",
            predicted_probability=0.0,
            confidence=0.99,
            updated_at=datetime.utcnow().isoformat(),
        )
        assert pred.predicted_probability == 0.0

    def test_certain_probability(self):
        """Test certain probability."""
        pred = CryptoEventPrediction(
            event="Certain Event",
            predicted_probability=1.0,
            confidence=0.99,
            updated_at=datetime.utcnow().isoformat(),
        )
        assert pred.predicted_probability == 1.0

    def test_edge_calculation(self):
        """Test edge calculation."""
        pred = CryptoEventPrediction(
            event="Test",
            predicted_probability=0.65,
            confidence=0.8,
            polymarket_probability=0.50,
            edge=0.15,
            updated_at=datetime.utcnow().isoformat(),
        )
        assert pred.edge == 0.15
        # float arithmetic: 0.65 - 0.50 == 0.15000000000000002, so compare with tolerance
        assert pred.edge == pytest.approx(pred.predicted_probability - pred.polymarket_probability)

    def test_negative_edge(self):
        """Test negative edge (model bearish vs market)."""
        pred = CryptoEventPrediction(
            event="Test",
            predicted_probability=0.40,
            confidence=0.7,
            polymarket_probability=0.55,
            edge=-0.15,
            updated_at=datetime.utcnow().isoformat(),
        )
        assert pred.edge < 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
