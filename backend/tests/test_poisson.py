import math

import pytest

from app.model import poisson


def test_pmf_known_values():
    # Poisson(lam=2): P(0)=e^-2, P(2)=2*e^-2
    assert poisson.pmf(0, 2.0) == pytest.approx(math.exp(-2))
    assert poisson.pmf(2, 2.0) == pytest.approx(2 * math.exp(-2))


def test_pmf_sums_to_one():
    total = sum(poisson.pmf(k, 6.0) for k in range(0, 26))
    assert total == pytest.approx(1.0, abs=1e-6)


def test_pmf_rejects_negative():
    with pytest.raises(ValueError):
        poisson.pmf(-1, 2.0)
    with pytest.raises(ValueError):
        poisson.pmf(1, -2.0)


def test_half_line_over_under_sum_to_one():
    # For a half-line there is no push, so over + under == 1.
    lam = 6.3
    assert poisson.prob_over(lam, 6.5) + poisson.prob_under(lam, 6.5) == pytest.approx(
        1.0, abs=1e-6
    )


def test_half_line_threshold_is_correct():
    # Over 6.5 must equal P(K >= 7).
    lam = 6.3
    expected = sum(poisson.pmf(k, lam) for k in range(7, 26))
    assert poisson.prob_over(lam, 6.5) == pytest.approx(expected)


def test_integer_line_excludes_push():
    # Over 7 = P(K >= 8); Under 7 = P(K <= 6); the exact 7 is a push.
    lam = 7.0
    over = poisson.prob_over(lam, 7)
    under = poisson.prob_under(lam, 7)
    push = poisson.pmf(7, lam)
    assert over + under + push == pytest.approx(1.0, abs=1e-6)
    assert over == pytest.approx(sum(poisson.pmf(k, lam) for k in range(8, 26)))


def test_over_increases_with_lambda():
    assert poisson.prob_over(8.0, 6.5) > poisson.prob_over(5.0, 6.5)
