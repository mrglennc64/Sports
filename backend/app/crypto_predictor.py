"""Crypto Event Predictor: XGBoost-based prediction of Bitcoin price targets, ETF approvals, and other crypto events.

Data sources:
  - CoinGecko API: prices, volume, market cap
  - On-chain metrics: whale transfers, exchange flows, active addresses
  - Options market: IV, put/call ratio, implied volatility
  - News sentiment: aggregated sentiment scores
  - Polymarket: market-derived probability benchmarks

Model: XGBoost trained to predict:
  - P(Bitcoin > $150k by Dec)
  - P(Ethereum ETF approved)
  - P(Solana > $300)
  - Other defined crypto events
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================


class CoinGeckoPriceData(BaseModel):
    """Current price, market cap, volume from CoinGecko."""
    symbol: str
    price_usd: float
    market_cap_usd: float
    volume_24h_usd: float
    price_change_24h: float
    price_change_7d: float
    price_change_30d: float
    all_time_high: float
    all_time_low: float


class OnChainMetrics(BaseModel):
    """On-chain activity metrics."""
    symbol: str
    active_addresses: int | None = None
    transaction_volume: float | None = None
    whale_transfers_24h: int | None = None
    exchange_inflow: float | None = None
    exchange_outflow: float | None = None
    large_transaction_count: int | None = None
    miner_revenue_usd: float | None = None


class OptionsMarketData(BaseModel):
    """Options market indicators."""
    symbol: str
    implied_volatility: float | None = None
    put_call_ratio: float | None = None
    call_oi: float | None = None
    put_oi: float | None = None
    skew: float | None = None


class NewsSentiment(BaseModel):
    """Aggregated news sentiment."""
    symbol: str
    sentiment_score: float = Field(0.0, ge=-1, le=1, description="[-1, 1] where -1 is very negative; 0 = neutral default when no signal")
    article_count_24h: int = 0
    mentions_24h: int = 0
    trending: bool = False


class PolymarketData(BaseModel):
    """Market-derived pricing from prediction markets."""
    event: str
    implied_probability: float = Field(..., ge=0, le=1)
    volume_24h: float
    liquidity: float
    yes_price: float = Field(..., ge=0, le=1)
    no_price: float = Field(..., ge=0, le=1)


class CryptoEventPrediction(BaseModel):
    """Prediction output for a crypto event."""
    event: str
    predicted_probability: float = Field(..., ge=0, le=1, description="Model-predicted probability")
    confidence: float = Field(..., ge=0, le=1, description="Confidence in the prediction")
    polymarket_probability: float | None = Field(None, ge=0, le=1, description="Market reference probability")
    edge: float | None = Field(None, description="Predicted_prob - market_prob (bookmaker edge)")
    key_factors: dict[str, float] = Field(default_factory=dict, description="Feature importance breakdown")
    updated_at: str


@dataclass
class PredictionResult:
    """Full result set for a crypto event prediction request."""
    event: str
    predictions: list[CryptoEventPrediction]
    timestamp: str
    data_quality: float = Field(default=1.0, description="[0, 1] indicator of data completeness")


# =============================================================================
# API Clients
# =============================================================================


class CoinGeckoClient:
    """Fetch price and market data from CoinGecko free API."""

    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=10.0)

    async def get_price_data(self, coin_id: str) -> CoinGeckoPriceData:
        """Fetch current price, market cap, volume for a coin."""
        try:
            url = f"{self.BASE_URL}/simple/data"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
                "include_24hr_change": "true",
                "include_ath": "true",
                "include_atl": "true"
            }
            resp = await self.client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            coin_data = data.get(coin_id, {})
            usd_data = coin_data.get("usd", {})

            return CoinGeckoPriceData(
                symbol=coin_id.upper(),
                price_usd=float(usd_data.get("usd", 0)),
                market_cap_usd=float(usd_data.get("usd_market_cap", 0)),
                volume_24h_usd=float(usd_data.get("usd_24h_vol", 0)),
                price_change_24h=float(usd_data.get("usd_24h_change", 0)),
                price_change_7d=float(usd_data.get("usd_7d_change", 0)) if "usd_7d_change" in usd_data else 0,
                price_change_30d=float(usd_data.get("usd_30d_change", 0)) if "usd_30d_change" in usd_data else 0,
                all_time_high=float(usd_data.get("usd_ath", 0)),
                all_time_low=float(usd_data.get("usd_atl", 0)),
            )
        except Exception as e:
            logger.error(f"CoinGecko API error for {coin_id}: {e}")
            raise

    async def get_historical_prices(
        self, coin_id: str, days: int = 30
    ) -> pd.DataFrame:
        """Fetch historical daily prices for technical indicators."""
        try:
            url = f"{self.BASE_URL}/coins/{coin_id}/market_chart"
            params = {"vs_currency": "usd", "days": days}
            resp = await self.client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            prices = data.get("prices", [])
            df = pd.DataFrame(prices, columns=["timestamp", "price"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

            return df
        except Exception as e:
            logger.error(f"CoinGecko historical error for {coin_id}: {e}")
            raise


class OnChainDataClient:
    """Fetch on-chain metrics. In production, integrate with Glassnode, IntoTheBlock, or Nansen."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=10.0)

    async def get_metrics(self, symbol: str) -> OnChainMetrics:
        """Fetch on-chain metrics for a symbol."""
        # Placeholder: In production, call actual on-chain data providers.
        # Examples:
        #   - Glassnode API (whale transactions, exchange flows, active addresses)
        #   - IntoTheBlock (large transaction detection)
        #   - Nansen (wallet labeling, fund flows)

        logger.info(f"Fetching on-chain metrics for {symbol}")

        # Return synthetic data for now; replace with real API calls.
        return OnChainMetrics(
            symbol=symbol,
            active_addresses=1_000_000,  # Mock
            whale_transfers_24h=42,  # Mock
            exchange_inflow=500.0,  # Mock BTC
            exchange_outflow=300.0,  # Mock BTC
            large_transaction_count=128,  # Mock
        )


