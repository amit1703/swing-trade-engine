# Macro & Sentiment Overview — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a collapsible Macro & Sentiment panel (Fear & Greed, SPY/QQQ %, market headlines) to the dashboard without touching any scan engine.

**Architecture:** Standalone `backend/services/macro_service.py` with module-level TTL cache (20 min), one new FastAPI endpoint, one self-contained React component inserted between Header and tab bar.

**Tech Stack:** Python httpx (already installed), yfinance (already installed), FastAPI, React 18, IBM Plex Mono font (already used throughout).

---

## Task 1: Create the backend service module

**Files:**
- Create: `swing-trading-dashboard/backend/services/__init__.py`
- Create: `swing-trading-dashboard/backend/services/macro_service.py`
- Create: `swing-trading-dashboard/backend/tests/__init__.py`
- Create: `swing-trading-dashboard/backend/tests/test_macro_service.py`

### Step 1: Install test dependencies

```bash
cd swing-trading-dashboard/backend
pip install pytest pytest-asyncio
```

### Step 2: Create the services package

Create `swing-trading-dashboard/backend/services/__init__.py` — empty file:
```python
```

Create `swing-trading-dashboard/backend/tests/__init__.py` — empty file:
```python
```

### Step 3: Write the failing tests first

Create `swing-trading-dashboard/backend/tests/test_macro_service.py`:

```python
"""Tests for macro_service.py — run with: pytest backend/tests/test_macro_service.py -v"""
import time
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_market_overview_returns_required_keys():
    """get_market_overview() always returns the four top-level keys."""
    import services.macro_service as svc

    svc._cache    = None
    svc._cache_ts = 0.0

    with patch.object(svc, "_fetch_fear_greed",   new=AsyncMock(return_value={"score": 42.0, "label": "Fear"})):
        with patch.object(svc, "_fetch_index_change", new=AsyncMock(return_value={"price": 500.0, "change_pct": -1.0})):
            with patch.object(svc, "_fetch_news",     new=AsyncMock(return_value=[])):
                result = await svc.get_market_overview()

    for key in ("fear_greed", "indices", "news", "cached_at", "cache_age_s"):
        assert key in result, f"Missing key: {key}"
    assert result["fear_greed"]["score"] == 42.0
    assert "SPY" in result["indices"]
    assert "QQQ" in result["indices"]


@pytest.mark.asyncio
async def test_get_market_overview_uses_cache_on_second_call():
    """Second call within TTL must return cached data without re-fetching."""
    import services.macro_service as svc

    svc._cache = {
        "fear_greed": {"score": 99.0, "label": "Extreme Greed"},
        "indices": {"SPY": None, "QQQ": None},
        "news": [],
        "cached_at": "2026-01-01T00:00:00",
        "cache_age_s": 0,
    }
    svc._cache_ts = time.monotonic()  # fresh

    call_count = 0
    original   = svc._fetch_fear_greed

    async def _counting_mock():
        nonlocal call_count
        call_count += 1
        return None

    svc._fetch_fear_greed = _counting_mock
    try:
        await svc.get_market_overview()
        assert call_count == 0, "Cache should have been used — fetch should not have been called"
    finally:
        svc._fetch_fear_greed = original


@pytest.mark.asyncio
async def test_fear_greed_failure_yields_none_not_exception():
    """If CNN endpoint fails, fear_greed is None but function still returns."""
    import services.macro_service as svc

    svc._cache    = None
    svc._cache_ts = 0.0

    with patch.object(svc, "_fetch_fear_greed",   new=AsyncMock(return_value=None)):
        with patch.object(svc, "_fetch_index_change", new=AsyncMock(return_value=None)):
            with patch.object(svc, "_fetch_news",     new=AsyncMock(return_value=[])):
                result = await svc.get_market_overview()

    assert result["fear_greed"] is None
    assert result["indices"]["SPY"] is None
    assert isinstance(result["news"], list)
```

### Step 4: Run tests — verify they FAIL

