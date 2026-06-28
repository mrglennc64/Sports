"""Polymarket Gamma-API client + transparent v1 edge model.

Pulls LIVE prediction markets (real questions, prices, volume, liquidity,
resolution dates) from Polymarket's public Gamma API and turns them into the
prediction rows the Edge AI verticals render.

Data source: the Gamma public-search endpoint
    https://gamma-api.polymarket.com/public-search?q=<term>&events_status=active
which returns active *events*, each containing one or more binary sub-markets.

What is REAL here:
  - event / question text
  - market_price (the live YES price on Polymarket)
  - volume_24h, liquidity, end_date, market URL

What is COMPUTED (transparent v1, not a trained ML model):
  - model_probability: market_price adjusted by a documented correction for the
    favorite-longshot bias (longshots are systematically overpriced, favorites
    underpriced in prediction/betting markets). We apply a mild logit stretch.
  - edge   = model_probability - market_price
  - kelly  = quarter-Kelly fraction, capped
  - action = BUY YES / BUY NO / PASS based on edge + liquidity gating

The model tag is returned in every payload so the UI can label it honestly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
MODEL_TAG = "polymarket-v1 (live price + favorite-longshot correction)"

# Only treat prices in this band as tradeable; outside it markets are
# effectively resolved and carry no usable edge.
PRICE_MIN, PRICE_MAX = 0.03, 0.97

# ---- simple in-process TTL cache (avoids hammering the API / rate limits) ----
_CACHE: dict[str, tuple[float, Any]] = {}
_TTL_SECONDS = 300  # 5 minutes


def _cache_get(key: str, now: float) -> Any | None:
    hit = _CACHE.get(key)
    if hit and (now - hit[0]) < _TTL_SECONDS:
        return hit[1]
    return None


def _cache_put(key: str, now: float, value: Any) -> None:
    _CACHE[key] = (now, value)


# -----------------------------------------------------------------------------
# Fetching
# -----------------------------------------------------------------------------
async def _search_events(client: httpx.AsyncClient, query: str, now: float, limit: int = 20) -> list[dict]:
    """Keyword-search active events (cached per query)."""
    cache_key = f"search::{query}::{limit}"
    cached = _cache_get(cache_key, now)
    if cached is not None:
        return cached
    url = (
        f"{GAMMA_BASE}/public-search?q={httpx.QueryParams({'q': query})['q']}"
        f"&limit_per_type={limit}&events_status=active"
    )
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        events = resp.json().get("events", []) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Polymarket search failed for %r: %s", query, exc)
        events = []
    _cache_put(cache_key, now, events)
    return events


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _parse_yes(market: dict) -> float | None:
    outcomes = market.get("outcomes")
    prices = market.get("outcomePrices")
    try:
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        if isinstance(prices, str):
            prices = json.loads(prices)
    except (json.JSONDecodeError, TypeError):
        return None
    if not outcomes or not prices or len(prices) != 2:
        return None
    labels = [str(o).strip().lower() for o in outcomes]
    if "yes" in labels and "no" in labels:
        return _f(prices[labels.index("yes")], -1.0)
    return None


def _normalize(market: dict, event: dict) -> dict | None:
    if market.get("closed") or not market.get("active", True):
        return None
    yes = _parse_yes(market)
    if yes is None or yes < PRICE_MIN or yes > PRICE_MAX:
        return None
    liquidity = _f(market.get("liquidityNum") or market.get("liquidity"))
    slug = event.get("slug") or market.get("slug") or ""
    # Prefer the full market question; fall back to event title + bucket label.
    question = market.get("question") or ""
    if not question:
        gi = market.get("groupItemTitle")
        question = f"{event.get('title', '')} {gi or ''}".strip()
    return {
        "question": question,
        "yes_price": round(yes, 4),
        "no_price": round(1.0 - yes, 4),
        "volume_24h": round(_f(market.get("volume24hr"))),
        "liquidity": round(liquidity),
        "end_date": market.get("endDate") or event.get("endDate"),
        "url": f"https://polymarket.com/event/{slug}" if slug else None,
    }


# -----------------------------------------------------------------------------
# Edge model (transparent v1)
# -----------------------------------------------------------------------------
def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def model_probability(market_price: float) -> float:
    """Transparent v1 fair-value estimate via favorite-longshot correction.

    Stretch the market price toward the extremes in logit space (k>1).
    Empirically, favorites are underpriced and longshots overpriced; a mild
    stretch nudges toward the documented fair value.
    """
    k = 1.12
    return round(_sigmoid(_logit(market_price) * k), 4)


def _kelly(q: float, p: float) -> float:
    """Quarter-Kelly fraction for the favored side, capped at 0.10."""
    if q > p:  # buy YES at price p
        b = (1 - p) / p
        f = q - (1 - q) / b
    else:  # buy NO at price (1-p), win prob (1-q)
        p_no, q_no = 1 - p, 1 - q
        b = (1 - p_no) / p_no
        f = q_no - (1 - q_no) / b
    return round(min(max(0.0, f) * 0.25, 0.10), 4)


def _confidence(liquidity: float, edge: float) -> str:
    a = abs(edge)
    if liquidity >= 50_000 and a >= 0.04:
        return "high"
    if liquidity >= 5_000 and a >= 0.02:
        return "medium"
    return "low"


def build_prediction(
    norm: dict,
    edge_threshold: float = 0.02,
    override: tuple[float, str] | None = None,
) -> dict:
    """Build a prediction row. If `override` is given (model_prob, source_note)
    from an independent signal, it replaces the v1 longshot estimate."""
    p = norm["yes_price"]
    if override is not None:
        q, source = override
    else:
        q, source = model_probability(p), "longshot-correction"
    edge = round(q - p, 4)
    conf = _confidence(norm["liquidity"], edge)
    if abs(edge) < edge_threshold:
        action = "PASS"
    elif edge > 0:
        action = "BUY YES"
    else:
        action = "BUY NO"
    return {
        "event": norm["question"],
        "market_price": p,
        "model_probability": q,
        "edge": edge,
        "kelly": _kelly(q, p),
        "confidence": conf,
        "action": action,
        "signal": source,
        "volume_24h": norm["volume_24h"],
        "liquidity": norm["liquidity"],
        "end_date": norm["end_date"],
        "url": norm["url"],
    }


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
async def find_markets(
    queries: list[str],
    now: float,
    exclude: list[str] | None = None,
    min_liquidity: float = 1000.0,
    limit: int = 8,
) -> list[dict]:
    """Search live Polymarket markets for the given queries, normalize, filter,
    dedupe by question, and return the most liquid `limit` markets."""
    exclude = [e.lower() for e in (exclude or [])]
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "edge-ai/1.0"}) as client:
        results = await asyncio.gather(
            *[_search_events(client, q, now) for q in queries],
            return_exceptions=True,
        )
    for events in results:
        if isinstance(events, Exception) or not events:
            continue
        for ev in events:
            for mk in ev.get("markets", []) or []:
                norm = _normalize(mk, ev)
                if norm is None or norm["liquidity"] < min_liquidity:
                    continue
                ql = norm["question"].lower()
                if any(x in ql for x in exclude):
                    continue
                out.append(norm)
    # de-dup by question, keep highest liquidity
    best: dict[str, dict] = {}
    for n in out:
        cur = best.get(n["question"])
        if cur is None or n["liquidity"] > cur["liquidity"]:
            best[n["question"]] = n
    deduped = sorted(best.values(), key=lambda n: n["liquidity"], reverse=True)
    return deduped[:limit]


async def vertical_payload(
    vertical: str,
    queries: list[str],
    now: float,
    exclude: list[str] | None = None,
    min_liquidity: float = 1000.0,
    limit: int = 8,
    signal_fn: Any = None,
    model_tag: str = MODEL_TAG,
) -> dict:
    """Build a full vertical payload from live Polymarket markets.

    `signal_fn(norm) -> (model_prob, note) | None` lets a vertical supply an
    independent estimate per market; markets it can't score fall back to v1.
    """
    markets = await find_markets(
        queries, now, exclude=exclude, min_liquidity=min_liquidity, limit=limit
    )
    preds = []
    for n in markets:
        override = None
        if signal_fn is not None:
            try:
                override = signal_fn(n)
            except Exception:  # noqa: BLE001
                override = None
        preds.append(build_prediction(n, override=override))
    # Surface the strongest edges first, then by liquidity.
    preds.sort(key=lambda r: (abs(r["edge"]), r["liquidity"]), reverse=True)
    return {
        "vertical": vertical,
        "market": "polymarket",
        "model": model_tag,
        "count": len(preds),
        "predictions": preds,
    }
