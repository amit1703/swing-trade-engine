# Backtest Diagnostics — Design Doc 2026-03-10

## Overview

Extend the V5 diagnostics system to support a V4 strategy baseline audit. The existing `analytics.py` functions are reused without modification. A new background job runs `BacktestEngine` over the full 809-ticker universe using strict V4 parameters (single `TRAIL_ATR_MULT=4.162` for all setup types), caches results to disk, and exposes them via a new endpoint. The DiagnosticsTab gains a source toggle: **Live Trades** vs **Backtest (V4 baseline)**.

---

## Decisions

| Question | Decision |
|---|---|
| Runtime model | Background job + disk cache (fire-and-forget, poll for progress) |
| Time window | Fixed 2-year: `2023-01-01 → 2024-12-31` |
| Trail config | Strict V4: single `TRAIL_ATR_MULT=4.162` for all setups (`trail_mult_override` param) |
| Cache storage | JSON file: `backend/cache/backtest_diagnostics.json` |

---

## 1. Constants (`backend/constants.py`)

Three new constants:

```python
# V4 Backtest Diagnostics
BACKTEST_DIAG_START_DATE = "2023-01-01"   # fixed 2-year window start
BACKTEST_DIAG_END_DATE   = "2024-12-31"   # fixed 2-year window end
BACKTEST_V4_TRAIL_MULT   = 4.162          # single trail for all setups (strict V4 override)
```

`BACKTEST_V4_TRAIL_MULT` is intentionally separate from `TRAIL_ATR_MULT` to make the V4-override intent explicit.

---

## 2. `BacktestEngine` — `trail_mult_override` param

### `BacktestEngine.__init__`

Add optional parameter:

```python
trail_mult_override: float | None = None
```

Stored as `self.trail_mult_override`. Passed through to `_manage_open_trade` via the `state` dict.

### `_manage_open_trade` change

```python
# Before (V5 per-setup lookup):
mult_fn = _TRAIL_ATR_BY_SETUP.get(setup_type)
mult = mult_fn() if mult_fn else _constants.TRAIL_ATR_MULT

# After (override takes priority):
override = state.get("trail_mult_override")
if override is not None:
    mult = override
else:
    mult_fn = _TRAIL_ATR_BY_SETUP.get(setup_type)
    mult = mult_fn() if mult_fn else _constants.TRAIL_ATR_MULT
```

`trail_mult_override` is stored in the trade `state` dict when the engine initialises a new position:

```python
"trail_mult_override": self.trail_mult_override,
```

### New module-level function: `run_backtest_universe`

```python
async def run_backtest_universe(
    tickers: list[str],
    start_date: str,
    end_date: str,
    trail_mult_override: float | None = None,
    progress_cb=None,          # optional async callback(done: int, total: int)
) -> list[dict]:
    """
    Run BacktestEngine on every ticker concurrently.
    Returns a flat list of TradeRecord.to_dict() dicts across all tickers.
    """
```

Uses `asyncio.Semaphore(CONCURRENCY_LIMIT)` — same pattern as the scanner. Calls `progress_cb` after each ticker completes. Returns all trade dicts (empty list if no trades generated).

---

## 3. New Endpoints (`backend/main.py`)

### In-memory status (module-level dict)

```python
_backtest_diag_status = {
    "status":   "idle",   # "idle" | "running" | "completed" | "failed"
    "done":     0,
    "total":    0,
    "last_run": None,     # ISO timestamp of last completed run
}
```

Resets to `"idle"` on server restart. JSON cache on disk provides persistence of results.

### Adapter (module-level helper)

```python
def _backtest_trade_to_analytics(tr: dict) -> dict:
    """Map TradeRecord.to_dict() fields to analytics.py contract."""
    return {
        "ticker":       tr["ticker"],
        "setup_type":   tr["setup_type"],
        "entry_price":  tr["entry_price"],
        "stop_loss":    tr["initial_stop"],   # initial_stop → stop_loss
        "close_price":  tr["exit_price"],     # exit_price → close_price
        "status":       "closed",
        "regime_score": None,                 # backtest does not capture regime score per trade
    }
```

### Cache path (module-level constant)

```python
BACKTEST_DIAG_CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "backtest_diagnostics.json")
```

### `POST /api/diagnostics/backtest/run`

Triggers background job. Returns immediately.

```python
{"status": "started", "message": "V4 backtest running over N tickers"}
```

Returns 409 if a run is already in progress.

Background job:
1. Sets `_backtest_diag_status["status"] = "running"`, `total = len(tickers)`
2. Calls `run_backtest_universe(tickers, start_date, end_date, BACKTEST_V4_TRAIL_MULT, progress_cb)`
3. Converts trade dicts via `_backtest_trade_to_analytics`
4. Calls all 4 analytics functions
5. Writes JSON cache with metadata + 4 sections
6. Sets status to `"completed"` or `"failed"`

### `GET /api/diagnostics/backtest/status`

```python
{
    "status":   "running",   # "idle" | "running" | "completed" | "failed"
    "done":     412,
    "total":    809,
    "last_run": "2026-03-10T14:22:00"   # null if never run
}
```

### `GET /api/diagnostics/backtest`

Returns cached report from JSON file. Shape identical to `/api/diagnostics/report` plus metadata:

```json
{
    "generated_at":  "2026-03-10T14:22:00",
    "start_date":    "2023-01-01",
    "end_date":      "2024-12-31",
    "tickers_run":   809,
    "total_trades":  2847,
    "summary":             { ... },
    "setup_breakdown":     { ... },
    "ticker_distribution": [ ... ],
    "regime_performance":  { ... }
}
```

Returns 404 with `{"detail": "No backtest cache found. POST /api/diagnostics/backtest/run to generate."}` if no cache exists.

---

## 4. Frontend (`frontend/src/components/DiagnosticsTab.jsx`)

### Source toggle

`source` state (`"live"` | `"backtest"`). Toggle bar rendered below the tab title:

```
[ Live Trades ]  [ Backtest (V4 baseline) ]
```

### Backtest sub-states

1. **No cache** (404 from GET): info card + "Run V4 Backtest" button → `POST /api/diagnostics/backtest/run`
2. **Running**: button disabled, progress bar, polls `/api/diagnostics/backtest/status` every 3 seconds
3. **Complete**: identical 5-section layout as live mode + `generated_at` timestamp badge + `"2023-01-01 → 2024-12-31"` date range label

### No new components

Same `MetricCard`, equity curve, setup breakdown, ticker distribution, regime performance sections render for both sources. Data shapes are identical.

---

## 5. Files Changed

| File | Change |
|---|---|
| `backend/constants.py` | Add 3 backtest diagnostic constants |
| `backend/backtest_engine.py` | `trail_mult_override` param on `BacktestEngine`; update `_manage_open_trade`; add `run_backtest_universe()` |
| `backend/main.py` | Add `_backtest_diag_status`, `_backtest_trade_to_analytics()`, 3 new endpoints |
| `frontend/src/components/DiagnosticsTab.jsx` | Add source toggle + backtest states |

## 6. Files NOT Changed

- `backend/analytics.py` — reused entirely, zero modifications
- `backend/database.py` — no new tables (JSON cache instead)
- `frontend/src/App.jsx` — tab wiring unchanged
- All engines — unchanged
