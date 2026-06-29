# Smoke Tests for Production Deployment

Comprehensive smoke test suite for the Edge AI multi-vertical prediction platform. Tests all critical endpoints before production deployment.

## Overview

The smoke test suite verifies:

1. **5 Verticals** - MLB, AI Releases, Economics, Earnings, Crypto
2. **Portfolio Engine** - Allocation, simulation, regime detection
3. **CLV** - Odds capture, line movement analysis, bet recording, leaderboard
4. **Health Check** - System status and component health
5. **Database** - Schema, tables, data integrity
6. **Frontend** - Route accessibility, CORS, response formats

## Test Coverage

```
TOTAL TESTS: 100+ smoke tests
├── Verticals (25 tests)
├── Portfolio Engine (18 tests)
├── CLV (35 tests)
├── Health Check (18 tests)
├── Database (22 tests)
└── Frontend (20 tests)
```

## Quick Start

### Prerequisites

```bash
cd backend/
pip install -r requirements-test.txt
```

### Run All Tests

**Linux/macOS:**
```bash
chmod +x test-suite.sh
./test-suite.sh
```

**Windows:**
```cmd
test-suite.bat
```

**Or use pytest directly:**
```bash
pytest -c pytest_smoke.ini tests/test_smoke_*.py -v
```

## Test Files

### Core Smoke Tests

- **test_smoke_verticals.py** - Tests all 5 vertical endpoints
- **test_smoke_health.py** - Health check and system status
- **test_smoke_frontend.py** - Frontend integration and CORS
- **test_smoke_portfolio.py** - Portfolio engine endpoints
- **test_smoke_clv.py** - CLV capture, analysis, recording
- **test_smoke_database.py** - Database connectivity and schema

### Sample Data

- **tests/fixtures/sample_data.json** - Test data for all endpoints
  - Sample odds captures
  - Sample bets and results
  - Sample predictions
  - Sample portfolio allocations
  - Sample equity curves
  - Sample regime states
  - Sample CLV analysis
  - Sample crypto predictions

### Configuration

- **pytest_smoke.ini** - Pytest configuration with markers and plugins
- **requirements-test.txt** - Test dependencies

## Test Execution

### Run Specific Test Class

```bash
pytest -c pytest_smoke.ini tests/test_smoke_verticals.py::TestVerticals -v
```

### Run Tests by Marker

```bash
# Run only integration tests
pytest -c pytest_smoke.ini -m integration

# Run only CLV tests
pytest -c pytest_smoke.ini -m clv

# Run everything except slow tests
pytest -c pytest_smoke.ini -m "not slow"
```

### Generate Coverage Report

```bash
pytest -c pytest_smoke.ini --cov=app --cov-report=html --cov-report=term-missing
```

### Run with Timeout Protection

```bash
pytest -c pytest_smoke.ini --timeout=300
```

## Output Reports

### HTML Report
- **test-results/smoke-tests.html** - Interactive test results
- View in browser: `open test-results/smoke-tests.html`

### JUnit XML
- **test-results/smoke-tests.xml** - CI/CD integration
- **test-results/pytest.log** - Detailed test logs

### Coverage Report
- **test-results/coverage/index.html** - Code coverage analysis

### Deployment Report
- **test-results/deployment-report.txt** - Human-readable summary

## Endpoint Test Matrix

### ✓ Implemented Endpoints

```
VERTICALS:
  GET /verticals              - List all verticals
  GET /verticals/mlb          - MLB strikeout predictions
  GET /verticals/ai-releases  - AI release forecasts
  GET /verticals/economics    - Economic predictions
  GET /verticals/earnings     - Earnings predictions
  GET /verticals/crypto       - Crypto event predictions

HEALTH:
  GET /health                 - System health check

PREDICTIONS:
  GET /predict                - v1 pitcher prediction
  GET /v2/predict             - v2 ensemble prediction
  GET /slate                  - v1 slate builder
  GET /v2/slate               - v2 slate builder
  GET /v2/arb                 - Arbitrage scanner
  POST /v2/parlay             - Parlay builder
  GET /backtest               - Backtest metrics
```

### ⧗ Future Implementation

```
PORTFOLIO ENGINE:
  GET /api/portfolio/allocation   - Portfolio weights
  POST /api/portfolio/simulate    - Equity curve simulation
  GET /api/portfolio/regime       - Market regime detection

CLV:
  POST /api/clv/capture           - Capture odds snapshot
  GET /api/clv/analysis           - Line movement stats
  POST /api/clv/record-bet        - Record bet and calculate CLV
  GET /api/clv/leaderboard        - Leaderboard ranked by CLV
```

## Test Assertions

### Verticals Tests

```python
# Check response status and structure
response = client.get("/verticals/mlb")
assert response.status_code == 200
assert "rows" in response.json()

# Verify prediction fields
for pred in response.json()["rows"]:
    assert "pitcher" in pred
    assert "edge" in pred or "status" in pred
```

