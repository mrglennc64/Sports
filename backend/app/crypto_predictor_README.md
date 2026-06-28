# Crypto Event Predictor

Predicts crypto events (Bitcoin price targets, ETF approvals, Solana milestones) using XGBoost and multi-source data.

## Data Sources

- **CoinGecko API** (free, 10-50 calls/min): Real-time prices, market cap, volume, price changes
- **On-chain Metrics** (placeholder - integrate with Glassnode, IntoTheBlock, Nansen):
  - Whale transfers (24h)
  - Exchange flows (inflow/outflow)
  - Active addresses
  - Large transaction count
- **Options Market** (placeholder - integrate with Deribit, CBOE):
  - Implied volatility
  - Put/call ratio
  - Call/put open interest
  - Skew
- **News Sentiment** (placeholder - integrate with CryptoNews, Twitter/X Firehose, Coin Bureau):
  - Aggregated sentiment score [-1, 1]
  - Article count (24h)
  - Mention velocity
  - Trending status
- **Polymarket** (reference only): Market-implied probabilities for validation/edge calculation

## Model

XGBoost classifier trained to predict probabilities of:
- **Bitcoin > $150k by Dec 2026** (price target)
- **Ethereum Spot ETF Approval** (regulatory milestone)
- **Solana > $300** (price target)
- *(Easily extensible to other events)*

Features engineered from all data sources:
- Price-based: current price, market cap, volume, 24h/7d/30d change
- Technical: volatility, SMAs
- On-chain: whale transfers, exchange net flow
- Options: IV, put/call ratio
- Sentiment: score, mention velocity, trending flag

## API Endpoints

### GET /verticals/crypto

List all crypto event predictions.

```bash
curl "http://localhost:8000/verticals/crypto?market=polymarket&event=bitcoin_150k_dec"
```

**Query Parameters:**
- `market` (str): Market source (`polymarket`, default)
- `event` (str, optional): Single event ID. If omitted, returns all events.

**Response:**
```json
{
  "vertical": "crypto",
  "timestamp": "2026-06-28",
  "market": "polymarket",
  "predictions": [
    {
      "event": "Bitcoin above $150k by Dec 2026",
      "model_probability": 0.62,
      "market_price": 0.48,
      "edge": 0.14,
      "confidence": 0.75,
      "key_factors": {
        "price": 0.35,
        "sentiment_score": 0.25,
        "volatility_30d": 0.15
      },
      "updated_at": "2026-06-28T14:32:10.123Z"
    }
  ]
}
```

### GET /verticals/crypto/event/{event_id}

Detailed analysis for a specific crypto event.

```bash
curl "http://localhost:8000/verticals/crypto/event/bitcoin_150k_dec"
```

**Path Parameters:**
- `event_id` (str): Event identifier (bitcoin_150k_dec, ethereum_etf, solana_300)

**Response:**
```json
{
  "event": "Bitcoin above $150k by Dec 2026",
  "timestamp": "2026-06-28T14:32:10.123Z",
  "data_quality": 0.85,
  "predictions": [
    {
      "event": "Bitcoin above $150k by Dec 2026",
      "predicted_probability": 0.62,
      "confidence": 0.75,
      "polymarket_reference": 0.48,
      "edge": 0.14,
      "key_factors": {
        "price": 0.35,
        "sentiment_score": 0.25,
        "volatility_30d": 0.15
      },
      "updated_at": "2026-06-28T14:32:10.123Z"
    }
  ]
}
```

## Python Usage

### Single Event Prediction

```python
import asyncio
from app.crypto_predictor import CryptoEventPredictor

async def predict():
    predictor = CryptoEventPredictor()
    result = await predictor.predict_event("bitcoin_150k_dec")
    
    for pred in result.predictions:
        print(f"Event: {pred.event}")
        print(f"Probability: {pred.predicted_probability:.1%}")
        print(f"Confidence: {pred.confidence:.1%}")
        if pred.edge:
            print(f"Edge vs Polymarket: {pred.edge:+.1%}")
        print(f"Key Factors: {pred.key_factors}")

asyncio.run(predict())
```

### All Events

```python
async def predict_all():
    predictor = CryptoEventPredictor()
    results = await predictor.predict_all()
    
    for result in results:
        print(f"\n{result.event}")
        print(f"Data Quality: {result.data_quality:.1%}")
        for pred in result.predictions:
            print(f"  → {pred.event}: {pred.predicted_probability:.1%}")

asyncio.run(predict_all())
```

