import pytest

from app.model import edge


def test_american_decimal_roundtrip():
    for a in (-200, -110, +100, +150, +250):
        d = edge.american_to_decimal(a)
        assert edge.decimal_to_american(d) == pytest.approx(a, rel=1e-9)


def test_american_to_decimal_known():
    assert edge.american_to_decimal(+100) == pytest.approx(2.0)
    assert edge.american_to_decimal(-200) == pytest.approx(1.5)
    assert edge.american_to_decimal(+150) == pytest.approx(2.5)


def test_implied_prob_known():
    assert edge.implied_prob(+100) == pytest.approx(0.5)
    assert edge.implied_prob(-200) == pytest.approx(1 / 1.5)


def test_prob_to_american_roundtrip():
    assert edge.prob_to_american(0.5) == pytest.approx(100.0)
    p = 0.6
    assert edge.implied_prob(edge.prob_to_american(p)) == pytest.approx(p)


def test_devig_balanced_market_is_fifty_fifty():
    # -110 / -110 is the classic balanced market; de-vigged it is ~50/50.
    p_over, p_under = edge.devig_two_way(-110, -110)
    assert p_over == pytest.approx(0.5)
    assert p_under == pytest.approx(0.5)
    assert p_over + p_under == pytest.approx(1.0)


def test_devig_sums_to_one_unbalanced():
    p_a, p_b = edge.devig_two_way(-150, +130)
    assert p_a + p_b == pytest.approx(1.0)
    assert p_a > p_b  # favourite has higher probability


def test_devig_removes_vig_overstatement():
    # Raw implied probs sum to > 1 (the vig); de-vig must reduce each side.
    raw_over = edge.implied_prob(-110)
    p_over, _ = edge.devig_two_way(-110, -110)
    assert raw_over > 0.5  # raw is inflated
    assert p_over < raw_over  # de-vig corrects it down


def test_shin_symmetric_matches_proportional():
    # On a balanced market Shin and proportional agree (both 50/50).
    p_over, p_under = edge.devig_two_way(-110, -110, method="shin")
    assert p_over == pytest.approx(0.5, abs=1e-6)
    assert p_under == pytest.approx(0.5, abs=1e-6)


def test_shin_sums_to_one_and_differs_when_lopsided():
    prop = edge.devig_two_way(-300, +240, method="proportional")
    shin = edge.devig_two_way(-300, +240, method="shin")
    assert sum(shin) == pytest.approx(1.0, abs=1e-6)
    # Shin corrects favourite-longshot bias, so it should not be identical to
    # the proportional split on a lopsided market.
    assert abs(shin[0] - prop[0]) > 1e-4


def test_devig_unknown_method_raises():
    with pytest.raises(ValueError):
        edge.devig_two_way(-110, -110, method="bogus")


def test_kelly_zero_at_fair_odds():
    # At fair +100 odds with true prob 0.5, Kelly is exactly 0 (no edge).
    assert edge.kelly_fraction(0.5, +100) == pytest.approx(0.0)


def test_kelly_positive_with_edge():
    # True prob 0.6 at +100 -> f* = (1*0.6 - 0.4)/1 = 0.2
    assert edge.kelly_fraction(0.6, +100) == pytest.approx(0.2)


def test_kelly_negative_when_overpriced():
    assert edge.kelly_fraction(0.4, +100) < 0


def test_safe_kelly_applies_fraction_and_cap():
    # full = 0.2; quarter-Kelly -> 0.05; cap 0.05 -> 0.05 (right at cap)
    assert edge.safe_kelly(0.6, +100, fraction=0.25, cap=0.05) == pytest.approx(0.05)
    # full = 0.2; quarter -> 0.05 but cap 0.03 clips it
    assert edge.safe_kelly(0.6, +100, fraction=0.25, cap=0.03) == pytest.approx(0.03)
    # no edge -> 0
    assert edge.safe_kelly(0.4, +100, fraction=0.25, cap=0.05) == 0.0


def test_evaluate_prop_picks_higher_edge_side():
    # Model strongly favours the under; over/under priced -110/-110.
    res = edge.evaluate_prop(
        line=6.5,
        over_odds=-110,
        under_odds=-110,
        model_prob_over=0.40,
        model_prob_under=0.60,
        kelly_fraction_=0.25,
        kelly_cap=0.05,
    )
    assert res.side == "under"
    assert res.edge == pytest.approx(0.60 - 0.5)
    assert res.kelly > 0
