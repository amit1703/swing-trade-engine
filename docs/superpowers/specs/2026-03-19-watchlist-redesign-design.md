# Watchlist Redesign — Pre-Trigger Setups
**Date:** 2026-03-19

## Goal
Replace the current VCP near-breakout watchlist with stocks that are one move away from triggering a live scanner setup — same quality bar as the live scanner, same engine logic, just before the final trigger fires.

## Two Watchlist Feeds

### 1. RES_BREAKOUT Near (Engine 6 pre-trigger)
Stock is coiling just below resistance and approaching a breakout.

**Conditions (all required):**
- Trend: close > SMA50
- Resistance identified (Donchian / pivot high / KDE zone)
- Consolidation near resistance: ≥ `_min_consol` bars within 8% of resistance (same as Engine 6)
- Close within **5% below** resistance (`close >= resistance * 0.95`)
- Close has NOT yet crossed resistance (not a breakout yet)
- `watchlist_source: "RES_BREAKOUT"`

### 2. PULLBACK Approaching (Engine 3 pre-trigger)
Stock is in an uptrend, pulling back toward a structural support — trend + structure confirmed, trigger not yet fired.

**Conditions (all required):**
- Trend: EMA8 > EMA20, close > SMA50 × 0.97 (relaxed, matches Engine 3 relaxed)
- CCI declining: `cci_today < cci_prev` (pullback actively in progress)
- Price approaching structural support: within **2 ATR** of the level found by `_find_structural_support()` (KDE zone, consolidation low, demand zone, or ascending TDL)
- Pin bar and CCI hook NOT required (those are the trigger — watchlist fires before them)
- `watchlist_source: "PULLBACK"`

## What Stays the Same
- `setup_type = "WATCHLIST"` — no DB schema changes
- `/api/watchlist` endpoint unchanged
- Scoring, RS rank gate, regime gate all still apply
- Same per-ticker pipeline in `main.py`

## What Changes

### Backend
1. **`engine6.py`** — add `scan_res_breakout_near()`: Engine 6 filters minus the cross condition, plus proximity gate (within 5% below resistance)
2. **`engine3.py`** — add `scan_pullback_approaching()`: Engine 3 trend + structural support check + CCI declining, without pin bar or CCI hook
3. **`main.py`** — replace VCP near-breakout WATCHLIST generation with calls to both new functions; remove old `near` dict from Engine 2 path

### Frontend
4. **`WatchlistPanel.jsx`** — show `watchlist_source` badge (RES_BREAKOUT / PULLBACK) per row; remove VCP-specific display assumptions

## Entry/Stop/Target
Same risk math as the parent engine:
- RES_BREAKOUT near: entry = resistance × 1.001, stop = resistance − stop_atr × ATR, target = nearest upstream resistance
- PULLBACK approaching: entry = today's high × 1.001, stop = support_lower − ATR_STOP_MULTIPLIER × ATR, target = nearest resistance
