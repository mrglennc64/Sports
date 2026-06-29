"""Market-consensus divergence guard — the "is the model an outlier?" veto.

A big model edge is only an opportunity if the model is right. When the model's
projected strikeouts sit close to where the whole market hangs the line, a flagged
edge is a soft book to exploit (Eduardo Rodriguez: model 4.4, market ~5.0 — a
normal under). When the model's projection is a full strikeout-plus away from the
*consensus* of every book, the base rate says the MODEL is wrong, not that 25% of
free edge is lying on the table (Tyler Mahle: model 2.1, market ~4.5).

We can't use Pinnacle as the sharp reference — the-odds-api doesn't carry Pinnacle
player props. Instead we use the median line across all books as the consensus:
wisdom-of-the-market, and harder to fool than any single book. This module is pure
math; the quotes themselves come from ``get_strikeout_quotes`` (the wide pull).
"""

from __future__ import annotations

from dataclasses import dataclass


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


@dataclass
class DivergenceView:
    consensus_line: float   # median strikeout line across the books
    line_low: float
    line_high: float
    n_books: int
    n_at_consensus: int     # how many books hang the line exactly at the consensus
    k_gap: float            # model_expected_ks - consensus_line (signed)
    diverges: bool          # True => model is an outlier vs the market, veto the edge
    reason: str

    @property
    def agreement_pct(self) -> float:
        """Share of books clustered at the consensus line — market tightness."""
        return round(self.n_at_consensus / self.n_books * 100.0, 1) if self.n_books else 0.0


def market_divergence(
    model_expected_ks: float,
    book_lines: list[float],
    threshold: float = 1.25,
) -> DivergenceView | None:
    """Flag when the model's projection is an outlier vs the market consensus.

    ``book_lines`` are the strikeout lines every book hangs for this pitcher. The
    consensus is their median; ``k_gap`` is how far the model sits from it. When
    ``abs(k_gap) > threshold`` the model disagrees with the whole market by more
    than a believable margin and the edge should be vetoed (it is far more likely a
    projection error than a real edge). Returns ``None`` if no lines are supplied
    (nothing to compare against — don't veto on absence of data).
    """
    lines = [float(x) for x in book_lines if x is not None]
    if not lines:
        return None

    consensus = _median(lines)
    n_at_consensus = sum(1 for x in lines if x == consensus)
    k_gap = model_expected_ks - consensus
    diverges = abs(k_gap) > threshold
    direction = "below" if k_gap < 0 else "above"
    reason = (
        f"model {model_expected_ks:.1f} Ks is {abs(k_gap):.1f} "
        f"{direction} the market consensus line {consensus:.1f} "
        f"({len(lines)} book{'s' if len(lines) != 1 else ''})"
        + (" — likely a projection error, edge vetoed" if diverges else "")
    )
    return DivergenceView(
        consensus_line=consensus,
        line_low=min(lines),
        line_high=max(lines),
        n_books=len(lines),
        n_at_consensus=n_at_consensus,
        k_gap=round(k_gap, 2),
        diverges=diverges,
        reason=reason,
    )
