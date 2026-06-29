"""Correlated-exposure capping — the piece the per-bet Kelly cap can't do.

``safe_kelly`` caps any SINGLE bet at ``kelly_cap`` of bankroll. It cannot see
that two "different" bets are the same underlying event: the same pitcher's
strikeout total quoted at two books, or at 5.5 and 6.5, or the same slate pulled
twice. Each clears the per-bet cap, yet together they stake one outcome at
multiples of it. That is the 2026-06-28 failure mode — one arm carried 3x the
intended risk because nothing aggregated the legs.

This module groups bets by a correlation key (the pitcher) and scales the legs
within any over-staked group DOWN so the group's total stake never exceeds
``group_cap``. It is strictly reduce-only: a group already under the cap is
untouched, and no leg is ever increased. Pure math, no I/O.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass
class CappedLeg:
    key: str            # correlation group this leg belongs to (e.g. pitcher id/name)
    kelly: float        # original per-bet (already per-bet capped) stake fraction
    kelly_capped: float # stake fraction after the group cap (<= kelly)
    group_total: float  # summed original kelly across the whole group
    capped: bool        # True iff this leg was scaled down by the group cap


def cap_correlated(
    keys: list[str],
    kellys: list[float],
    group_cap: float,
) -> list[CappedLeg]:
    """Scale each group's legs so the group's total stake fraction <= ``group_cap``.

    ``keys[i]`` is the correlation group of leg ``i`` (legs sharing a key bet the
    same underlying outcome) and ``kellys[i]`` its per-bet stake fraction. For any
    group whose legs sum above ``group_cap``, every leg in it is multiplied by
    ``group_cap / group_total`` so the legs keep their relative sizes but the group
    total lands exactly on the cap. Groups already at or below the cap pass through
    unchanged. Returns one :class:`CappedLeg` per input leg, in input order.

    Reduce-only by construction: the scale factor is ``min(1, cap/total)``, so no
    leg is ever increased. A non-positive ``group_cap`` zeroes every leg.
    """
    if len(keys) != len(kellys):
        raise ValueError("keys and kellys must be the same length")

    totals: dict[str, float] = defaultdict(float)
    for key, k in zip(keys, kellys):
        totals[key] += max(k, 0.0)  # negative/no-bet legs contribute nothing

    out: list[CappedLeg] = []
    for key, k in zip(keys, kellys):
        total = totals[key]
        if group_cap <= 0:
            scale = 0.0
        elif total > group_cap:
            scale = group_cap / total
        else:
            scale = 1.0
        capped_value = max(k, 0.0) * scale
        out.append(
            CappedLeg(
                key=key,
                kelly=k,
                kelly_capped=capped_value,
                group_total=total,
                capped=total > group_cap and k > 0.0 and group_cap > 0,
            )
        )
    return out