```bash
cd swing-trading-dashboard/backend
pytest tests/test_macro_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'services'` (service doesn't exist yet).

### Step 5: Implement `macro_service.py`

Create `swing-trading-dashboard/backend/services/macro_service.py`:

```python
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


# ── Fetch helpers ─────────────────────────────────────────────────────────────

async def _fetch_fear_greed() -> Optional[Dict[str, Any]]:
    """Fetch Fear & Greed score from CNN public endpoint."""
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
        return {"score": round(float(score), 1), "label": fg.get("rating", "Unknown")}
    except Exception as exc:
        log.warning("Fear & Greed fetch failed: %s", exc)
        return None


async def _fetch_index_change(symbol: str) -> Optional[Dict[str, Any]]:
    """Today's price + % change for a symbol (blocking yfinance in executor)."""
    loop = asyncio.get_event_loop()
    try:
        def _get() -> Optional[Dict[str, Any]]:
            hist = yf.Ticker(symbol).history(period="2d")
            if hist is None or len(hist) < 2:
                return None
            prev  = float(hist["Close"].iloc[-2])
            today = float(hist["Close"].iloc[-1])
            chg   = (today - prev) / prev * 100
            return {"price": round(today, 2), "change_pct": round(chg, 2)}
        return await loop.run_in_executor(None, _get)
    except Exception as exc:
        log.warning("Index fetch failed for %s: %s", symbol, exc)
        return None


async def _fetch_news(max_items: int = 5) -> List[Dict[str, Any]]:
    """Top market headlines from yfinance ^GSPC."""
    loop = asyncio.get_event_loop()
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
        return await loop.run_in_executor(None, _get)
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
    import time as _time
    global _cache, _cache_ts

    now       = _time.monotonic()
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
        "fear_greed": fg,
        "indices":    {"SPY": spy, "QQQ": qqq},
        "news":       news,
        "cached_at":  datetime.now(timezone.utc).isoformat(),
        "cache_age_s": 0,
    }

    _cache    = result
    _cache_ts = now
    return result
```

### Step 6: Run tests — verify they PASS

```bash
cd swing-trading-dashboard/backend
pytest tests/test_macro_service.py -v
```

Expected output:
```
PASSED tests/test_macro_service.py::test_get_market_overview_returns_required_keys
PASSED tests/test_macro_service.py::test_get_market_overview_uses_cache_on_second_call
PASSED tests/test_macro_service.py::test_fear_greed_failure_yields_none_not_exception
3 passed in X.XXs
```

### Step 7: Commit

```bash
cd swing-trading-dashboard
git add backend/services/__init__.py backend/services/macro_service.py \
        backend/tests/__init__.py backend/tests/test_macro_service.py
git commit -m "feat(macro): add macro_service with F&G + indices + news, 3 tests passing"
```

---

## Task 2: Add the API endpoint to main.py

**Files:**
- Modify: `swing-trading-dashboard/backend/main.py` (two edits)

### Step 1: Add the import

In `main.py`, find the block of service imports (around line 115, after `from scoring import ...`):

```python
from scoring import compute_rs_rank_map, compute_top_sectors, score_and_filter_setups
from email_digest import send_digest
```

Add one line after `send_digest`:

```python
from scoring import compute_rs_rank_map, compute_top_sectors, score_and_filter_setups
from email_digest import send_digest
from services.macro_service import get_market_overview
```

### Step 2: Add the endpoint

Find `@app.get("/api/health")` (around line 1374). Insert the new endpoint **above** it:

```python
@app.get("/api/market-overview")
async def market_overview_endpoint():
    """Cached market sentiment: Fear & Greed, SPY/QQQ performance, top news."""
    return await get_market_overview()


@app.get("/api/health")
async def health():
    ...
```

### Step 3: Manual smoke test

Start the backend if not running:
```bash
cd swing-trading-dashboard/backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Hit the endpoint:
```bash
curl http://localhost:8000/api/market-overview
```

Expected: JSON with `fear_greed`, `indices`, `news`, `cached_at`, `cache_age_s` keys. Some values may be `null` if external APIs are slow — that is correct behaviour.

### Step 4: Commit

```bash
cd swing-trading-dashboard
git add backend/main.py
git commit -m "feat(macro): add GET /api/market-overview endpoint"
```

---

## Task 3: Add the frontend API function

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/api.js`

### Step 1: Add the export

Open `frontend/src/api.js`. At the bottom of the file (after `fetchPrices`), add:

```js
export const fetchMarketOverview = () =>
  fetch('/api/market-overview').then(handleResponse)
```

### Step 2: Verify

In a browser console (or with curl through Vite proxy) confirm `/api/market-overview` is reachable. No test needed — it's a one-liner fetch wrapper matching the existing pattern.

### Step 3: Commit

```bash
cd swing-trading-dashboard
git add frontend/src/api.js
git commit -m "feat(macro): add fetchMarketOverview to api.js"
```

---

## Task 4: Build the MarketOverview component

**Files:**
- Create: `swing-trading-dashboard/frontend/src/components/MarketOverview.jsx`

### Step 1: Create the component

Create `swing-trading-dashboard/frontend/src/components/MarketOverview.jsx`:

```jsx
/**
 * MarketOverview — Collapsible macro sentiment strip
 *
 * Collapsed (26px): toggle button + F&G score + SPY/QQQ badges inline
 * Expanded  (70px): F&G gauge row + news headlines row
 *
 * Fetches /api/market-overview on mount; auto-refreshes every 20 min.
 * Collapse state persisted in localStorage key "macro_panel_collapsed".
 */
import { useEffect, useRef, useState } from 'react'
import { fetchMarketOverview } from '../api.js'

const REFRESH_MS = 20 * 60 * 1000  // 20 minutes

// Fear & Greed colour scale
function fgColor(score) {
  if (score == null) return 'var(--muted)'
  if (score <= 24)   return 'var(--halt)'    // Extreme Fear
  if (score <= 44)   return '#f97316'        // Fear
  if (score <= 55)   return '#eab308'        // Neutral
  if (score <= 74)   return 'var(--go)'      // Greed
  return '#00C8FF'                           // Extreme Greed
}

function fmtPct(pct) {
  if (pct == null) return '—'
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`
}

