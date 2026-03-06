"""
macro_service.py — Market context data for the Macro Overview panel.

Public API
----------
get_market_overview()  →  dict   (async, cached 20 min)

Returned shape:
{
  "fear_greed": {"score": 23.0, "label": "Extreme Fear"} | None,
  "indices":    {"SPY": {"price": 475.23, "change_pct": -1.2} | None,
                 "QQQ": {"price": 401.10, "change_pct": -0.8} | None},
  "news":       [{"title": ..., "publisher": ..., "url": ..., "age_min": 45}],
  "cached_at":  "2026-03-06T14:30:00+00:00",
  "cache_age_s": 0,
}
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import yfinance as yf

log = logging.getLogger(__name__)

# ── Cache ─────────────────────────────────────────────────────────────────────
_CACHE_TTL_SECONDS = 1200                                   # 20 minutes
_cache:    Optional[Dict[str, Any]] = None
_cache_ts: float                    = 0.0

CNN_FG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

_FALLBACK_FEAR_GREED = {"score": 50.0, "label": "Neutral", "is_fallback": True}
_FALLBACK_INDEX      = {"price": None, "change_pct": None, "is_fallback": True}
_FALLBACK_NEWS       = [{"title": "Market data unavailable", "publisher": "—", "url": "", "age_min": None, "is_fallback": True}]


# ── Fetch helpers ─────────────────────────────────────────────────────────────

async def _fetch_fear_greed() -> Optional[Dict[str, Any]]:
    """Fetch Fear & Greed score from CNN public endpoint."""
    log.debug("_fetch_fear_greed: starting request to %s", CNN_FG_URL)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                CNN_FG_URL,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            data = resp.json()
        fg    = data.get("fear_and_greed", {})
        score = fg.get("score")
        if score is None:
            return None
        result = {"score": round(float(score), 1), "label": fg.get("rating", "Unknown")}
        log.debug("_fetch_fear_greed: got score=%.1f label=%s", result["score"], result["label"])
        return result
    except httpx.HTTPStatusError as exc:
        log.warning("Fear & Greed HTTP %s: %s", exc.response.status_code, exc.response.text[:200])
        return None
    except httpx.TimeoutException:
        log.warning("Fear & Greed request timed out")
        return None
    except Exception as exc:
        log.warning("Fear & Greed fetch failed: %s", exc)
        return None


async def _fetch_index_change(symbol: str) -> Optional[Dict[str, Any]]:
    """Today's price + % change for a symbol (blocking yfinance in executor)."""
    log.debug("_fetch_index_change: starting %s", symbol)
    loop = asyncio.get_running_loop()
    try:
        def _get() -> Optional[Dict[str, Any]]:
            hist = yf.Ticker(symbol).history(period="2d")
            if hist is None or len(hist) < 2:
                return None
            prev  = float(hist["Close"].iloc[-2])
            today = float(hist["Close"].iloc[-1])
            chg   = (today - prev) / prev * 100
            return {"price": round(today, 2), "change_pct": round(chg, 2)}
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _get),
            timeout=12.0,
        )
        if result is not None:
            log.debug("_fetch_index_change: %s price=%.2f chg=%.2f%%", symbol, result["price"], result["change_pct"])
        return result
    except asyncio.TimeoutError:
        log.warning("Index fetch timed out for %s", symbol)
        return None
    except Exception as exc:
        log.warning("Index fetch failed for %s: %s", symbol, exc)
        return None


async def _fetch_news(max_items: int = 5) -> List[Dict[str, Any]]:
    """Top market headlines from yfinance ^GSPC."""
    log.debug("_fetch_news: starting ^GSPC news fetch")
    loop = asyncio.get_running_loop()
    try:
        def _get() -> List[Dict[str, Any]]:
            raw     = yf.Ticker("^GSPC").news or []
            now_ts  = datetime.now(timezone.utc).timestamp()
            result  = []
            for item in raw[:max_items]:
                pub_ts  = item.get("providerPublishTime", 0)
                age_min = int((now_ts - pub_ts) / 60) if pub_ts else None
                result.append({
                    "title":     item.get("title", ""),
                    "publisher": item.get("publisher", ""),
                    "url":       item.get("link", ""),
                    "age_min":   age_min,
                })
            return result
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _get),
            timeout=12.0,
        )
        log.debug("_fetch_news: got %d headlines", len(result))
        return result
    except asyncio.TimeoutError:
        log.warning("News fetch timed out")
        return []
    except Exception as exc:
        log.warning("News fetch failed: %s", exc)
        return []


# ── Public API ────────────────────────────────────────────────────────────────

async def get_market_overview() -> Dict[str, Any]:
    """
    Return compiled market context dict.
    Refreshes from external sources when cache is older than _CACHE_TTL_SECONDS.
    Never raises — partial failures surface as None / [] fields.
    """
    global _cache, _cache_ts

    now       = time.monotonic()
    cache_age = now - _cache_ts
    if _cache is not None and cache_age < _CACHE_TTL_SECONDS:
        return {**_cache, "cache_age_s": int(cache_age)}

    fg, spy, qqq, news = await asyncio.gather(
        _fetch_fear_greed(),
        _fetch_index_change("SPY"),
        _fetch_index_change("QQQ"),
        _fetch_news(),
    )

    result = {
        "fear_greed": fg or _FALLBACK_FEAR_GREED,
        "indices":    {
            "SPY": spy or {**_FALLBACK_INDEX},
            "QQQ": qqq or {**_FALLBACK_INDEX},
        },
        "news":       news if news else _FALLBACK_NEWS,
        "cached_at":  datetime.now(timezone.utc).isoformat(),
        "cache_age_s": 0,
    }

    _cache    = result
    _cache_ts = now
    return result
