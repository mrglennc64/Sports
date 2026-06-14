"""Card selection: turn the full ranked slate into a small, diversified bet card.

The slate flags every +EV start. But when you can only place a handful of bets,
betting all of them is wrong for three reasons the backtest already exposed:

  1. **Overconfidence at the extremes.** The graded sample showed the model's
     biggest "edges" (20%+) win far below their implied rate — an efficient book
     isn't 30% wrong, so a giant edge is usually model error, not value. We cap
     the edge band (``max_edge``) and require a real-but-not-absurd edge
     (``min_edge``).

  2. **Correlation.** Multiple legs in the same game (a pitcher's over and the
     opposing lineup, two arms in one park/ump environment) are correlated;
     treating them as independent bets concentrates risk. We cap bets per game
     (``max_per_game``, default 1).

  3. **Thin inputs.** A confident-looking edge built on a missing lineup / no
     umpire / no whiff data is fragile. We gate on an input-completeness score
     (``min_completeness``) so the card prefers fully-supported projections.

Pure functions, no I/O — the pipeline attaches ``game_pk`` and ``completeness``
to each row, this module picks the card. Selection NEVER changes a projection or
an edge; it only chooses which of the already-computed bets make the card.
"""

from __future__ import annotations

from collections.abc import Sequence

# Completeness component weights (sum to 1.0). ``starts_ok`` dominates and is set
# above the default 0.5 gate on purpose: enough recent starts is the input the
# backtest tied most directly to trust, so starts alone clears the gate while the
# secondary enrichers (umpire / Savant whiff / pitch-mix) cannot clear it without
# it. They raise the score above the floor once starts are present.
_W_STARTS = 0.55
_W_UMPIRE = 0.20
_W_WHIFF = 0.15
_W_PITCH_MIX = 0.10


def input_completeness(
    *,
    starts_ok: bool,
    has_umpire: bool,
    has_whiff: bool,
    has_pitch_mix: bool,
) -> float:
    """Fraction in [0, 1] of the key projection inputs that were actually present.

    ``starts_ok`` is the dominant term (it mirrors the low-confidence gate: at
    least ``min_recent_starts`` this season). The rest are optional enrichers
    that, when populated, raise confidence in the edge.
    """
    return (
        _W_STARTS * starts_ok
        + _W_UMPIRE * has_umpire
        + _W_WHIFF * has_whiff
        + _W_PITCH_MIX * has_pitch_mix
    )


def select_card(
    rows: Sequence[dict],
    *,
    max_bets: int = 4,
    max_per_game: int = 1,
    min_edge: float = 0.05,
    max_edge: float = 0.20,
    min_completeness: float = 0.5,
) -> list[dict]:
    """Pick the bet card from priced slate rows. Returns the chosen rows in order.

    A row is eligible when it is flagged as a bet (``bet`` True — already +EV,
    positive Kelly, and not low-confidence), its ``edge`` sits inside
    ``[min_edge, max_edge]``, and its ``completeness`` meets ``min_completeness``.
    Eligible rows are ranked by edge (then Kelly, then pitcher name for a stable
    order) and taken greedily, skipping any game already at ``max_per_game``,
    until ``max_bets`` are chosen.

    Side effects on the INPUT rows (so callers can render the full slate with the
    card highlighted): every row gets ``selected`` (bool); chosen rows also get
    ``card_rank`` (1-based); rows that were bets but missed the card get
    ``card_excluded`` with a short reason.
    """
    candidates: list[dict] = []
    for r in rows:
        r["selected"] = False
        if not r.get("bet"):
            continue  # not a +EV/confident bet to begin with — silently skip
        edge = r.get("edge")
        if edge is None:
            r["card_excluded"] = "no edge"
            continue
        if edge < min_edge:
            r["card_excluded"] = f"edge {edge:.1%} below select floor {min_edge:.0%}"
            continue
        if edge > max_edge:
            r["card_excluded"] = (
                f"edge {edge:.1%} above cap {max_edge:.0%} (likely model error)"
            )
            continue
        if r.get("completeness", 0.0) < min_completeness:
            r["card_excluded"] = (
                f"inputs incomplete ({r.get('completeness', 0.0):.0%} "
                f"< {min_completeness:.0%})"
            )
            continue
        candidates.append(r)

    candidates.sort(
        key=lambda r: (r["edge"], r.get("kelly", 0.0), r.get("pitcher", "")),
        reverse=True,
    )

    card: list[dict] = []
    per_game: dict[object, int] = {}
    for r in candidates:
        if len(card) >= max_bets:
            r["card_excluded"] = f"card full ({max_bets} bets)"
            continue
        game = r.get("game_pk")
        if game is not None and per_game.get(game, 0) >= max_per_game:
            r["card_excluded"] = f"game already has {max_per_game} bet(s)"
            continue
        per_game[game] = per_game.get(game, 0) + 1
        r["selected"] = True
        r["card_rank"] = len(card) + 1
        r.pop("card_excluded", None)
        card.append(r)

    return card
