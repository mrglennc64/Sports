"""Independent real-data signals for the Economics and Earnings verticals.

These upgrade `model_probability` from the price-only favorite-longshot
transform (polymarket_client.model_probability) to an estimate anchored on an
*independent* real data source:

  Economics:
    - FRED (no key, fredgraph CSV): latest CPI YoY and Fed funds upper target.
    - Inflation/CPI threshold markets are scored against the real current YoY.
    - Fed "no change / hike / cut" markets use real historical base rates.
  Earnings:
    - Yahoo Finance v8 chart (no auth): live prices for mega-cap tickers.
    - "Largest company by market cap" markets are scored against live caps
      (price x cached shares outstanding).

Every signal is best-effort: any fetch failure or unrecognized question returns
None, and the caller falls back to the v1 longshot model. Each enriched row is
labelled with the data source so the UI stays honest.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL = 1800  # 30 min — macro/fundamentals move slowly


def _cache_get(key: str, now: float) -> Any | None:
    hit = _CACHE.get(key)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    return None


def _cache_put(key: str, now: float, val: Any) -> None:
    _CACHE[key] = (now, val)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _clamp(p: float) -> float:
    return round(min(0.97, max(0.03, p)), 4)


# =============================================================================
# FRED (no key) — economics
# =============================================================================
async def _fred_series(client: httpx.AsyncClient, series_id: str) -> list[tuple[str, float]]:
    """Return [(date, value)] for a FRED series via the no-key CSV endpoint."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    resp = await client.get(url, timeout=15.0)
    resp.raise_for_status()
    rows: list[tuple[str, float]] = []
    for line in resp.text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        date, raw = parts[0], parts[-1].strip()
        if raw in ("", "."):
            continue
        try:
            rows.append((date, float(raw)))
        except ValueError:
            continue
    return rows


# Dated macro snapshot. The production VPS cannot reach FRED/BLS (firewalled),
# so we ship the latest official prints and let FRED override them when the
# endpoint is reachable. Refresh after each CPI release / FOMC meeting.
MACRO_SNAPSHOT: dict[str, Any] = {
    "cpi_yoy": 4.2,        # BLS CPI-U, May 2026 (released 2026-06-10)
    "ff_upper": 3.75,      # FOMC target range upper bound (2026-06-17)
    "unemployment": None,
    "asof": "2026-06",
    "source": "BLS May-2026 CPI / FOMC Jun-2026",
}


async def get_macro(now: float, try_fred: bool = False) -> dict[str, Any]:
    """Latest real macro indicators (cached). Starts from the dated snapshot and
    overrides with live FRED values when the endpoint is reachable."""
    cached = _cache_get("macro", now)
    if cached is not None:
        return cached
    macro: dict[str, Any] = dict(MACRO_SNAPSHOT)
    if try_fred:
        try:
            async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
                cpi = await _fred_series(client, "CPIAUCSL")
                if len(cpi) >= 13 and cpi[-13][1]:
                    macro["cpi_yoy"] = round((cpi[-1][1] / cpi[-13][1] - 1) * 100, 2)
                    macro["source"] = "FRED (live)"
                    macro["asof"] = cpi[-1][0]
                ff = await _fred_series(client, "DFEDTARU")
                if ff:
                    macro["ff_upper"] = ff[-1][1]
                ur = await _fred_series(client, "UNRATE")
                if ur:
                    macro["unemployment"] = ur[-1][1]
        except Exception as exc:  # noqa: BLE001
            logger.info("FRED unreachable, using dated snapshot: %s", exc)
    _cache_put("macro", now, macro)
    return macro


# Historical base rate that the FOMC leaves rates unchanged at a given meeting
# (rough, regime-dependent — used only as a prior, blended with the market).
_FED_HOLD_BASE = 0.78
_FED_HIKE_BASE = 0.10
_FED_CUT_BASE = 0.22