function fmtAge(min) {
  if (min == null || min < 0) return ''
  if (min < 60) return `${min}m`
  return `${Math.floor(min / 60)}h`
}

// Reusable index badge (SPY / QQQ)
function IndexBadge({ sym, info }) {
  const up  = info?.change_pct >= 0
  const nil = info == null
  return (
    <span style={{
      fontFamily: 'IBM Plex Mono, monospace',
      fontSize: 10,
      fontWeight: 600,
      letterSpacing: '0.05em',
      padding: '1px 6px',
      background: nil ? 'rgba(255,255,255,0.04)' : up ? 'rgba(0,200,122,0.10)' : 'rgba(255,45,85,0.10)',
      border: `1px solid ${nil ? 'var(--border)' : up ? 'rgba(0,200,122,0.35)' : 'rgba(255,45,85,0.35)'}`,
      borderRadius: 2,
      color: nil ? 'var(--muted)' : up ? 'var(--go)' : 'var(--halt)',
      whiteSpace: 'nowrap',
    }}>
      {sym} {nil ? '—' : fmtPct(info.change_pct)}
    </span>
  )
}

// Shared toggle button (collapse / expand)
function ToggleBtn({ collapsed, onClick }) {
  return (
    <button
      onClick={onClick}
      title={collapsed ? 'Expand macro overview' : 'Collapse macro overview'}
      style={{
        background: 'none',
        border: '1px solid var(--border-light)',
        color: 'var(--muted)',
        fontFamily: 'IBM Plex Mono, monospace',
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: '0.12em',
        padding: '1px 6px',
        cursor: 'pointer',
        textTransform: 'uppercase',
        whiteSpace: 'nowrap',
        flexShrink: 0,
      }}
    >
      MACRO {collapsed ? '▸' : '▾'}
    </button>
  )
}

