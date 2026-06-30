"""The daily parlay matrix — a STAKING structure layered on capital control.

Given a hard daily budget (from :mod:`app.model.bankroll`) and the day's +EV card
legs (one per game, independent by construction), this splits the budget across a
small / medium / large tier and builds the best parlay for each tier's leg band.

Design stance (deliberate, and at odds with the "8-12 leg lottery" pitch):

  * **Legs are hard-capped at 6** (``MAX_MATRIX_LEGS``). An 8-12 leg parlay of
    ~40-55% legs has a joint win probability around 0.01-0.07% — it hits roughly
    once a *decade*, not once a month, and after the book's compounded vig it is a
    ~-45% EV ticket. We do not build them.
  * **+EV tiers must clear +EV.** The small and medium tiers only stake a parlay
    whose EV is positive; if today's legs can't form one, the tier is skipped and
    its budget is left unspent (protect capital over forcing action).
  * **The large tier is an explicit variance bucket.** It may stake a -EV "moonshot,"
    but it is FLAGGED as such — it is entertainment/variance, not expected profit.

The honest bottom line, surfaced in the output: a parlay multiplies per-leg edge
*and* the per-leg vig. If the legs have no proven edge (CLV unconfirmed), every
tier is -EV and the matrix only controls how fast the budget bleeds. This builds
the structure; proven edge is still the prerequisite for profit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import combinations

from app.config import Settings
from app.config import settings as default_settings
from app.data.client import StatsApiClient
from app.ensemble_pipeline import build_slate_ensemble
from app.model.bankroll import BankrollPlan, cap_to_budget, plan_bankroll
from app.model.parlay import ParlayLeg, evaluate_parlay
from app.parlay_pipeline import _card_leg

# Hard ceiling on legs per parlay — see module docstring. Even 6 is high-variance.
MAX_MATRIX_LEGS = 6


@dataclass
class Tier:
    name: str
    budget_pct: float       # share of the daily budget allocated to this tier
    min_legs: int
    max_legs: int
    allow_negative_ev: bool = False  # only the variance "moonshot" tier sets this


# Small = sustainer (lowest variance), Medium = growth, Large = flagged variance.
DEFAULT_TIERS: list[Tier] = [
    Tier("small", 0.50, 2, 3, allow_negative_ev=False),
    Tier("medium", 0.30, 3, 4, allow_negative_ev=False),
    Tier("large", 0.20, 4, 6, allow_negative_ev=True),
]


@dataclass
class TierResult:
    name: str
    budget_pct: float
    stake: float
    built: bool
    n_legs: int | None = None
    ev_per_unit: float | None = None
    expected_profit: float | None = None   # stake * ev_per_unit (honest; often <= 0)
    potential_payout: float | None = None  # stake * book_decimal (gross if it hits)
    win_prob: float | None = None          # joint model probability (independence-assumed)
    positive_ev: bool | None = None
    legs: list[dict] = field(default_factory=list)
    note: str = ""


def _leg_dicts(legs: tuple[ParlayLeg, ...]) -> list[dict]:
    return [
        {"label": leg.label, "model_prob": round(leg.model_prob, 4),
         "american_odds": leg.american_odds, "game_id": leg.game_id}
        for leg in legs
    ]


def _best_combo(legs, lo, hi, *, prefer_payout, kf, kc):
    """Best parlay within [lo, hi] legs. prefer_payout ranks by the payout multiple
    (the moonshot wants the big number); otherwise by EV per unit (the sane tiers
    want the best honest edge). Returns (evaluation, combo) or None."""
    hi = min(hi, len(legs), MAX_MATRIX_LEGS)
    best = None
    best_key = None
    for size in range(lo, hi + 1):
        for combo in combinations(legs, size):
            try:
                ev = evaluate_parlay(list(combo), kelly_fraction=kf, kelly_cap=kc,
                                     block_same_game=True)
            except ValueError:
                continue
            key = ev.book_decimal if prefer_payout else ev.ev_per_unit
            if best_key is None or key > best_key:
                best, best_key = (ev, combo), key
    return best


def build_matrix_from_legs(
    legs: list[ParlayLeg],
    plan: BankrollPlan,
    *,
    tiers: list[Tier] = DEFAULT_TIERS,
    kelly_fraction: float = 0.25,
    kelly_cap: float = 0.05,
) -> dict:
    """Build the tiered parlay matrix from already-projected legs + a bankroll plan.

    Pure (no I/O) so it is directly testable. Each tier stakes ``budget_pct`` of the
    hard daily budget on the best parlay in its leg band; +EV tiers skip if no +EV
    parlay exists today; the variance tier may stake a flagged -EV moonshot.
    """
    results: list[TierResult] = []
    staked = 0.0
    for tier in tiers:
        target = round(tier.budget_pct * plan.daily_budget, 2)
        stake = cap_to_budget(target, plan.daily_budget, staked)
        best = _best_combo(legs, tier.min_legs, tier.max_legs,
                           prefer_payout=tier.allow_negative_ev,
                           kf=kelly_fraction, kc=kelly_cap)
        if plan.daily_budget <= 0 or stake <= 0:
            results.append(TierResult(tier.name, tier.budget_pct, 0.0, False,
                                      note="no budget (reserve protected or daily cap spent)"))
            continue
        if best is None:
            results.append(TierResult(tier.name, tier.budget_pct, 0.0, False,
                                      note=f"no eligible parlay in the {tier.min_legs}-{tier.max_legs} "
                                           "leg band from today's card legs"))
            continue
        ev, combo = best
        if not tier.allow_negative_ev and not ev.positive_ev:
            results.append(TierResult(tier.name, tier.budget_pct, 0.0, False,
                                      note="no +EV parlay available in this leg band today — tier skipped, "
                                           "budget left unspent"))
            continue

        staked += stake
        note = ""
        if not ev.positive_ev:
            note = ("NEGATIVE-EV variance bucket: a flagged lottery ticket, not an "
                    "expected-profit play (parlays don't create edge).")
        results.append(TierResult(
            name=tier.name, budget_pct=tier.budget_pct, stake=stake, built=True,
            n_legs=ev.n_legs, ev_per_unit=round(ev.ev_per_unit, 4),
            expected_profit=round(stake * ev.ev_per_unit, 2),
            potential_payout=round(stake * ev.book_decimal, 2),
            win_prob=round(ev.model_prob, 4), positive_ev=ev.positive_ev,
            legs=_leg_dicts(combo), note=note,
        ))

    total_staked = round(sum(r.stake for r in results), 2)
    total_expected = round(sum(r.expected_profit for r in results
                              if r.expected_profit is not None), 2)
    matrix_note = (
        "Capital control caps the daily spend; it does not create edge. "
        f"Expected profit across the staked tiers is {total_expected:+.2f} — "
        + ("positive only because every leg cleared +EV."
           if total_expected > 0 else
           "non-positive, which is the honest default until per-leg edge is proven by CLV.")
    )
    return {
        "daily_budget": plan.daily_budget,
        "reserve_floor": plan.reserve_floor,
        "reserve_intact": plan.reserve_intact,
        "total_staked": total_staked,
        "unspent_budget": round(max(0.0, plan.daily_budget - total_staked), 2),
        "total_expected_profit": total_expected,
        "tiers": [asdict(r) for r in results],
        "note": matrix_note,
    }


async def build_parlay_matrix(
    date: str,
    *,
    total_bankroll: float,
    reserve_floor: float,
    cycle_days: int,
    client: StatsApiClient | None = None,
    settings: Settings = default_settings,
    tiers: list[Tier] = DEFAULT_TIERS,
) -> dict:
    """Live entry point: plan the bankroll, pull today's +EV card legs, build the matrix.

    The card is already diversified to one bet per game, so its legs are independent
    — the matrix never parlays correlated legs. Per-leg probabilities already include
    the configured shrinkage, so the reported EV is the honest production number.
    """
    bankroll = plan_bankroll(total_bankroll, reserve_floor, cycle_days)

    owns = client is None
    client = client or StatsApiClient()
    try:
        slate = await build_slate_ensemble(date, client=client, settings=settings)
        card = slate.get("card", [])
        legs = [leg for leg in (_card_leg(r) for r in card) if leg is not None]
        matrix = build_matrix_from_legs(
            legs, bankroll, tiers=tiers,
            kelly_fraction=settings.kelly_fraction, kelly_cap=settings.kelly_cap,
        )
        matrix.update({
            "date": date,
            "cycle_days": cycle_days,
            "bankroll_verdict": bankroll.verdict,
            "card_size": len(card),
            "eligible_legs": len(legs),
        })
        return matrix
    finally:
        if owns:
            await client.aclose()
