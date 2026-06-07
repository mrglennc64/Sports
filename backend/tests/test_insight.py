from app.model.expected_ks import LEAGUE_AVG_K_RATE
from app.model.insight import build_insight

COMMON = dict(
    opp_k_rate=LEAGUE_AVG_K_RATE,
    park=1.0,
    expected_ks=6.0,
    line=5.5,
    min_edge=0.03,
)


def test_strong_play_for_big_edge():
    ins = build_insight(side="over", edge=0.08, kelly=0.05, low_confidence=False, **COMMON)
    assert ins.recommendation == "Strong Play"
    assert ins.confidence == "High"
    assert ins.signal == "strong"
    assert ins.stake_label == "Large"


def test_lean_for_moderate_edge():
    ins = build_insight(side="under", edge=0.035, kelly=0.015, low_confidence=False, **COMMON)
    assert ins.recommendation == "Lean"
    assert ins.stake_label == "Small"


def test_no_bet_below_threshold():
    ins = build_insight(side="over", edge=0.01, kelly=0.0, low_confidence=False, **COMMON)
    assert ins.recommendation == "No Bet"
    assert ins.stake_label == "—"
    assert any("no value" in r.lower() for r in ins.reasons)


def test_low_confidence_forces_pass():
    ins = build_insight(side="over", edge=0.20, kelly=0.05, low_confidence=True, **COMMON)
    assert ins.recommendation == "Pass"
    assert ins.confidence == "Low"
    assert any("not enough starts" in r.lower() for r in ins.reasons)


def test_context_reasons_present():
    ins = build_insight(
        side="over",
        edge=0.06,
        kelly=0.05,
        low_confidence=False,
        opp_k_rate=LEAGUE_AVG_K_RATE * 1.10,  # high-K opponent
        park=1.05,                            # K-boosting park
        expected_ks=7.5,
        line=5.5,
        min_edge=0.03,
    )
    joined = " ".join(ins.reasons).lower()
    assert "high rate" in joined
    assert "boost" in joined
    assert "above the" in joined
