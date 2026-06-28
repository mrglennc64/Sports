# Crypto Event Predictor - Deployment Guide

Complete deployment and production checklist for the Crypto Event Predictor system.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (React)                        │
│  - CryptoVertical.jsx: Cards, detail modal, confidence bar   │
│  - Fetch from /api/verticals/crypto                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Backend                            │
│  - GET /verticals/crypto: List all events                    │
│  - GET /verticals/crypto/event/{id}: Detail for single event │
│  - Async orchestration of data fetches                       │
└──────────────────────────┬──────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
   ┌─────────────┐  ┌────────────┐  ┌──────────────┐
   │ CoinGecko   │  │ On-chain   │  │ Options +    │
   │ (Real: v3)  │  │ (Stub →    │  │ Sentiment    │
   │             │  │ Glassnode) │  │ (Stub)       │
   └─────────────┘  └────────────┘  └──────────────┘
        │                │                  │
        └────────────────┼──────────────────┘
                         │
                         ▼
            ┌──────────────────────────┐
            │  Feature Engineering     │
            │  (Prices, on-chain,      │
            │   options, sentiment)    │
            └──────────────┬───────────┘
                           │
                           ▼
            ┌──────────────────────────┐
            │   XGBoost Model          │
            │   (Trained on outcomes)  │
            └──────────────┬───────────┘
                           │
                           ▼
            ┌──────────────────────────┐
            │  Probability + Edge      │
            │  vs Polymarket           │
            └──────────────────────────┘
```

## 1. Development Setup

### 1.1 Clone & Install

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
pip install pytest pytest-asyncio  # For testing
```

### 1.2 Environment Variables

Create `.env` in `backend/`:

```env
# Optional API keys
COINGECKO_API_KEY=
GLASSNODE_API_KEY=
DERIBIT_API_KEY=
CRYPTONEWS_API_KEY=
POLYMARKET_API_KEY=

# Model path (optional)
CRYPTO_MODEL_PATH=./models/crypto_xgboost.pkl

# Cache settings
CRYPTO_CACHE_TTL_SECONDS=300
```

### 1.3 Run Backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Test the endpoint:
```bash
curl "http://localhost:8000/verticals/crypto"
```

### 1.4 Run Frontend

```bash
cd frontend
npm install
npm run dev  # Vite dev server on http://localhost:5173
```

## 2. API Integration Roadmap

### Phase 1: CoinGecko (Production)
**Status:** DONE (integrated, free tier)
- Real-time prices, market cap, volume
- 10-50 calls/min rate limit
- No auth required for free API

**Next:** Test with multiple symbols
```bash
curl "https://api.coingecko.com/api/v3/coins/bitcoin,ethereum,solana?vs_currencies=usd"
```

### Phase 2: On-Chain Metrics (Stub → Integration)
**Current:** Synthetic data (placeholder)
**Goal:** Real on-chain metrics

**Option A: Glassnode** (recommended)
- Whale transfers, exchange flows, active addresses
- Sign up: https://glassnode.com/
- API docs: https://docs.glassnode.com/

```python
# Example Glassnode integration
import httpx

async def get_glassnode_metrics(symbol: str, api_key: str) -> OnChainMetrics:
    async with httpx.AsyncClient() as client:
        # Whale transfers
        resp = await client.get(
            "https://api.glassnode.com/v1/metrics/transactions/large_tx_count",
            params={
                "a": f"{symbol.lower()}",
                "api_key": api_key,
            }
        )
        data = resp.json()
        # Parse and return OnChainMetrics
```

**Option B: Santiment** (alternative)
- Social signals + on-chain
- API: https://santiment.net/

**Option C: CryptoQuant** (alternative)
- Exchange flows, miner revenue
- API: https://www.cryptoquant.com/

### Phase 3: Options Market Data (Stub → Deribit)
**Current:** Synthetic IV and put/call ratio
**Goal:** Real options market data

**Deribit** (largest crypto options venue)
- Free public API (no auth needed for historical)
- WebSocket for real-time
- API docs: https://docs.deribit.com/

```python
async def get_deribit_options(symbol: str) -> OptionsMarketData:
    async with httpx.AsyncClient() as client:
        # Fetch instrument data
        resp = await client.get(
            "https://www.deribit.com/api/v2/public/get_instruments",
            params={"currency": symbol.upper(), "kind": "option"}
        )
        instruments = resp.json()["result"]
        
        # Calculate IV, skew, put/call ratio
        # ...
```

### Phase 4: News Sentiment (Stub → Real Aggregation)
**Current:** Synthetic sentiment scores
**Goal:** Real sentiment from crypto news sources

**Option A: CryptoNews API**
- RSS feeds + sentiment
- Sign up: https://www.cryptonewsapi.com/

