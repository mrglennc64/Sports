"""Tests for the hedge-an-existing-position calculator (and /v2/hedge)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.model.hedge import hedge_existing_position


def test_hedge_locks_profit_when_prices_form_cross_time_arb():
    # Early Under at +115 (dec 2.15); Over now +105 (dec 2.05).
    # 1/2.15 + 1/2.05 = 0.953 < 1 -> a real lock exists.
    r = hedge_existing_position(45.45, 115, 105)
    assert r.risk_free is True
    assert r.locked_profit > 0
    # Equal-payout hedge: returns match within rounding on either outcome.
    assert r.locked_return == pytest.approx(r.initial_stake * 2.15, rel=1e-3)
    # Net on the hedge side also equals locked_return.
    assert r.hedge_stake * 2.05 == pytest.approx(r.locked_return, rel=1e-3)


def test_hedge_reports_capped_loss_when_no_arb():
    # Both sides at -110 (dec ~1.909): 1/1.909 * 2 = 1.048 > 1 -> no free money.
    r = hedge_existing_position(100, -110, -110)
    assert r.risk_free is False
    assert r.locked_profit < 0          # honestly a capped loss, not profit
    assert r.hedge_stake > 0            # still computes the equalising stake


def test_hedge_rejects_nonpositive_stake():
    with pytest.raises(ValueError):
        hedge_existing_position(0, 115, 105)


def test_hedge_route():
    client = TestClient(main.app)
    r = client.get("/v2/hedge", params={"stake": 45.45, "odds": 115, "hedge_odds": 105})
    assert r.status_code == 200
    body = r.json()
    assert body["risk_free"] is True
    assert body["locked_profit"] > 0
    assert body["hedge_stake"] > 0
