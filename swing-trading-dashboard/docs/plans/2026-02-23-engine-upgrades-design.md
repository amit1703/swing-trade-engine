# Engine Upgrades Design — 2026-02-23

## Summary

Four targeted bug fixes across Engine 2 and Engine 5, plus a new Engine 6 that scans
for stocks breaking above KDE resistance levels. A new "Resistance Breakouts" table is
added to the dashboard left panel.

---

## Part 1 — Bug Fixes

### Engine 5 — C&H Breakout Level (handle_high)

**Problem:** `_find_cup` works on close prices only, so `right_rim` is the highest *close*
after the cup bottom. `_find_handle` then sets `handle_high = right_rim` (a close value).
On a chart the resistance/breakout zone is drawn at the intraday HIGH, not the close, so
the pivot level appears too low.

**Fix (partially applied by user):**
- After `_find_handle` returns, look up the intraday HIGH of the right-rim bar using
  `high_s.iloc[rim_abs_idx]` and set `handle["handle_high"]` to `max(rim_intraday_high, current_handle_high)`.
- Additionally, pass `high_lb` (the lookback slice of `high_s`) into `_find_handle` and
  compute `handle_high = max(intraday_highs_in_handle_window[1:])` so the handle's own
  highest intraday bar is also considered.
- Update the geometry `handle_high` field to use this corrected value.

### Engine 5 — RS Unit Mismatch

**Problem:** `rs_vs_spy = rs_ratio - spy_3m_return` subtracts a decimal return (e.g. 0.08)
from a ratio value (e.g. 1.05), producing a meaningless number that inflates quality scores.

**Fix:**
```python
rs_vs_spy = (rs_ratio - 1.0) - spy_3m_return
```
Converts the ratio to a return (e.g. 0.05) before comparing to SPY's 3-month return,
giving a proper relative outperformance figure.  Applied in both `scan_cup_handle` and
`scan_flat_base`.

### Engine 5 — Flat Base Pivot Inconsistency

**Problem:** `base_high` used for the breakout check is `close_s.max()` (highest close),
but `base_high_price` used in geometry is `high_s.max()` (intraday high). The breakout
pivot and chart overlay are inconsistent, and the pivot should be the intraday high.

**Fix:** Replace `base_high = float(base_close.max())` with `base_high = base_high_price`
(already computed as `float(high_s.iloc[-lookback:].max())`).

### Engine 2 — Progressive Tightening

**Problem:** `all(tr_values[i] >= tr_values[i+1] ...)` allows consecutive equal TR values
to be counted as "progressively tighter," which is incorrect.

**Fix:** Change `>=` to `>`.

---

## Part 2 — Engine 6: Resistance Breakout Scanner

### Purpose

Detect stocks that have recently broken above a KDE resistance zone from Engine 1 with
strong volume confirmation — the "TDL / KDE type" signals the user was not finding in
the existing tables.

### Signal Criteria

1. **Stage 2 filter** (same as Engine 5):
   - Close > 200 SMA
   - Close > 50 SMA
   - Close ≥ 52-week low × 1.30
   - 200 SMA rising (today > 20 bars ago)

2. **Resistance breakout detection** — for each `RESISTANCE` zone from Engine 1:
   - Find the most recent bar (within last 3 trading days) where `close > zone.upper`
   - Confirm the bar immediately before that was `close ≤ zone.upper` (fresh cross, not re-test)
   - Breakout bar volume ≥ 150% of 50-day SMA
   - Current close ≤ zone.upper × 1.05 (not already extended >5% above zone)

3. **Among qualifying zones** return the one with the most recent breakout.

### Risk Math

```
entry     = breakout_bar_high × 1.001
stop_loss = zone.lower − 0.2 × ATR14
risk      = entry − stop_loss   (reject if risk ≤ 0 or risk > entry × 0.15)
take_profit = entry + 2 × risk   (1:2 R:R)
```

### Output Schema

```python
{
    "ticker":              str,
    "setup_type":          "RES_BREAKOUT",
    "signal":              "BRK",
    "entry":               float,
    "stop_loss":           float,
    "take_profit":         float,
    "rr":                  2.0,
    "resistance_level":    float,   # zone.level (KDE centroid)
    "zone_upper":          float,
    "breakout_pct":        float,   # (close - zone_upper) / zone_upper × 100
    "volume_ratio":        float,   # breakout-day vol / 50d avg
    "days_since_breakout": int,
    "setup_date":          str,     # ISO date of most recent trading day
}
```

### File

`swing-trading-dashboard/backend/engines/engine6.py`

---

## Part 3 — API Endpoint

**New endpoint:** `GET /api/setups/res-breakout`

Returns all `RES_BREAKOUT` setups from the latest scan, sorted by `days_since_breakout`
ascending (freshest first).

**Scan pipeline change in `main.py`:**
- Import `scan_resistance_breakout` from `engines.engine6`
- After Engine 1 zones are computed for each ticker, run Engine 6 in the same `_process`
  coroutine (parallel with existing engines where possible)
- Save results via existing `batch_save_setups` infrastructure
- Add `res_count` tracking alongside `vcp_count`, `pb_count`, `base_count`

---

## Part 4 — Frontend

**New state:** `resBreakoutSetups` (array, default `[]`)

**New API call:** `fetchSetups('res-breakout')` — added to `loadAllData` `Promise.allSettled`

**New table in left panel** (below Base Patterns):
- Title: "Resistance Breakouts"
- Columns: Ticker | Level | Break% | Vol Ratio | Days Ago | Entry | Stop | Target
- Sorted by `days_since_breakout` ascending
- Rendered via existing `SetupTable` component with a new column config

---

## Files Changed

| File | Change |
|------|--------|
| `backend/engines/engine5.py` | Fix C&H handle_high, RS units, flat base pivot |
| `backend/engines/engine2.py` | Fix progressive tightening `>=` → `>` |
| `backend/engines/engine6.py` | **New file** — resistance breakout scanner |
| `backend/main.py` | Import Engine 6, wire into scan pipeline, add endpoint |
| `frontend/src/api.js` | No change needed (generic `fetchSetups` handles new type) |
| `frontend/src/App.jsx` | Add `resBreakoutSetups` state + fetch |
| `frontend/src/components/SetupTable.jsx` | Add RES_BREAKOUT column config |