**Option B: Twitter/X Firehose + NLP**
- Requires enterprise access
- Use Tweepy + TextBlob or huggingface transformers

**Option C: Self-hosted Reddit/Discord scraper**
- Parse crypto communities
- Use VADER sentiment analyzer

### Phase 5: Polymarket Integration (Reference)
**Current:** None (optional)
**Goal:** Fetch market-implied probabilities for validation

```python
async def get_polymarket_probability(event_id: str) -> float:
    async with httpx.AsyncClient() as client:
        # CLOB API
        resp = await client.get(
            "https://clob.polymarket.com/markets",
            params={"search": event_id}
        )
        markets = resp.json()
        # Return market yes_price as probability
```

## 3. Model Training

### 3.1 Data Collection

Collect historical outcomes for at least 2 years:
- Bitcoin > price targets (daily snapshots)
- Ethereum ETF approval status (binary)
- Solana milestones (binary)

Store in CSV:
```csv
date,event,price,market_cap,volume_24h,whale_transfers_24h,implied_vol,sentiment,outcome
2024-06-01,bitcoin_150k,45000,900e9,25e9,50,0.60,0.35,0
2024-06-02,bitcoin_150k,46000,920e9,27e9,48,0.62,0.40,0
...
```

### 3.2 Train XGBoost

```python
import xgboost as xgb
import pickle

# Load data
df = pd.read_csv("crypto_events_historical.csv")

# Features and target
X = df[[
    "price", "market_cap", "volume_24h",
    "whale_transfers_24h", "implied_vol", "sentiment",
    # ... all engineered features
]]
y = df["outcome"]

# Train
model = xgb.XGBClassifier(
    objective="binary:logistic",
    n_estimators=100,
    max_depth=6,
    learning_rate=0.1,
    subsample=0.8,
)
model.fit(X, y, eval_set=[(X, y)], verbose=False)

# Save
with open("crypto_xgboost.pkl", "wb") as f:
    pickle.dump(model, f)

# Feature importance
import matplotlib.pyplot as plt
xgb.plot_importance(model)
plt.show()
```

### 3.3 Load Model in Predictor

```python
predictor = CryptoEventPredictor(
    model_path="/path/to/crypto_xgboost.pkl"
)
```

## 4. Caching Strategy

Implement TTL caching to reduce API calls:

```python
from functools import lru_cache
import time

class CachedCoinGeckoClient(CoinGeckoClient):
    def __init__(self, ttl_seconds=300):
        super().__init__()
        self.cache = {}
        self.ttl = ttl_seconds
    
    async def get_price_data(self, coin_id: str):
        key = f"price:{coin_id}"
        now = time.time()
        
        if key in self.cache:
            data, timestamp = self.cache[key]
            if now - timestamp < self.ttl:
                return data  # Return cached
        
        # Fetch fresh
        data = await super().get_price_data(coin_id)
        self.cache[key] = (data, now)
        return data
```

TTL recommendations:
- CoinGecko prices: **1 min** (update frequently)
- On-chain metrics: **5 min** (update hourly)
- Options data: **1 min** (update frequently)
- News sentiment: **15 min** (update hourly)
- Polymarket: **5 min** (update hourly)

## 5. Error Handling & Resilience

### 5.1 Retry Logic

```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
async def fetch_with_retry(url: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
```

### 5.2 Graceful Degradation

If a data source fails, use synthetic/default values:

```python
async def _fetch_symbol_data(self, symbol: str):
    try:
        price_data = await self.coingecko.get_price_data(symbol)
    except Exception as e:
        logger.warn(f"CoinGecko failed: {e}, using defaults")
        price_data = CoinGeckoPriceData(
            symbol=symbol,
            price_usd=50000,  # Sensible default
            market_cap_usd=1e12,
            # ...
        )
    # ... continue with other data sources
```

### 5.3 Data Quality Scoring

Track data completeness:

```python
def calculate_data_quality(data_dict: dict) -> float:
    """Score [0, 1] of data completeness."""
    required_keys = [
        "price_data", "historical", "onchain", "options", "sentiment"
    ]
    available = sum(1 for k in required_keys if data_dict.get(k))
    return available / len(required_keys)
```

## 6. Monitoring & Alerts

### 6.1 Logging

```python
import logging

logger = logging.getLogger(__name__)

logger.info(f"Fetching data for {symbol}")
logger.warning(f"CoinGecko slow: {latency}ms")
logger.error(f"Deribit API error: {e}")
```

### 6.2 Metrics to Track

- **API Latency:** Per-source fetch time
- **Hit Rate:** Successful predictions / total requests
- **Model Accuracy:** Predicted prob vs actual outcomes
- **Edge Realization:** Predicted edge vs actual CLV
- **Data Quality:** Completeness score over time