export default function MarketOverview() {
  const [data,      setData     ] = useState(null)
  const [loading,   setLoading  ] = useState(true)
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem('macro_panel_collapsed') === 'true'
  )
  const timerRef = useRef(null)

  const load = async () => {
    try {
      const d = await fetchMarketOverview()
      setData(d)
    } catch (err) {
      console.warn('[MarketOverview] fetch failed:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    timerRef.current = setInterval(load, REFRESH_MS)
    return () => clearInterval(timerRef.current)
  }, [])

  const toggle = () => setCollapsed(v => {
    const next = !v
    localStorage.setItem('macro_panel_collapsed', String(next))
    return next
  })

  const fg      = data?.fear_greed
  const spy     = data?.indices?.SPY
  const qqq     = data?.indices?.QQQ
  const news    = data?.news ?? []
  const fgScore = fg?.score ?? null
  const fgLabel = fg?.label ?? '—'
  const fgClr   = fgColor(fgScore)

  const panelBase = {
    flexShrink: 0,
    background: 'var(--surface)',
    borderBottom: '1px solid var(--border)',
  }

  // ── Collapsed strip ────────────────────────────────────────────────────────
  if (collapsed) {
    return (
      <div style={{ ...panelBase, height: 26, display: 'flex', alignItems: 'center', gap: 10, padding: '0 12px' }}>
        <ToggleBtn collapsed onClick={toggle} />

        {loading ? (
          <span style={{ fontSize: 9, color: 'var(--muted)', fontFamily: 'IBM Plex Mono, monospace' }}>
            loading…
          </span>
        ) : (
          <>
            {fg && (
              <span style={{ fontFamily: 'IBM Plex Mono, monospace', fontSize: 10, color: fgClr, fontWeight: 700, whiteSpace: 'nowrap' }}>
                F&G {fgScore?.toFixed(0)} <span style={{ fontWeight: 400, opacity: 0.75 }}>{fgLabel}</span>
              </span>
            )}
            <span style={{ color: 'var(--border)', fontSize: 12, lineHeight: 1 }}>│</span>
            <IndexBadge sym="SPY" info={spy} />
            <IndexBadge sym="QQQ" info={qqq} />
          </>
        )}
      </div>
    )
  }

  // ── Expanded panel ─────────────────────────────────────────────────────────
  return (
    <div style={panelBase}>

      {/* Row 1: toggle + F&G gauge + indices */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '5px 12px', borderBottom: '1px solid var(--border)', height: 42 }}>
        <ToggleBtn collapsed={false} onClick={toggle} />

        {loading ? (
          <div style={{ display: 'flex', gap: 8 }}>
            {[70, 50, 80].map((w, i) => (
              <div key={i} className="shimmer-row" style={{ width: w, height: 12, borderRadius: 2 }} />
            ))}
          </div>
        ) : (
          <>
            {/* F&G score + gauge */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 8, letterSpacing: '0.15em', color: 'var(--muted)', textTransform: 'uppercase', fontFamily: 'IBM Plex Mono, monospace', whiteSpace: 'nowrap' }}>
                Fear &amp; Greed
              </span>
              {/* Gauge bar */}
              <div style={{ width: 64, height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${fgScore ?? 0}%`, height: '100%', background: fgClr, borderRadius: 3, transition: 'width 0.6s ease' }} />
              </div>
              <span style={{ fontFamily: 'IBM Plex Mono, monospace', fontSize: 13, fontWeight: 700, color: fgClr, lineHeight: 1, minWidth: 22, textAlign: 'right' }}>
                {fgScore != null ? fgScore.toFixed(0) : '—'}
              </span>
              <span style={{ fontFamily: 'IBM Plex Mono, monospace', fontSize: 9, color: fgClr, opacity: 0.85, whiteSpace: 'nowrap' }}>
                {fgLabel}
              </span>
            </div>

            <span style={{ color: 'var(--border)', fontSize: 12, lineHeight: 1 }}>│</span>

            {/* Indices */}
            <div style={{ display: 'flex', gap: 5 }}>
              <IndexBadge sym="SPY" info={spy} />
              <IndexBadge sym="QQQ" info={qqq} />
            </div>

            {/* Cache age — shown only when data is stale (>2 min) */}
            {data?.cache_age_s > 120 && (
              <span style={{ fontSize: 8, color: 'var(--muted)', fontFamily: 'IBM Plex Mono, monospace', marginLeft: 'auto' }}>
                cached {Math.floor(data.cache_age_s / 60)}m ago
              </span>
            )}
          </>
        )}
      </div>

      {/* Row 2: news headlines */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, padding: '0 12px', height: 26, overflow: 'hidden' }}>
        {loading ? (
          <div className="shimmer-row" style={{ width: '55%', height: 9 }} />
        ) : news.length === 0 ? (
          <span style={{ fontSize: 9, color: 'var(--muted)', fontFamily: 'IBM Plex Mono, monospace' }}>No headlines</span>
        ) : (
          <div style={{ display: 'flex', gap: 18, alignItems: 'center', overflow: 'hidden' }}>
            {news.slice(0, 4).map((item, i) => (
              <a
                key={i}
                href={item.url || '#'}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: 'flex', alignItems: 'center', gap: 4,
                  textDecoration: 'none', whiteSpace: 'nowrap',
                  overflow: 'hidden', flexShrink: i === 0 ? 0 : 1,
                  maxWidth: i === 0 ? 360 : 280,
                }}
              >
                <span style={{ color: 'var(--accent)', fontSize: 7, fontWeight: 700, flexShrink: 0 }}>▸</span>
                <span style={{ fontSize: 9, color: 'var(--text)', fontFamily: 'IBM Plex Mono, monospace', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {item.title}
                </span>
                {item.age_min != null && (
                  <span style={{ fontSize: 7, color: 'var(--muted)', flexShrink: 0, marginLeft: 2 }}>
                    · {fmtAge(item.age_min)}
                  </span>
                )}
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
```

### Step 2: Visual check

Start both servers and open `http://localhost:5173`. The component is not wired in yet (Task 5 does that), but confirm no build errors:

```bash
cd swing-trading-dashboard/frontend
npm run dev
```

Expected: Vite compiles without errors.

### Step 3: Commit

```bash
cd swing-trading-dashboard
git add frontend/src/components/MarketOverview.jsx
git commit -m "feat(macro): add MarketOverview collapsible component"
```

---

## Task 5: Wire MarketOverview into App.jsx

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/App.jsx` (two edits)

### Step 1: Add the import

At the top of `App.jsx`, with the other component imports (around line 31–38):

```js
import Header        from './components/Header.jsx'
import SetupTable    from './components/SetupTable.jsx'
// ... other imports ...
import MarketOverview from './components/MarketOverview.jsx'   // ← add this line
```

### Step 2: Insert the component in the render tree

Find the render section around line 274. The current structure is:
```jsx
<Header ... />

{/* ── Tab bar ────────── */}
<div className="flex items-stretch flex-shrink-0" style={{ ... }}>
```

Insert `<MarketOverview />` between Header and the tab bar:
```jsx
<Header ... />

<MarketOverview />

{/* ── Tab bar ────────── */}
<div className="flex items-stretch flex-shrink-0" style={{ ... }}>
```

No props needed — the component fetches its own data.

### Step 3: Verify in browser

1. Open `http://localhost:5173`
2. You should see the Macro panel between the Header and the tab buttons
3. Click `MACRO ▾` → panel collapses to a single strip
4. Refresh the page → collapsed state is preserved (localStorage)
5. Expanded: F&G gauge bar, SPY/QQQ badges, news headlines visible
6. If external APIs are down, graceful `—` values appear instead of errors

### Step 4: Commit

```bash
cd swing-trading-dashboard
git add frontend/src/App.jsx
git commit -m "feat(macro): wire MarketOverview panel into App.jsx between Header and tabs"
```

---

## Done

All five tasks complete. Run the full test suite to confirm nothing regressed:

```bash
cd swing-trading-dashboard/backend
pytest tests/test_macro_service.py -v
```

Expected: 3 passed.

The feature is fully isolated — no scan engines, database schema, or scoring logic was modified.
