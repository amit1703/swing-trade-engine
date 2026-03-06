# Macro & Sentiment Overview — Design Document

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to create the implementation plan from this design.

**Goal:** Add a collapsible Macro & Sentiment Overview panel to the React dashboard for quick situational awareness, with zero impact on core scanning engines.

**Architecture:** Standalone backend service module (Approach A) — lazy fetch with in-process TTL cache, new FastAPI endpoint, new React component inserted between Header and tab bar.

**Tech Stack:** Python httpx (already installed), yfinance (already installed), FastAPI, React 18

---

## Backend: `backend/services/macro_service.py`

New module, zero coupling to existing engines.

### Data fetched
| Source | Data | Method |
|--------|------|--------|
| CNN `production.dataviz.cnn.io` | Fear & Greed score (0–100) + label | `httpx.AsyncClient.get()` |
| yfinance `SPY`, `QQQ` | Today's % change vs prior close | `yf.Ticker().history(period="2d")` |
| yfinance `^GSPC` | Top 5 market news headlines | `yf.Ticker("^GSPC").news[:5]` |

### Cache
- Module-level `_cache: dict | None` and `_cache_ts: float`
- TTL = 1200 seconds (20 min)
- `get_market_overview()` is `async`; checks TTL, fetches with `asyncio.gather` if stale
- On any individual fetch failure: that field returns `None`/`[]`, never raises
- Returns dict shape:
```python
{
  "fear_greed": {"score": 23, "label": "Extreme Fear"},   # or None
  "indices": {
    "SPY": {"price": 475.23, "change_pct": -1.2},          # or None
    "QQQ": {"price": 401.10, "change_pct": -0.8},
  },
  "news": [
    {"title": "...", "publisher": "Reuters", "url": "...", "age_min": 45}
  ],
  "cached_at": "2026-03-06T14:30:00",
  "cache_age_s": 0,
}
```

### Directory
Create `backend/services/__init__.py` (empty) + `backend/services/macro_service.py`.

---

## API: `main.py`

Add one endpoint — no modifications to scan flow or engines:

```python
@app.get("/api/market-overview")
async def market_overview():
    return await get_market_overview()
```

Import: `from services.macro_service import get_market_overview`

---

## Frontend

### `frontend/src/api.js`
Add:
```js
export const fetchMarketOverview = () =>
  fetch('/api/market-overview').then(handleResponse)
```

### `frontend/src/components/MarketOverview.jsx`
New component. Props: none (self-contained, fetches own data).

**Collapsed state (24px strip):**
```
[ MACRO ▸ ]  F&G: 23 Extreme Fear  |  SPY -1.2%  QQQ -0.8%
```

**Expanded state (80px panel):**
```
┌─ MACRO OVERVIEW ▾ ───────────────────────────────────────────────┐
│  F&G  [████░░░░░░]  23  Extreme Fear  │ SPY  -1.2%  QQQ -0.8%   │
│  ──────────────────────────────────────────────────────────────  │
│  ▸ Markets sell off on rate concerns (Reuters · 45m ago)         │
│  ▸ Fed signals cautious path ahead (WSJ · 2h ago)                │
└──────────────────────────────────────────────────────────────────┘
```

**Behaviour:**
- Collapse state persisted in `localStorage` key `macro_panel_collapsed`
- Fetches on mount via `fetchMarketOverview()`; auto-refreshes every 20 min
- Loading: shimmer placeholders
- Error/null data: show `—` gracefully, never crash
- Fear & Greed color scale:
  - 0–24: `var(--halt)` (red)
  - 25–44: `#f97316` (orange)
  - 45–55: `#eab308` (yellow)
  - 56–74: `var(--go)` (green)
  - 75–100: `#00C8FF` (cyan — euphoria)

**Placement in `App.jsx`:**
Insert `<MarketOverview />` between `<Header>` and the tab bar `<div>`. No props needed.
Import `fetchMarketOverview` in `api.js` only; component is self-contained.

---

## Constraints
- DO NOT modify any engine files (engine0–engine7)
- DO NOT modify `scoring.py`, `database.py`, `constants.py`
- Only `main.py` additions (import + one endpoint)
- Only `App.jsx` additions (one component insertion)
- Only `api.js` additions (one export)
