"""Tests for the market-consensus divergence guard (app.model.divergence).

Anchored on the 2026-06-29 slate that motivated it: the guard must KEEP Eduardo
Rodriguez (model near the market) and VETO Tyler Mahle (model two strikeouts off
the whole market), without any Pinnacle data.
"""

from __future__ import annotations

import pytest

from app.model.divergence import market_divergence


def test_rodriguez_is_kept_model_near_market():
    # Model 4.36, books hang 4.5 / 5.5 -> consensus 5.0, gap -0.64 (< threshold).
    v = market_divergence(4.36, [4.5, 5.5])
    assert v is not None
    assert v.consensus_line == pytest.approx(5.0)
    assert not v.diverges                      # a normal under edge, not an outlier


def test_mahle_is_vetoed_model_far_below_market():
    # Model 2.1, books hang 3.5 / 4.5 / 5.5 -> consensus 4.5, gap -2.4 (>> threshold).
    v = market_divergence(2.1, [3.5, 4.5, 5.5])
    assert v is not None
    assert v.diverges                          # two-K outlier => projection error
    assert v.k_gap == pytest.approx(-2.4)
    assert "vetoed" in v.reason


def test_over_side_outlier_is_also_caught():
    # Symmetric: model wildly ABOVE the market is just as suspect.
    v = market_divergence(8.0, [5.5, 6.5])
    assert v.diverges
    assert v.k_gap > 0


def test_threshold_boundary_is_not_a_veto():
    # Exactly at threshold is allowed; just past it vetoes.
    assert not market_divergence(4.25, [5.5], threshold=1.25).diverges  # gap -1.25
    assert market_divergence(4.24, [5.5], threshold=1.25).diverges       # gap -1.26


def test_single_book_still_works():
    v = market_divergence(3.0, [5.5])
    assert v.n_books == 1
    assert "1 book)" in v.reason or "1 book " in v.reason


def test_no_lines_returns_none_not_a_veto():
    # Absence of market data must not be treated as divergence.
    assert market_divergence(4.0, []) is None
    assert market_divergence(4.0, [None]) is None


def test_consensus_uses_median_not_mean():
    # One crazy outlier line shouldn't drag the consensus (median robustness).
    v = market_divergence(5.0, [5.5, 5.5, 12.5])
    assert v.consensus_line == pytest.approx(5.5)
    assert not v.diverges


def test_consensus_agreement_counts_books_at_the_line():
    # 4 of 6 books hang 5.5 (the consensus); the other two are off it.
    v = market_divergence(5.0, [5.0, 5.5, 5.5, 5.5, 5.5, 6.0])
    assert v.n_books == 6
    assert v.consensus_line == pytest.approx(5.5)
    assert v.n_at_consensus == 4
    assert v.agreement_pct == pytest.approx(66.7, abs=0.1)
    assert v.line_low == pytest.approx(5.0)
    assert v.line_high == pytest.approx(6.0)


def test_full_agreement_is_100_pct():
    v = market_divergence(5.0, [5.5, 5.5, 5.5])
    assert v.n_at_consensus == 3
    assert v.agreement_pct == pytest.approx(100.0)
