"""Type-matchup synthesis adjustment for the strikeout projection (flag-gated).

The offline analytics program (mlb-edge/analytics) clustered pitchers into
archetypes and showed OUT-OF-SAMPLE that regressing a pitcher's K rate toward his
ARCHETYPE — heavily, by sample size — generalizes better than his own history,
and that the archetype-vs-opponent matchup is the best base estimate. This module
brings that signal into the live engine without a DuckDB dependency: it loads a
small exported prior (``app/data/type_priors.json``, written by
``analytics/export_priors.py``) and produces a type-matchup lambda that
``projection.project`` blends in when ``ModelConfig.type_matchup_weight > 0``.

The blend is OFF by default (weight 0.0). Everything degrades to a no-op (returns
None) if the priors file or the pitcher's archetype is missing — so the engine is
unchanged unless the prior is present AND the flag is on.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import settings as default_settings

_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "type_priors.json"
_CACHE: dict[str, dict | None] = {}


def load_priors(path: str | None = None) -> dict | None:
    """Load (and cache) the exported type priors; None if the file is absent."""
    p = Path(path) if path else None
    if p is None:
        cand = getattr(default_settings, "type_priors_path", "") or ""
        p = Path(cand) if cand else _DEFAULT_PATH
        if not p.is_absolute() and not p.exists():
            p = _DEFAULT_PATH  # fall back to the package-relative copy
    key = str(p)
    if key not in _CACHE:
        try:
            with open(p, encoding="utf-8") as f:
                _CACHE[key] = json.load(f)
        except (OSError, json.JSONDecodeError):
            _CACHE[key] = None
    return _CACHE[key]


def clear_priors_cache() -> None:
    """Test hook — drop the in-memory prior cache."""
    _CACHE.clear()


def _log5(p: float, o: float, lg: float) -> float:
    """Odds-ratio combine of two rates vs a league baseline (same as projection)."""
    eps = 1e-6
    p = min(max(p, eps), 1 - eps)
    o = min(max(o, eps), 1 - eps)
    lg = min(max(lg, eps), 1 - eps)
    a = (p * o) / lg
    b = ((1 - p) * (1 - o)) / (1 - lg)
    return a / (a + b)


def archetype_regressed_rate(
    recent_k_rate: float, pmarg: float, n_starts: int,
    bf_per_start: float, shrink_pa: float,
) -> float:
    """Regress the pitcher's recent K rate toward his archetype marginal.

    alpha = batters-faced-this-season / (that + shrink_pa). Few starts -> lean on
    the archetype (robust); a full season -> trust the individual more (but, per
    the synthesis, only ~30% even then, since shrink_pa is large).
    """
    bf_seen = max(0, n_starts) * bf_per_start
    alpha = bf_seen / (bf_seen + shrink_pa)
    return pmarg + alpha * (recent_k_rate - pmarg)


def type_matchup_lambda(
    *, pitcher_id: int | None, recent_k_rate: float, opp_k_rate: float,
    expected_bf: float, n_starts: int, league_k: float, shrink_pa: float,
    path: str | None = None,
) -> float | None:
    """Expected Ks from the archetype-regressed pitcher rate vs the opponent.

    Returns None (a no-op for the blend) when priors or the pitcher's archetype
    are unavailable.
    """
    if pitcher_id is None:
        return None
    pr = load_priors(path)
    if not pr:
        return None
    ptype = pr.get("pitcher_type", {}).get(str(pitcher_id))
    if ptype is None:
        return None
    pmarg = pr.get("pmarg", {}).get(str(ptype))
    if pmarg is None:
        return None
    bf_per_start = pr.get("bf_per_start", 24.0)
    eff = archetype_regressed_rate(
        recent_k_rate, pmarg, n_starts, bf_per_start, shrink_pa
    )
    rate = _log5(eff, opp_k_rate, league_k)
    return expected_bf * rate