class OptionsMarketDataClient:
    """Fetch options market data (IV, put/call ratio, skew)."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=10.0)

    async def get_options_data(self, symbol: str) -> OptionsMarketData:
        """Fetch options market indicators."""
        # Placeholder: In production, integrate with:
        #   - Deribit (crypto options largest venue)
        #   - CBOE (traditional options APIs)

        logger.info(f"Fetching options data for {symbol}")

        # Return synthetic data; replace with real API calls.
        return OptionsMarketData(
            symbol=symbol,
            implied_volatility=0.65,  # Mock 65% annualized IV
            put_call_ratio=0.85,  # Mock
            call_oi=10_000.0,  # Mock BTC open interest
            put_oi=12_000.0,  # Mock BTC open interest
            skew=0.05,  # Mock positive skew
        )


class NewsSentimentClient:
    """Fetch and analyze news sentiment for crypto assets."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=10.0)

    async def get_sentiment(self, symbol: str) -> NewsSentiment:
        """Aggregate news sentiment across sources."""
        # Placeholder: In production, integrate with:
        #   - CryptoNews sentiment feeds
        #   - Twitter/X Firehose (with sentiment NLP)
        #   - Coin Bureau, CoinTelegraph RSS

        logger.info(f"Fetching news sentiment for {symbol}")

        # Return synthetic data; replace with real sentiment aggregation.
        return NewsSentiment(
            symbol=symbol,
            sentiment_score=0.35,  # Mock: slightly positive
            article_count_24h=47,
            mentions_24h=1230,
            trending=True,
        )


class PolymarketClient:
    """Fetch event probabilities from Polymarket (decentralized prediction market)."""

    BASE_URL = "https://clob.polymarket.com"

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=10.0)

    async def get_event_probability(self, event_id: str) -> PolymarketData | None:
        """Fetch market-implied probability for a Polymarket event."""
        try:
            # Polymarket API endpoint
            url = f"{self.BASE_URL}/markets"
            resp = await self.client.get(url)
            resp.raise_for_status()

            # Parse and find matching event
            # Actual implementation would search by event_id
            logger.info(f"Fetching Polymarket data for event {event_id}")

            return None  # Placeholder
        except Exception as e:
            logger.error(f"Polymarket API error: {e}")
            return None


# =============================================================================
# Feature Engineering
# =============================================================================


