# Sniper Debug Mode — Design Document
**Date:** 2026-02-27
**Status:** Approved

---

## Problem

When a ticker fails to produce a setup, the scanner returns `None` silently. There is no way to know *which* filter rejected it — trend, volume, CCI, launchpad, RS score — without reading engine source code and mentally tracing the logic. This makes it impossible to quickly diagnose why a specific stock isn't surfacing.

---

## Solution

A standalone `debug_ticker.py` script in the backend directory. Running `python debug_ticker.py NVDA` fetches data for one ticker, runs every engine with a `debug=True` flag, and prints the exact rejection reason at each gate. Normal full-market scans are completely unaffected.

---

## Architecture

### New file
| File | Purpose |
|------|---------|
| `backend/debug_ticker.py` | Standalone CLI script. Positional arg: ticker symbol. Fetches data synchronously, runs all engines with `debug=True`, prints pass/fail for each. No DB writes, no FastAPI, no asyncio. |

### Modified files
| File | Change |
|------|--------|
| `backend/validation.py` | `is_price_vital()` gets `debug: bool = False`; prints rejection message before returning `False`. |
| `backend/engines/engine2.py` | `scan_vcp()` and `detect_trendline()` get `debug: bool = False`; print at each early-return gate. |
| `backend/engines/engine3.py` | `scan_pullback()` and `scan_relaxed_pullback()` get `debug: bool = False`; print at each gate. |
| `backend/engines/engine6.py` | `scan_resistance_breakout()` gets `debug: bool = False`; print at each gate. |

All new `debug` parameters default to `False` — zero change to existing call sites in `main.py`.

---

## Debug Parameter Threading

Each engine function signature gains one trailing parameter:

```python
def scan_vcp(..., debug: bool = False) -> Optional[Dict]:
def scan_pullback(..., debug: bool = False) -> Optional[Dict]:
def scan_relaxed_pullback(..., debug: bool = False) -> Optional[Dict]:
def scan_resistance_breakout(..., debug: bool = False) -> Optional[Dict]:
def is_price_vital(..., debug: bool = False) -> bool:
```

Inside each function, every early-return `None` (or `False`) gets a guarded print:

```python
if not (l8 > l20 and lc > l50):
    if debug:
        print(f"Engine 2 VCP: REJECTED - Trend filter failed "
              f"(EMA8 {l8:.2f} vs EMA20 {l20:.2f}, Close {lc:.2f} vs SMA50 {l50:.2f})")
    return None
```

---

## Rejection Messages

### Vitality filter (`validation.py`)
```
Vitality: REJECTED - Zombie/Buyout stock (10-day range X.X% < 2%)
```

### Engine 2 VCP (`scan_vcp`)
```
Engine 2 VCP: REJECTED - Trend filter failed (EMA8 X vs EMA20 X, Close X vs SMA50 X)
Engine 2 VCP: REJECTED - No volume dry-up (<50% of avg) in final contraction
Engine 2 VCP: REJECTED - Not within 5% of any resistance zone (closest: X.X%)
Engine 2 VCP: REJECTED - Breakout volume X.Xx (required: 1.5x 50d SMA)
Engine 2 VCP: REJECTED - RS score not positive (X.XXX)
Engine 2 VCP: REJECTED - No valid descending trendline detected
```

### Engine 3 Pullback (`scan_pullback`)
```
Engine 3 Pullback: REJECTED - Trend filter failed (EMA8 X vs EMA20 X, Close X vs SMA50 X)
Engine 3 Pullback: REJECTED - Low X.XX not in value zone (EMA8 X.XX, EMA20 X.XX)
Engine 3 Pullback: REJECTED - No KDE support zone or ascending TDL touch (low: X.XX)
Engine 3 Pullback: REJECTED - No pin bar (Close X.XX < EMA20 X.XX)
Engine 3 Pullback: REJECTED - CCI hook failed (yesterday: X.X, today: X.X, required: < -100 then rising)
```

### Engine 3 RLX Pullback (`scan_relaxed_pullback`)
```
Engine 3 RLX Pullback: REJECTED - Trend filter failed (...)
Engine 3 RLX Pullback: REJECTED - Low X.XX not in value zone (...)
Engine 3 RLX Pullback: REJECTED - No KDE support zone touch required for RLX (low: X.XX)
Engine 3 RLX Pullback: REJECTED - No pin bar (Close X.XX < EMA20 X.XX)
Engine 3 RLX Pullback: REJECTED - CCI relaxation failed (CCI: X.X, required: < -30)
```

### Engine 6 ResBreakout (`scan_resistance_breakout`)
```
Engine 6 Breakout: REJECTED - Below 50 SMA (X.XX < X.XX)
Engine 6 Breakout: REJECTED - No KDE resistance zones found
Engine 6 Breakout: REJECTED - Price overextended (>5% above zone)
Engine 6 Breakout: REJECTED - No zone cross found in last 3 days
Engine 6 Breakout: REJECTED - Decisive close failed (close in bottom X% of range)
Engine 6 Breakout: REJECTED - Launchpad criteria failed (bar N: range X.XX ≥ 1.5× ATR X.XX)
Engine 6 Breakout: REJECTED - Breakout volume X.Xx (required: 1.5x 50d SMA)
```

---

## `debug_ticker.py` Script Structure

```
usage: python debug_ticker.py <TICKER>

1. Fetch 2y OHLCV from yfinance (synchronous)
2. Print header: ══ SNIPER DEBUG: NVDA ══
3. Vitality check (is_price_vital)
4. Engine 1: calculate KDE S/R zones
5. Engine 4: calculate RS score and blue dot
6. Engine 2: scan_vcp (debug=True) → print PASS or rejection chain
7. Engine 3: scan_pullback (debug=True) → print PASS or rejection chain
8. Engine 3: scan_relaxed_pullback (debug=True) → print PASS or rejection chain
9. Engine 6: scan_resistance_breakout (debug=True) → print PASS or rejection chain
10. Engine 5: scan_base_pattern (no debug messages — complex geometry, rarely the issue)
11. Print summary: X/5 engines passed
```

---

## Interaction with Normal Scan

`main.py` never passes `debug=True` to any engine. The new parameter defaults to `False` everywhere. Normal full-market scans produce identical output to today. The only change to `main.py` is `None`.

---

## Styling Constraints

- Output uses `print()` directly — no logging framework, no colour codes, plain terminal text
- Each engine section is separated by a divider line for readability
- `✓ PASS` / `✗ REJECTED` prefixes make it easy to scan vertically
