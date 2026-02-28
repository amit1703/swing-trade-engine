# DRY RUN Setups Display — Design Doc

**Date:** 2026-02-28

## Problem

When DRY RUN mode is active, the scan engines run and engine counts appear in the EngineHealthPanel, but the SetupTables (VCP / Pullback / Base / ResBreakout) stay empty. This is because `batch_save_setups` is skipped in dry_run mode, so no setups reach the DB that the SetupTables read from.

The user expected DRY RUN to be a true "safe mode": see all results without writing to the database.

## Root Cause

Two separate data paths:
- **EngineHealthPanel** reads `_scan_state["engine_stats"]` — updated in-memory during the scan regardless of `dry_run`.
- **SetupTables** read from SQLite via `GET /api/setups/{type}` → `get_latest_setups()` — only populated when `dry_run=False`.

## Design

### Backend (`main.py`)

1. Add `"dry_run_setups": None` to `_scan_state` initializer and to the per-scan reset block inside `_run_scan()`.

2. At the end of `_run_scan()`, after `_inject_hot_sector()`, if `dry_run=True`, organize `collected_setups` by `setup_type` and store in `_scan_state["dry_run_setups"]`:

```python
if dry_run and collected_setups:
    _scan_state["dry_run_setups"] = {
        "vcp":         [s for s in collected_setups if s.get("setup_type") == "VCP"],
        "pullback":    [s for s in collected_setups if s.get("setup_type") == "PULLBACK"],
        "base":        [s for s in collected_setups if s.get("setup_type") == "BASE"],
        "res_breakout":[s for s in collected_setups if s.get("setup_type") == "RES_BREAKOUT"],
        "watchlist":   [s for s in collected_setups if s.get("setup_type") == "WATCHLIST"],
    }
```

3. In `GET /api/scan-status`, include `dry_run_setups` in the response:

```python
return {
    ...existing fields...,
    "dry_run_setups": _scan_state.get("dry_run_setups"),
}
```

`dry_run_setups` is `None` during the scan and for non-dry-run scans, so polling overhead is negligible.

### Frontend (`App.jsx`)

In the poll loop (inside the `setInterval` callback), when the scan finishes:

```js
if (!status.in_progress) {
  clearInterval(pollTimerRef.current)
  if (status.engine_stats?.dry_run && status.dry_run_setups) {
    const dr = status.dry_run_setups
    setVcpSetups(dr.vcp ?? [])
    setPullbackSetups(dr.pullback ?? [])
    setBaseSetups(dr.base ?? [])
    setResBreakoutSetups(dr.res_breakout ?? [])
    setWatchlistItems(dr.watchlist ?? [])
  } else {
    loadAllData()
  }
}
```

Non-dry-run scans are unaffected — they still call `loadAllData()`.

## Data Compatibility

`collected_setups` entries already contain all fields the frontend needs (`ticker`, `setup_type`, `entry`, `stop_loss`, `take_profit`, `rr`, signal flags, `sector`, `hot_sector`, etc.). The DB layer adds `scan_timestamp` and `setup_date` but the frontend does not use those for display.

## What Does NOT Change

- DB schema — no new tables or columns
- Non-dry-run scan flow — completely unaffected
- EngineHealthPanel — already works
- `loadAllData()` — called as today for real scans

## Result

DRY RUN becomes a true safe mode:
- Engines run ✅
- EngineHealthPanel shows counts ✅
- SetupTables show tickers ✅
- Nothing written to DB ✅
- Next real scan is unaffected ✅
