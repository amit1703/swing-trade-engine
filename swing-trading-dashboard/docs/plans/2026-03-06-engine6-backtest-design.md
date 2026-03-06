# Engine 6 Backtest Integration Design

**Date:** 2026-03-06

## Goal

Wire Engine 6 (Resistance Breakout) into the backtest replay loop so users can backtest KDE and pivot-point breakout signals alongside VCP, Pullback, and Base patterns.

## Context

Engine 6 (`scan_resistance_breakout`) already handles both KDE and pivot-derived S/R zones — Engine 1's `calculate_sr_zones()` returns zones tagged with `source: "kde"` or `source: "pivot"`, and Engine 6 iterates all zones regardless of source. The backtest already calls `calculate_sr_zones()` to build the `sr_zones` list passed to other engines. Engine 6 is simply not wired into `_detect_signals()` yet.

## Architecture

The backtest `_detect_signals()` function in `backtest_engine.py` already follows an `elif stype == "VCP" / "PULLBACK" / "BASE"` pattern. Adding `elif stype == "RES_BREAKOUT"` completes the set. No changes to Engine 6 itself.

## Changes

### `backend/backtest_engine.py`
- Add `elif stype == "RES_BREAKOUT":` branch in `_detect_signals()` calling `scan_resistance_breakout(ticker, df_slice, sr_zones)`
- Update `_detect_signals()` docstring to list `"RES_BREAKOUT"` as a valid type
- Add `"RES_BREAKOUT"` to `BacktestRunner` default `setup_types`

### `backend/main.py`
- Update `BacktestRequest` field default: `["VCP", "PULLBACK", "BASE", "RES_BREAKOUT"]`

### `frontend/src/components/BacktestPanel.jsx`
- Add `"RES_BREAKOUT"` to `SETUP_OPTIONS` constant
- Add `"RES_BREAKOUT"` to `useState` default selection

## Testing

- Unit test: `_detect_signals()` with `stype="RES_BREAKOUT"` returns setup dict when all Minervini rules pass (synthetic OHLCV + zone data)
- Unit test: `_detect_signals()` with `stype="RES_BREAKOUT"` returns `None` when volume is below threshold
- Run full suite (246 tests) and confirm no regressions