### With Custom API Keys

```python
predictor = CryptoEventPredictor(
    coingecko_api_key="your-key",
    onchain_api_key="glassnode-key",
    options_api_key="deribit-key",
    news_api_key="cryptonews-key",
    model_path="/path/to/xgboost_model.pkl"
)
```

## Production Deployment Checklist

- [ ] **Train XGBoost model** on historical crypto event outcomes (backtest 2yr min)
- [ ] **Integrate on-chain data providers:**
  - Glassnode API for whale transfers, exchange flows, active addresses
  - IntoTheBlock or Nansen for large transaction detection
  - On-chain alternatives: Santiment, Messari, CryptoQuant
- [ ] **Integrate options market data:**
  - Deribit API (largest crypto options venue)
  - Integrate IV surface, put/call ratios, skew
- [ ] **Implement news sentiment:**
  - CryptoNews API or similar
  - Twitter/X Firehose for mention velocity (requires enterprise access)
  - Coin Bureau, Cointelegraph RSS feeds
- [ ] **Set up Polymarket integration:**
  - CLOB API for event discovery and probability snapshots
  - Cache market probabilities for edge calculation
- [ ] **Add Kalshi integration** for economic events that affect crypto
- [ ] **Implement caching/TTL:**
  - CoinGecko responses: 1min TTL
  - On-chain metrics: 5min TTL
  - Options data: 1min TTL
  - News sentiment: 15min TTL
  - Polymarket: 5min TTL
- [ ] **Rate limiting:**
  - CoinGecko: 10-50 calls/min (free tier)
  - Deribit: 25 requests/3sec
  - Set up backoff strategy
- [ ] **Model versioning:**
  - Store XGBoost model checkpoints with date/performance metrics
  - A/B test new feature sets
  - Monitor model drift
- [ ] **Backtesting:**
  - Historical accuracy on settled events
  - Edge validation vs actual market outcomes
  - Sharpe ratio / ROI calculation
- [ ] **Monitoring:**
  - Data fetch latency per source
  - Model prediction distribution over time
  - Edge realization (predicted edge vs actual)

## Feature Engineering Details

### Price-Based Features
- **price**: Current USD price
- **market_cap**: Total market cap
- **volume_24h**: 24h trading volume
- **price_change_24h/7d/30d**: Percent change over periods
- **volatility_30d**: Annualized historical volatility
- **sma_7/sma_30**: 7/30-day simple moving averages

### On-Chain Features
- **whale_transfers_24h**: Count of large transfers in last 24h
- **exchange_flow_net**: Inflow minus outflow (negative = accumulation)

### Options Features
- **implied_volatility**: Annualized IV from options market
- **put_call_ratio**: Put OI / Call OI (>1 = bearish)

### Sentiment Features
- **sentiment_score**: Aggregated sentiment [-1, 1]
- **mention_velocity**: (Mentions 24h) / (Articles 24h)
- **trending**: Boolean flag

## Extending with New Events

1. Add event definition to `CryptoEventPredictor.EVENTS`:
```python
EVENTS = {
    "your_event_key": {
        "name": "Your Event Name",
        "description": "Description",
        "symbols": ["bitcoin", "ethereum"],
    }
}
```

2. Retrain model on new event outcomes (or add heuristic logic to `CryptoEventModel.predict_event`)

3. The pipeline automatically fetches data and generates predictions.

## Edge Calculation

```
Edge = Model Probability - Market Reference Probability

If edge > 0.03 (3%), typically worth wagering.
If market is efficient, expected edge converges to zero over time.
```

Polymarket serves as the market reference. If edge > 0, the model is bullish relative to the market.

## Error Handling

- **Data fetch failures**: Logged and propagated as HTTPException (500)
- **Invalid event ID**: HTTPException (400)
- **API rate limits**: Graceful degradation with retry backoff (stub)
- **Incomplete data**: `data_quality` score reflects completeness [0, 1]

## Testing

```bash
# Run crypto predictor tests
pytest tests/test_crypto_predictor.py -v

# Test specific event
pytest tests/test_crypto_predictor.py::test_bitcoin_prediction -v
```

## License

MIT
