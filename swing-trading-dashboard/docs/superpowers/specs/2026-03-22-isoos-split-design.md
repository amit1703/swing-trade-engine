# IS/OOS Split Tab — Design Spec

**Date:** 2026-03-22
**Status:** Approved

---

## Overview

Add an "IS / OOS Split" tab to `DiagnosticsTab.jsx` that runs two sequential portfolio backtests (one In-Sample period, one Out-of-Sample period) and presents results in a table with a delta row showing degradation per metric.

The goal is to let the user validate that a strategy's parameters hold up on unseen data — the core test of whether a backtest is overfit.

---

## Scope

- New tab inside `DiagnosticsTab.jsx` only
- One new backend endpoint group (`/api/diagnostics/isoos/*`)
- No changes to `backtest_engine.py`, `portfolio_backtest.py`, or any engine
- No new database tables; result cached to a JSON file

---

## Frontend — "IS / OOS Split" Tab

### Tab placement

Third tab in `DiagnosticsTab`, after "Live Trades" and "Full System Backtest":
```
[ Live Trades ]  [ Full System Backtest ]  [ IS / OOS Split ]
```

### Config panel

Always visible when the tab is active (same UX pattern as Full System Backtest config toolbar).

Controls:
- **IS Period:** start year input → end year input (e.g. 2017 → 2021)
- **OOS Period:** start year input → end year input (e.g. 2022 → 2024)
- **Max Positions:** number input (default 4)
- **Setup Types:** multi-select checkboxes (PULLBACK, BASE, RES_BREAKOUT, HTF, LCE)
- **Min Score:** number input 0–100 (default 0)
- **RUN button** — disabled while running

### Results layout

**Main comparison table** (always full width):

| | WIN RATE | PROFIT F. | AVG R | MAX DD | TRADES |
|---|---|---|---|---|---|
| IN-SAMPLE | value | value | value | value | value |
| OUT-OF-SAMPLE | value | value | value | value | value |
| DELTA | Δ | Δ | Δ | Δ | — |

- Delta = OOS − IS for each metric
- Delta values: red if degraded (worse), green if improved (better), muted if neutral
- "Trades" delta shown as `—` (count difference is not meaningful as a signal)
- Metrics definitions:
  - Win Rate: % of closed trades with positive R
  - Profit Factor: gross profit / gross loss
  - Avg R: average R-multiple per trade
  - Max DD: maximum drawdown (peak-to-trough on cumulative R)

**Setup breakdown** (below main table, collapsed by default):

Two collapsible sections — "IN-SAMPLE Breakdown" and "OUT-OF-SAMPLE Breakdown" — each showing the same per-setup-type table already used in the Full System Backtest tab (setup type | trades | win rate | avg R | profit factor).

### Loading / empty states

- While running: progress bar + "Running IS period… / Running OOS period…" status text
- No result yet: prompt to configure dates and run
- Error: inline error message with retry

---

## Backend

### New files / changes

**`backend/main.py`** — add three new endpoints:

#### `POST /api/diagnostics/isoos/run`

Request body:
```python
class ISOOSRunRequest(BaseModel):
    is_start_date: str = "2017-01-01"
    is_end_date: str = "2021-12-31"
    oos_start_date: str = "2022-01-01"
    oos_end_date: str = "2024-12-31"
    max_positions: int = 4
    ticker_count: Optional[int] = None
    min_score: float = 0.0
    setup_types: List[str] = ["PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"]
```

Response: `202 Accepted` `{"status": "started"}` or `409 Conflict` if already running.

Background job:
1. Run `run_portfolio_backtest_universe` with IS config
2. Run `run_portfolio_backtest_universe` with OOS config
3. Compute analytics for each set of trades (using existing `analytics.py` functions)
4. Save combined result to `cache/isoos_diagnostics.json` (atomic write)

#### `GET /api/diagnostics/isoos/status`

Response: `{"status": "idle"|"running_is"|"running_oos"|"done"|"error", "done": bool, "progress": {"current": int, "total": int}}`

#### `GET /api/diagnostics/isoos`

Response: cached result from `cache/isoos_diagnostics.json`, or `404` if no cache exists.

### Cache file format

```json
{
  "run_at": "2026-03-22T10:00:00",
  "config": {
    "is_start_date": "2017-01-01",
    "is_end_date": "2021-12-31",
    "oos_start_date": "2022-01-01",
    "oos_end_date": "2024-12-31",
    "max_positions": 4,
    "setup_types": ["PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"],
    "min_score": 0.0
  },
  "is": {
    "summary": { "win_rate": 0.624, "profit_factor": 1.84, "avg_r": 0.38, "max_drawdown": -0.082, "total_trades": 312 },
    "setup_breakdown": [ ... ]
  },
  "oos": {
    "summary": { "win_rate": 0.581, "profit_factor": 1.61, "avg_r": 0.29, "max_drawdown": -0.121, "total_trades": 187 },
    "setup_breakdown": [ ... ]
  }
}
```

### State management

Reuse the same boolean-lock pattern as the existing backtest endpoint (`_backtest_running` global flag). IS/OOS uses a separate flag: `_isoos_running`.

Progress phases reported via `_isoos_status` dict: `{"phase": "is"|"oos"|"done", "current": int, "total": int}`.

---

## Data Flow

```
Frontend RUN → POST /api/diagnostics/isoos/run → 202
Frontend polls GET /api/diagnostics/isoos/status every 3s
Backend: run IS backtest (progress_cb updates _isoos_status)
Backend: run OOS backtest (progress_cb updates _isoos_status)
Backend: compute analytics, write cache/isoos_diagnostics.json
Status → done=true
Frontend: GET /api/diagnostics/isoos → render table
```

---

## Reused Code

- `run_portfolio_backtest_universe()` from `portfolio_backtest.py` — called twice
- `compute_summary()`, `compute_setup_breakdown()` from `analytics.py`
- `BacktestConfig` from `portfolio_backtest.py`
- Atomic cache write pattern: `tempfile.mkstemp()` + `os.replace()`
- Config toolbar + progress bar UI pattern from Full System Backtest section of `DiagnosticsTab.jsx`

---

## Out of Scope

- Overlaid equity curves (Option C — not chosen)
- Rolling WFO windows
- Per-ticker IS/OOS breakdown
- Export / share results
- Automatic re-run on config change