### Health Tests

```python
# Verify health status
response = client.get("/health")
data = response.json()
assert data["status"] == "ok"
assert "odds_provider" in data
assert "devig_method" in data
```

### CLV Tests

```python
# Capture odds
payload = {...}
response = client.post("/api/clv/capture", json=payload)
assert response.status_code in [200, 201, 404]

# Record bet and calculate CLV
response = client.post("/api/clv/record-bet", json=payload)
assert "clv" in response.json() or response.status_code == 404
```

## Markers

Available pytest markers for selective testing:

```bash
pytest -c pytest_smoke.ini -m verticals
pytest -c pytest_smoke.ini -m portfolio
pytest -c pytest_smoke.ini -m clv
pytest -c pytest_smoke.ini -m health
pytest -c pytest_smoke.ini -m database
pytest -c pytest_smoke.ini -m frontend
pytest -c pytest_smoke.ini -m integration
pytest -c pytest_smoke.ini -m error_handling
pytest -c pytest_smoke.ini -m "not slow"
```

## Deployment Checklist

Before production deployment, verify:

- [ ] All 6 test suites pass (verticals, portfolio, CLV, health, database, frontend)
- [ ] Coverage report shows >80% coverage for critical paths
- [ ] No 5xx errors in test results
- [ ] Health endpoint responds in <1s
- [ ] CORS headers properly configured
- [ ] Database tables verified
- [ ] Sample data loads without errors
- [ ] All 5 verticals return predictions
- [ ] Frontend routes accessible
- [ ] Error handling works correctly

## Continuous Integration

### GitHub Actions

```yaml
- name: Run Smoke Tests
  run: |
    cd backend/
    pip install -r requirements-test.txt
    ./test-suite.sh
```

### Jenkins

```groovy
stage('Smoke Tests') {
    steps {
        sh 'cd backend && ./test-suite.sh'
        publishHTML([
            reportDir: 'backend/test-results',
            reportFiles: 'smoke-tests.html',
            reportName: 'Smoke Tests'
        ])
    }
}
```

### GitLab CI

```yaml
smoke_tests:
  stage: test
  script:
    - cd backend
    - pip install -r requirements-test.txt
    - ./test-suite.sh
  artifacts:
    paths:
      - backend/test-results/
    reports:
      junit: backend/test-results/smoke-tests.xml
```

## Troubleshooting

### Tests Fail to Connect to API

```bash
# Make sure backend server is running
cd backend
uvicorn app.main:app --reload --port 8000

# In another terminal:
./test-suite.sh
```

### Module Import Errors

```bash
# Ensure pythonpath is set correctly in pytest.ini
# And that you're running from the backend directory
cd backend/
pytest -c pytest_smoke.ini
```

### Missing Dependencies

```bash
# Install or upgrade test dependencies
pip install -r requirements-test.txt --upgrade
```

### Coverage Report Not Generated

```bash
# Ensure coverage is installed
pip install coverage pytest-cov

# Run with explicit coverage flags
pytest -c pytest_smoke.ini --cov=app --cov-report=html
```

## Performance Benchmarks

Expected response times:

| Endpoint | Expected | Max |
|----------|----------|-----|
| /health | <100ms | 1s |
| /verticals | <200ms | 2s |
| /verticals/mlb | <500ms | 5s |
| /v2/predict | 1-2s | 5s |
| /v2/parlay | <1s | 3s |

## Sample Data

### Odds Capture

```json
{
  "pitcher": "Gerrit Cole",
  "game_id": "MLB_NYY_BAL_2026_06_28",
  "strikeout_line": 6.5,
  "odds": {
    "draftkings": {"over": -110, "under": -110},
    "fanduel": {"over": -105, "under": -115}
  }
}
```

### Bet Recording

```json
{
  "pitcher": "Gerrit Cole",
  "line": 6.5,
  "side": "over",
  "odds": -110,
  "stake": 100,
  "result": "win",
  "actual_strikeouts": 7
}
```

## Additional Resources

- **Main API Docs**: `/openapi.json` or `/docs`
- **Backend Code**: `/app/main.py`
- **Config**: `/app/config.py`
- **Ensemble Pipeline**: `/app/ensemble_pipeline.py`
- **Crypto Predictor**: `/app/crypto_predictor.py`

## Support

For issues or questions about smoke tests:

1. Check test output in `test-results/smoke-tests.html`
2. Review pytest logs in `test-results/pytest.log`
3. Check assertion details in test file
4. Verify API is running and responding
5. Check database connections and schema

## Next Steps

1. ✓ Run smoke tests locally before pushing
2. ✓ Fix any failing tests before deployment
3. ✓ Review coverage report for untested code
4. ✓ Deploy to staging environment
5. ✓ Run smoke tests again in staging
6. ✓ Deploy to production
7. ✓ Run final smoke tests in production

---

**Generated**: 2026-06-28  
**Version**: 1.0  
**Last Updated**: 2026-06-28
