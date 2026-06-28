"""Tests for the parlay evaluator and the /v2/parlay route."""

from __future__ import annotations

import asyncio
from math import prod

import pytest
from fastapi.testclient import TestClient

from app import main
from app.model.edge import american_to_decimal
from app.model.parlay import ParlayLeg, evaluate_parlay


# --------------------------------------------------------------------------- #
# Pure engine
# --------------------------------------------------------------------------- #
def test_parlay_prob_is_product_of_independent_legs():
    legs = [
        ParlayLeg("A Over 6.5", model_prob=0.6, american_odds=-110, game_id=1),
        ParlayLeg("B Over 5.5", model_prob=0.55, american_odds=-105, game_id=2),
    ]
    ev = evaluate_parlay(legs)
    assert ev.model_prob == pytest.approx(0.6 * 0.55)
    assert ev.book_decimal == pytest.approx(
        american_to_decimal(-110) * american_to_decimal(-105)
    )
    assert ev.independent is True
    assert ev.n_legs == 2


def test_positive_ev_when_model_beats_payout():
    # Two legs the model loves at plus-money -> +EV parlay.
    legs = [
        ParlayLeg("A", model_prob=0.7, american_odds=120, game_id=1),
        ParlayLeg("B", model_prob=0.7, american_odds=110, game_id=2),
    ]
    ev = evaluate_parlay(legs)
    assert ev.ev_per_unit > 0
    assert ev.positive_ev is True
    assert ev.kelly > 0


def test_negative_ev_when_vig_compounds():
    legs = [
        ParlayLeg("A", model_prob=0.5, american_odds=-110, game_id=1),
        ParlayLeg("B", model_prob=0.5, american_odds=-110, game_id=2),
    ]
    ev = evaluate_parlay(legs)
    assert ev.ev_per_unit < 0
    assert ev.positive_ev is False
    assert ev.kelly == 0.0  # no stake on a -EV bet


def test_same_game_legs_warn_and_flag_dependent():
    legs = [
        ParlayLeg("Cole Over 6.5", model_prob=0.6, american_odds=-110, game_id=777),
        ParlayLeg("Bello Under 4.5", model_prob=0.6, american_odds=-110, game_id=777),
    ]
    ev = evaluate_parlay(legs)
    assert ev.independent is False
    assert any("same game" in w for w in ev.warnings)


def test_long_parlay_variance_warning():
    legs = [ParlayLeg(f"L{i}", model_prob=0.6, american_odds=-110, game_id=i) for i in range(4)]
    ev = evaluate_parlay(legs)
    assert any("4-leg" in w for w in ev.warnings)


def test_fair_decimal_is_inverse_model_prob():
    legs = [
        ParlayLeg("A", model_prob=0.6, american_odds=-110, game_id=1),
        ParlayLeg("B", model_prob=0.5, american_odds=-110, game_id=2),
    ]
    ev = evaluate_parlay(legs)
    assert ev.fair_decimal == pytest.approx(1 / (0.6 * 0.5))


def test_empty_and_invalid_legs_raise():
    with pytest.raises(ValueError):
        evaluate_parlay([])
    with pytest.raises(ValueError):
        evaluate_parlay([ParlayLeg("bad", model_prob=1.5, american_odds=-110)])


# --------------------------------------------------------------------------- #
# Pipeline (projection -> parlay), projections stubbed
# --------------------------------------------------------------------------- #
def test_build_parlay_pulls_side_probability(monkeypatch):
    import app.parlay_pipeline as pp

    async def fake_predict(pitcher, *, line, date, client=None, settings=None):
        probs = {"Cole": 0.62, "Bello": 0.48}
        return {
            "pitcher": pitcher,
            "prob_over": probs[pitcher],
            "prob_under": 1 - probs[pitcher],
            "game_pk": 100 if pitcher == "Cole" else 200,
        }

    monkeypatch.setattr(pp, "predict_pitcher_ensemble", fake_predict)
    specs = [
        pp.LegSpec("Cole", 6.5, "over", -110),
        pp.LegSpec("Bello", 5.5, "under", -105),
    ]

    async def run():
        return await pp.build_parlay(specs, on_date="2025-06-07", client=object())

    out = asyncio.run(run())
    # Over uses prob_over (0.62); Under uses prob_under (1 - 0.48 = 0.52).
    assert out["model_prob"] == pytest.approx(0.62 * 0.52)
    assert out["n_legs"] == 2
    assert out["independent"] is True  # different game_pks