def engineer_features(
    price_data: CoinGeckoPriceData,
    historical_prices: pd.DataFrame,
    onchain: OnChainMetrics,
    options: OptionsMarketData,
    sentiment: NewsSentiment,
) -> dict[str, float]:
    """Engineer features for the XGBoost model."""

    features = {}

    # Price-based features
    features["price"] = price_data.price_usd
    features["market_cap"] = price_data.market_cap_usd
    features["volume_24h"] = price_data.volume_24h_usd
    features["price_change_24h"] = price_data.price_change_24h
    features["price_change_7d"] = price_data.price_change_7d
    features["price_change_30d"] = price_data.price_change_30d

    # Volatility (technical)
    if not historical_prices.empty:
        returns = historical_prices["price"].pct_change()
        features["volatility_30d"] = returns.std() * np.sqrt(365)
        features["sma_7"] = historical_prices["price"].tail(7).mean()
        features["sma_30"] = historical_prices["price"].tail(30).mean()
    else:
        features["volatility_30d"] = 0.0
        features["sma_7"] = price_data.price_usd
        features["sma_30"] = price_data.price_usd

    # On-chain features
    features["whale_transfers_24h"] = onchain.whale_transfers_24h or 0
    features["exchange_flow_net"] = (onchain.exchange_inflow or 0) - (onchain.exchange_outflow or 0)

    # Options market features
    features["implied_volatility"] = options.implied_volatility or 0.5
    features["put_call_ratio"] = options.put_call_ratio or 1.0

    # Sentiment features
    features["sentiment_score"] = sentiment.sentiment_score
    features["mention_velocity"] = sentiment.mentions_24h / max(sentiment.article_count_24h, 1)
    features["trending"] = float(sentiment.trending)

    return features


# =============================================================================
# XGBoost Model (Stubs for integration)
# =============================================================================


class CryptoEventModel:
    """XGBoost model for crypto event prediction."""

    def __init__(self, model_path: str | None = None):
        """Initialize model from path or with defaults."""
        self.model_path = model_path
        self.model = None
        self.feature_names = [
            "price", "market_cap", "volume_24h",
            "price_change_24h", "price_change_7d", "price_change_30d",
            "volatility_30d", "sma_7", "sma_30",
            "whale_transfers_24h", "exchange_flow_net",
            "implied_volatility", "put_call_ratio",
            "sentiment_score", "mention_velocity", "trending"
        ]

        if model_path:
            self._load_model()
        else:
            self._init_default_model()

    def _init_default_model(self):
        """Initialize with a simple stub model."""
        # In production, train on historical crypto event outcomes
        logger.info("Initializing default XGBoost model (stub)")
        # xgb.XGBClassifier(objective="binary:logistic", n_estimators=100)

    def _load_model(self):
        """Load model from disk."""
        import pickle
        with open(self.model_path, "rb") as f:
            self.model = pickle.load(f)

    def predict_event(
        self,
        features: dict[str, float],
        event_type: str = "bitcoin_150k_dec"
    ) -> tuple[float, dict[str, float]]:
        """
        Predict probability and importance for a crypto event.

        Returns:
            (probability, feature_importance)
        """

        # Build feature vector in correct order
        feature_vector = np.array([features.get(name, 0.0) for name in self.feature_names]).reshape(1, -1)

        # Stub: Return synthetic prediction based on features
        # In production, call self.model.predict_proba(feature_vector)

        if event_type == "bitcoin_150k_dec":
            # Simple heuristic: higher price + positive sentiment = higher probability
            base_prob = 0.35
            if features.get("price", 0) > 100_000:
                base_prob += 0.15
            base_prob += features.get("sentiment_score", 0) * 0.10
            prob = min(1.0, max(0.0, base_prob))
        elif event_type == "ethereum_etf":
            # Ethereum spot ETF approval likelihood
            base_prob = 0.65
            base_prob += features.get("sentiment_score", 0) * 0.10
            prob = min(1.0, max(0.0, base_prob))
        elif event_type == "solana_300":
            base_prob = 0.25
            if features.get("price", 0) > 150:
                base_prob += 0.20
            prob = min(1.0, max(0.0, base_prob))
        else:
            prob = 0.5

        # Feature importance (stub)
        importance = {
            "price": abs(features.get("price", 0) / 100_000),
            "sentiment_score": abs(features.get("sentiment_score", 0.5)),
            "volatility_30d": features.get("volatility_30d", 0.5),
        }

        return prob, importance


# =============================================================================
# Main Predictor
# =============================================================================


