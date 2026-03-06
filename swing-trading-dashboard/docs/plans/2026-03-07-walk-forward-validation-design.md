# Walk-Forward Validation — Design Document

**Date:** 2026-03-07
**Status:** Approved

---

## Goal

Add a walk-forward optimization (WFO) system that validates strategy robustness across rolling time windows, measures IS/OOS performance degradation, and exports raw trade-level data for deeper analysis.

---

## Architecture Overview

Four layers: Data Cache → WFO Engine → API → Frontend.

---

## Layer 1 — Data Cache

### Storage
- Location: `backend/data/price_cache/{ticker}.parquet`
- Schema: Date, Open, High, Low, Close, Adj Close, Volume

### Download
- Bulk `yf.download(tickers_list, start=10y_ago, end=today, group_by="ticker", threads=True)`
- SPY always included automatically (required for RS calculations)
- Split MultiIndex result into per-ticker DataFrames, save each as Parquet

### Integrity Check (before save)
1. Drop rows with any missing OHLC values
2. Sort by date ascending
3. Require minimum 5 years of history — reject and warn if below threshold

### Cache Refresh
- No auto-expiry; re-download explicitly via API
- File presence checked before WFO run; missing cache → clear error message

---

## Layer 2 — WFO Engine

### File
`backend/wfo_engine.py`

### Entry Point
```python
run_wfo(
    tickers: List[str],
    setup_types: List[str],
    is_months: int = 24,
    oos_months: int = 3,
    step_months: int = 3,
    min_trades: int = 20,
) -> WFOResult
```

### Window Generation
- Default: 24-month IS, 3-month OOS, 3-month step across full 10-year cache
- Produces ~24 windows for an 8-year effective test range
- Example:
  ```
  Window 1:  IS = [2016-03 → 2018-03)  OOS = [2018-03 → 2018-06)
  Window 2:  IS = [2016-06 → 2018-06)  OOS = [2018-06 → 2018-09)
  ...
  Window 24: IS = [2023-09 → 2025-09)  OOS = [2025-09 → 2025-12)
  ```

### Per-Window Loop (per ticker)
1. Slice cached Parquet into IS DataFrame and OOS DataFrame
2. Pass each slice to `BacktestEngine` via new optional `df` parameter (skips yfinance)
3. Collect aggregate metrics + per-setup breakdown for IS and OOS
4. Store raw `TradeRecord` list for both IS and OOS

### Multi-Ticker Aggregation
- Run per-ticker loops independently
- After all tickers complete, aggregate raw trades across tickers per window for combined view
- Final result has both per-ticker and cross-ticker aggregated metrics

### Metrics — Per Window (IS and OOS, aggregate + per setup type)

| Metric | Formula |
|--------|---------|
| `trades` | Count of completed trades |
| `win_rate` | wins / trades |
| `avg_r` | mean R-multiple across all trades |
| `median_r` | median R-multiple (resistant to outliers) |
| `expectancy` | (win_rate × avg_win_r) − (loss_rate × avg_loss_r) |
| `profit_factor` | gross_profit / abs(gross_loss) |
| `net_profit_pct` | sum of all pnl_pct |

### Reliability & Stability
- `reliable: bool` — `True` when `trades >= min_trades`; unreliable windows shown grayed out
- `stability_score` = `OOS_expectancy / IS_expectancy` — values below 0.6 flagged as potential overfitting

### Data Storage
- Raw `TradeRecord` list stored per window alongside aggregated metrics
- Enables downstream analysis of score effectiveness, RS thresholds, volume impact, breakout distance

---

## Layer 3 — API

### Endpoints

#### `POST /api/wfo/download`
- Body: `{tickers: ["AAPL", "NVDA", ...]}`
- SPY appended automatically
- Background task → returns `{job_id}`
- Poll: `GET /api/wfo/download-status/{job_id}`
  ```json
  {"status": "running", "tickers_completed": 45, "total_tickers": 120}
  ```

#### `POST /api/wfo/run`
- Body:
  ```json
  {
    "tickers": [...],
    "setup_types": ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"],
    "is_months": 24,
    "oos_months": 3,
    "step_months": 3,
    "min_trades": 20
  }
  ```
- Background task → returns `{run_id}`

#### `GET /api/wfo/status/{run_id}`
```json
{
  "status": "running",
  "progress_pct": 37,
  "tickers_completed": 120,
  "total_tickers": 500
}
```

#### `GET /api/wfo/results/{run_id}`
- Returns full WFO result: run metadata + list of windows + per-ticker + cross-ticker aggregate
- Run metadata stored for reproducibility:
  - `tickers`, `setup_types`, `is_months`, `oos_months`, `step_months`, `min_trades`, `created_at`

#### `GET /api/wfo/export/{run_id}`
- Returns CSV download of full dataset (windows + raw trades)
- Content-Disposition: `attachment; filename=wfo_{run_id}.csv`

### Storage
- New `wfo_results` table in `trading.db`
- JSON blob per `run_id` (same immutable-snapshot pattern as existing scan results)
- Metadata stored alongside results for reproducibility

---

## Layer 4 — Frontend

### Location
New **"Walk-Forward"** tab in `BacktestPanel.jsx` (alongside existing "Replay" tab).

### Controls Panel
- Ticker input (comma-separated)
- Setup type checkboxes (all 6, all on by default)
- IS months / OOS months / Step months fields (defaults: 24 / 3 / 3)
- Min trades threshold (default: 20)
- **"Download Cache"** button → `POST /api/wfo/download`
- **"Run Walk-Forward"** button → `POST /api/wfo/run`
- Progress bar driven by `progress_pct` from status endpoint

### Results — View 1: Windows Table

One row per window:

| IS Period | OOS Period | IS WR | OOS WR | IS Avg R | OOS Avg R | IS Expect | OOS Expect | Stability | IS Trades | OOS Trades | Reliable |
|-----------|------------|-------|--------|----------|-----------|-----------|------------|-----------|-----------|------------|---------|

- Unreliable windows (trades < min_trades) shown grayed out
- Stability score < 0.6 highlighted red

### Results — View 2: Per-Setup Breakdown
- Expandable row under each window
- Same metrics split by: VCP / PULLBACK / BASE / RES_BREAKOUT / HTF / LCE

### Results — View 3: IS vs OOS Bar Chart
- X-axis: window number (1–24)
- Two bars per window: IS win_rate (blue) vs OOS win_rate (orange)
- Visual overfitting signal — consistent gap = strategy over-fitted

### Results — View 4: Expectancy Heatmap
- X-axis: windows (1–24)
- Y-axis: setup types (VCP, PULLBACK, BASE, RES_BREAKOUT, HTF, LCE)
- Cell value: OOS expectancy
- Color scale: green (positive) → red (negative)
- Reveals when individual setups stop working over time

### Export
- **"Export CSV"** button → `GET /api/wfo/export/{run_id}` → browser file download

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Cache format | Parquet | Fast reads, compact, preserves dtypes |
| Bulk download | `yf.download(..., group_by="ticker", threads=True)` | Avoids per-ticker rate limits |
| BacktestEngine reuse | Add optional `df` param | Minimal change to existing battle-tested code |
| DB storage | JSON blob in `wfo_results` | Consistent with existing `scan_setups` pattern |
| Multi-ticker | Aggregate raw trades per window | Enables cross-ticker statistical power |
| Reliability flag | `trades >= min_trades` (default 20) | Prevents misleading stats from sparse windows |
| Stability threshold | `OOS/IS expectancy < 0.6` = red | Common WFO overfitting heuristic |