def econ_signal(question: str, market_price: float, macro: dict) -> tuple[float, str] | None:
    """Return (model_probability, source_note) for an economics market, or None."""
    q = question.lower()

    # --- Inflation / CPI threshold markets vs real current YoY ---
    if ("inflation" in q or "cpi" in q) and macro.get("cpi_yoy") is not None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", q)
        if m:
            thr = float(m.group(1))
            cur = macro["cpi_yoy"]
            gap = cur - thr  # >0 means current already above threshold
            above = "above" in q or "more than" in q or "greater" in q or "exceed" in q or ">" in q
            # Logistic on the gap; ~1.2pp of gap ≈ one logit unit.
            prob_above = _sigmoid(gap / 1.2)
            prob = prob_above if above else (1 - prob_above)
            asof = macro.get("asof", "")
            return _clamp(prob), f"CPI YoY {cur}% ({asof}) vs {thr}%"

    # --- Fed rate-direction markets (no change / hike / cut) ---
    if "fed" in q or "federal funds" in q or "interest rate" in q or "rate cut" in q or "rate hike" in q:
        if "no change" in q or "no hike" in q or "unchanged" in q or "no cut" in q:
            base = _FED_HOLD_BASE
        elif "increase" in q or "hike" in q or "raise" in q:
            base = _FED_HIKE_BASE
        elif "cut" in q or "decrease" in q or "lower" in q:
            base = _FED_CUT_BASE
        else:
            return None
        # Blend the empirical prior with the market (60% market, 40% prior).
        prob = 0.6 * market_price + 0.4 * base
        return _clamp(prob), f"Fed base-rate prior {base:.0%}"

    return None


# =============================================================================
# Yahoo Finance (no auth) — earnings / market cap
# =============================================================================
# Shares outstanding (billions). Slowly-changing; refreshed manually. Live price
# x shares gives a real-time market cap good enough to rank the mega-caps.
_SHARES_B = {
    "NVDA": 24.4, "AAPL": 14.84, "MSFT": 7.43, "GOOGL": 12.2,
    "GOOG": 12.2, "AMZN": 10.6, "META": 2.53, "TSLA": 3.22,
    "AVGO": 4.71, "BRK-B": 2.16,
}

_NAME_TO_TICKER = {
    "nvidia": "NVDA", "apple": "AAPL", "microsoft": "MSFT",
    "alphabet": "GOOGL", "google": "GOOGL", "amazon": "AMZN",
    "meta": "META", "tesla": "TSLA", "broadcom": "AVGO",
}


async def _yahoo_price(client: httpx.AsyncClient, ticker: str) -> float | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
    try:
        resp = await client.get(url, timeout=12.0)
        resp.raise_for_status()
        meta = resp.json()["chart"]["result"][0]["meta"]
        return float(meta.get("regularMarketPrice"))
    except Exception:  # noqa: BLE001
        return None


async def get_market_caps(now: float) -> dict[str, float]:
    """Live market caps (USD) for the mega-caps, cached. Empty dict on failure."""
    cached = _cache_get("mcaps", now)
    if cached is not None:
        return cached
    caps: dict[str, float] = {}
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
            for tkr, shares in _SHARES_B.items():
                price = await _yahoo_price(client, tkr)
                if price:
                    caps[tkr] = price * shares * 1e9
    except Exception as exc:  # noqa: BLE001
        logger.warning("Yahoo market-cap fetch failed: %s", exc)
    _cache_put("mcaps", now, caps)
    return caps


def earnings_signal(question: str, market_price: float, caps: dict[str, float]) -> tuple[float, str] | None:
    """Return (model_probability, source_note) for an earnings/market-cap market, or None."""
    q = question.lower()
    if "largest company" in q and "market cap" in q and caps:
        # Which ticker is the subject of the market?
        subject = None
        for name, tkr in _NAME_TO_TICKER.items():
            if name in q and tkr in caps:
                subject = tkr
                break
        if subject is None:
            return None
        ranked = sorted(caps.values(), reverse=True)
        top = ranked[0]
        second = ranked[1] if len(ranked) > 1 else top
        subj_cap = caps[subject]
        if subj_cap >= top:
            # Currently #1 — margin over #2 drives confidence it stays #1.
            margin = (subj_cap - second) / second
            prob = _sigmoid(1.8 + margin * 5)
        else:
            # Behind the leader — gap to #1 drives how unlikely a flip is.
            gap = (top - subj_cap) / top
            prob = _sigmoid(-1.3 - gap * 12)
        cap_b = subj_cap / 1e9
        return _clamp(prob), f"live cap {subject} ${cap_b:.0f}B"
    return None