class CryptoEventPredictor:
    """Orchestrates all data fetching and prediction."""

    # Predefined crypto events
    EVENTS = {
        "bitcoin_150k_dec": {
            "name": "Bitcoin > $150k by Dec 2026",
            "description": "Bitcoin price target",
            "symbols": ["bitcoin"],
        },
        "ethereum_etf": {
            "name": "Ethereum Spot ETF Approved",
            "description": "SEC approves spot ETF",
            "symbols": ["ethereum"],
        },
        "solana_300": {
            "name": "Solana > $300",
            "description": "Solana price target",
            "symbols": ["solana"],
        },
    }

    def __init__(
        self,
        coingecko_api_key: str | None = None,
        onchain_api_key: str | None = None,
        options_api_key: str | None = None,
        news_api_key: str | None = None,
        model_path: str | None = None,
    ):
        self.coingecko = CoinGeckoClient()
        self.onchain = OnChainDataClient(api_key=onchain_api_key)
        self.options = OptionsMarketDataClient(api_key=options_api_key)
        self.sentiment = NewsSentimentClient(api_key=news_api_key)
        self.polymarket = PolymarketClient()
        self.model = CryptoEventModel(model_path=model_path)

    async def predict_event(
        self,
        event_key: str,
        days_lookback: int = 30,
    ) -> PredictionResult:
        """Predict probability for a specific crypto event."""

        if event_key not in self.EVENTS:
            raise ValueError(f"Unknown event: {event_key}")

        event_config = self.EVENTS[event_key]
        symbols = event_config["symbols"]

        # Fetch data in parallel
        tasks = []
        for symbol in symbols:
            tasks.append(self._fetch_symbol_data(symbol, days_lookback))

        symbol_data = await asyncio.gather(*tasks)

        # Generate predictions
        predictions = []
        for symbol, data in zip(symbols, symbol_data):
            prob, importance = self.model.predict_event(data["features"], event_key)

            pred = CryptoEventPrediction(
                event=event_config["name"],
                predicted_probability=prob,
                confidence=0.75,  # Stub
                polymarket_probability=data.get("polymarket_prob"),
                edge=prob - (data.get("polymarket_prob", 0.5)) if data.get("polymarket_prob") else None,
                key_factors=importance,
                updated_at=datetime.utcnow().isoformat(),
            )
            predictions.append(pred)

        return PredictionResult(
            event=event_config["name"],
            predictions=predictions,
            timestamp=datetime.utcnow().isoformat(),
            data_quality=0.85,  # Stub
        )

    async def _fetch_symbol_data(
        self,
        symbol: str,
        days_lookback: int = 30,
    ) -> dict[str, Any]:
        """Fetch all data for a symbol."""

        try:
            # Map symbol to CoinGecko ID
            symbol_map = {
                "bitcoin": "bitcoin",
                "ethereum": "ethereum",
                "solana": "solana",
            }
            coin_id = symbol_map.get(symbol.lower(), symbol.lower())

            # Fetch all data in parallel
            tasks = [
                self.coingecko.get_price_data(coin_id),
                self.coingecko.get_historical_prices(coin_id, days=days_lookback),
                self.onchain.get_metrics(symbol),
                self.options.get_options_data(symbol),
                self.sentiment.get_sentiment(symbol),
            ]

            price_data, historical, onchain, options, sentiment = await asyncio.gather(*tasks)

            # Engineer features
            features = engineer_features(price_data, historical, onchain, options, sentiment)

            return {
                "symbol": symbol,
                "features": features,
                "price_data": price_data,
                "polymarket_prob": None,  # Would fetch from Polymarket
            }

        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")
            raise

    async def predict_all(self, days_lookback: int = 30) -> list[PredictionResult]:
        """Generate predictions for all defined events."""
        tasks = [
            self.predict_event(event_key, days_lookback)
            for event_key in self.EVENTS.keys()
        ]
        return await asyncio.gather(*tasks)


# =============================================================================
# Convenience function for async context
# =============================================================================


async def predict_crypto_event(
    event_key: str,
    coingecko_api_key: str | None = None,
    onchain_api_key: str | None = None,
    options_api_key: str | None = None,
    news_api_key: str | None = None,
    model_path: str | None = None,
) -> PredictionResult:
    """Convenience function to predict a crypto event."""

    predictor = CryptoEventPredictor(
        coingecko_api_key=coingecko_api_key,
        onchain_api_key=onchain_api_key,
        options_api_key=options_api_key,
        news_api_key=news_api_key,
        model_path=model_path,
    )

    return await predictor.predict_event(event_key)