### 6.3 Example Monitoring Setup

```python
from prometheus_client import Counter, Histogram

fetch_time = Histogram(
    "crypto_fetch_seconds",
    "Time to fetch data",
    ["source"]
)

prediction_accuracy = Counter(
    "crypto_predictions_accurate",
    "Count of accurate predictions",
    ["event"]
)

with fetch_time.labels(source="coingecko").time():
    await self.coingecko.get_price_data("bitcoin")
```

## 7. Database (Optional)

Store predictions for backtesting:

```sql
CREATE TABLE crypto_predictions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    event_id VARCHAR(50),
    predicted_probability FLOAT,
    polymarket_probability FLOAT,
    actual_outcome BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    settled_at TIMESTAMP,
    INDEX(event_id, created_at)
);
```

```python
async def log_prediction(
    event_key: str,
    pred: CryptoEventPrediction,
    db: Database
):
    await db.execute(
        "INSERT INTO crypto_predictions "
        "(event_id, predicted_probability, polymarket_probability, created_at) "
        "VALUES (:event_id, :pred_prob, :market_prob, NOW())",
        {
            "event_id": event_key,
            "pred_prob": pred.predicted_probability,
            "market_prob": pred.polymarket_probability,
        }
    )
```

## 8. Production Deployment

### 8.1 Docker

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/models ./models

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 8.2 Docker Compose

```yaml
version: '3.8'

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - GLASSNODE_API_KEY=${GLASSNODE_API_KEY}
      - CRYPTO_MODEL_PATH=/app/models/crypto_xgboost.pkl
    volumes:
      - ./backend/models:/app/models

  frontend:
    build: ./frontend
    ports:
      - "5173:5173"
    environment:
      - VITE_API_BASE=http://localhost:8000
```

### 8.3 Kubernetes (Advanced)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: crypto-predictor
spec:
  replicas: 3
  selector:
    matchLabels:
      app: crypto-predictor
  template:
    metadata:
      labels:
        app: crypto-predictor
    spec:
      containers:
      - name: backend
        image: crypto-predictor:latest
        ports:
        - containerPort: 8000
        env:
        - name: GLASSNODE_API_KEY
          valueFrom:
            secretKeyRef:
              name: crypto-secrets
              key: glassnode
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
```

### 8.4 Environment Configuration

```env
# Production
DEBUG=false
LOG_LEVEL=info
WORKERS=4
CRYPTO_CACHE_TTL_SECONDS=600
MAX_CONCURRENT_REQUESTS=100
```

## 9. Testing Checklist

- [ ] Unit tests pass (`pytest tests/test_crypto_predictor.py`)
- [ ] Integration tests pass (real API calls)
- [ ] Load test (1000 requests/sec with k6 or locust)
- [ ] Data quality tests (>80% completeness)
- [ ] Model accuracy on holdout set (>60% for edge cases)
- [ ] Edge realization validated (predictions profitable on historical data)
- [ ] API rate limits respected (no throttling)
- [ ] Error handling works (graceful degradation)
- [ ] Monitoring alerts configured
- [ ] Documentation complete

## 10. Go-Live Checklist

- [ ] All API keys configured in production environment
- [ ] Model trained and validated
- [ ] Caching strategy implemented
- [ ] Error handling and retries configured
- [ ] Logging and monitoring set up
- [ ] Database backed up (if using)
- [ ] Frontend deployed and tested
- [ ] CORS configured correctly
- [ ] SSL/TLS certificates installed
- [ ] Load balancer and auto-scaling configured
- [ ] Team trained on monitoring dashboards
- [ ] Incident response plan documented

## 11. Post-Launch Monitoring

Track these metrics daily:

1. **Prediction Accuracy**: % of predictions that matched outcomes (after settlement)
2. **Edge Realization**: Actual profit/loss on edge-positive predictions
3. **API Health**: Uptime, latency, error rates per source
4. **Model Drift**: Rolling accuracy on last 30 days vs historical
5. **Data Quality**: % of predictions with full data completeness

## 12. Future Enhancements

- [ ] Add more events (Bitcoin halving, Layer 2 adoption, etc.)
- [ ] Implement ensemble models (XGBoost + NN + Linear)
- [ ] Add real-time WebSocket streaming for options data
- [ ] Integrate with more on-chain providers (Nansen, Santiment)
- [ ] Add sentiment from on-chain whale addresses (wallet labels)
- [ ] Backtest against historical market data
- [ ] Implement Kelly Criterion stake sizing
- [ ] Add arbitrage detection across prediction markets
- [ ] Deploy mobile app for push notifications
- [ ] Create professional dashboard (Grafana)

## Questions?

See `crypto_predictor_README.md` for API documentation and module details.