# --------------------------------------------------------------------------- #
# Route wiring
# --------------------------------------------------------------------------- #
def test_v2_parlay_route(monkeypatch):
    async def fake_build(specs, on_date, **kwargs):
        return {"n_legs": len(specs), "model_prob": 0.3, "ev_per_unit": 0.05, "positive_ev": True}

    monkeypatch.setattr(main, "build_parlay", fake_build)
    client = TestClient(main.app)
    r = client.post("/v2/parlay", json={"legs": [
        {"pitcher": "Cole", "line": 6.5, "side": "over", "odds": -110},
        {"pitcher": "Bello", "line": 5.5, "side": "under", "odds": -105},
    ]})
    assert r.status_code == 200
    assert r.json()["n_legs"] == 2


def test_v2_parlay_route_404_on_missing_pitcher(monkeypatch):
    async def fake_build(specs, on_date, **kwargs):
        raise LookupError("No probable start for 'Ghost'")

    monkeypatch.setattr(main, "build_parlay", fake_build)
    client = TestClient(main.app)
    r = client.post("/v2/parlay", json={"legs": [
        {"pitcher": "Ghost", "line": 6.5, "side": "over", "odds": -110},
    ]})
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Logging legs into the calibration pipeline (a)
# --------------------------------------------------------------------------- #
def _fake_predict_with_ids(monkeypatch):
    """Stub projections that carry pitcher_id + date (needed to settle a leg)."""
    import app.parlay_pipeline as pp

    async def fake_predict(pitcher, *, line, date, client=None, settings=None):
        meta = {"Cole": (100, 0.62), "Bello": (200, 0.48)}
        game_pk, p_over = meta[pitcher]
        return {
            "pitcher": pitcher,
            "pitcher_id": game_pk + 1,  # any stable id
            "date": date,
            "prob_over": p_over,
            "prob_under": 1 - p_over,
            "expected_ks": 6.1,
            "opponent": "OPP",
            "venue": "Park",
            "game_pk": game_pk,
            "low_confidence": False,
        }

    monkeypatch.setattr(pp, "predict_pitcher_ensemble", fake_predict)
    return pp


def test_build_parlay_logs_settleable_legs(monkeypatch, tmp_path):
    import csv

    from app.backtest.reliability import reliability_report
    from app.backtest.settle import settle_row

    pp = _fake_predict_with_ids(monkeypatch)
    log_path = tmp_path / "predictions.csv"
    monkeypatch.setattr(pp.default_settings, "predictions_log", str(log_path), raising=False)

    specs = [
        pp.LegSpec("Cole", 6.5, "over", -110, date="2026-06-07"),
        pp.LegSpec("Bello", 5.5, "under", -105, date="2026-06-07"),
    ]

    async def run():
        return await pp.build_parlay(specs, on_date="2026-06-07", client=object(), log=True)

    out = asyncio.run(run())
    assert out["legs_logged"] == 2

    rows = list(csv.DictReader(open(log_path, encoding="utf-8")))
    assert len(rows) == 2
    # Each logged leg must be settle-able and carry the chosen side's model_prob.
    over_leg = next(r for r in rows if r["side"] == "over")
    assert over_leg["bet"] == "False"  # not a flagged single bet
    assert float(over_leg["model_prob"]) == pytest.approx(0.62)
    assert over_leg["over_odds"] == "-110" and over_leg["under_odds"] == ""

    # Settle the over leg as a win (actual 8 > 6.5) -> it feeds /calibration.
    settled = settle_row(over_leg, actual_ks=8)
    assert settled is not None and settled.result == "win"
    assert settled.model_prob == pytest.approx(0.62)
    rep = reliability_report([settled])
    assert rep.n == 1  # the parlay leg is now a decided, scored prediction


def test_build_parlay_does_not_log_by_default(monkeypatch, tmp_path):
    pp = _fake_predict_with_ids(monkeypatch)
    log_path = tmp_path / "predictions.csv"
    monkeypatch.setattr(pp.default_settings, "predictions_log", str(log_path), raising=False)

    specs = [pp.LegSpec("Cole", 6.5, "over", -110, date="2026-06-07")]

    async def run():
        return await pp.build_parlay(specs, on_date="2026-06-07", client=object())

    out = asyncio.run(run())
    assert out["legs_logged"] == 0
    assert not log_path.exists()  # nothing written unless log=True
