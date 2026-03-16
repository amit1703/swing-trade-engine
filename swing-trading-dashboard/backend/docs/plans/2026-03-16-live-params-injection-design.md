# Live Scanner Full BacktestParams Injection Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to create the implementation plan from this design.

**Goal:** Fully align live scanner signal output (entry, stop_loss, take_profit) with BacktestParams (#433) so displayed levels are identical to what the backtest uses.

**Architecture:** Four targeted changes — engine6 uses `params.brk_stop_atr` and `params.brk_min_pct`, engine5 uses `params.base_stop_atr`, main.py overrides take_profit on all signals using `params.tp_multiple`. No architectural shifts; engines already have `params=None` pattern.

**Tech Stack:** Python, BacktestParams dataclass, engine3/5/6, main.py live scanner.

---

## Current State vs Target State

| Signal Field | Current (live scanner) | Target (aligned with backtest) |
|---|---|---|
| `stop_loss` (BRK) | `resistance - RES_STOP_ATR_FACTOR × ATR` (constant) | `resistance - params.brk_stop_atr × ATR` (1.6675) |
| `stop_loss` (BASE) | `floor - 0.2 × ATR` (hardcoded) | `floor - params.base_stop_atr × ATR` (0.2, from params) |
| `stop_loss` (PULLBACK) | `min(low, zone) - 0.8 × ATR` | unchanged (no BacktestParams field for pullback stop) |
| `take_profit` (all) | nearest zone or 2:1 fallback | `entry + params.tp_multiple × (entry - stop_loss)` (4.3458) |
| BRK detection filter | hardcoded `brk_min_pct` | `params.brk_min_pct` (0.04333) |

## Data Flow

```
BacktestParams() → _LIVE_PARAMS (main.py line 174)
       ↓
engine6(params=_LIVE_PARAMS)
  → stop_loss  = resistance - params.brk_stop_atr × ATR
  → entry gate = close >= resistance × (1 + params.brk_min_pct)

engine5(params=_LIVE_PARAMS)
  → stop_loss  = floor/handle_low - params.base_stop_atr × ATR

main.py post-signal (all engines)
  → take_profit = entry + params.tp_multiple × (entry - stop_loss)
  → rr          = recalculated from new take_profit
```

## Files Touched

- **Modify:** `backend/engines/engine6.py` — use `params.brk_stop_atr` and `params.brk_min_pct`
- **Modify:** `backend/engines/engine5.py` — use `params.base_stop_atr` in flat base and cup & handle
- **Modify:** `backend/main.py` — add TP override helper, apply after every engine signal return
- **No changes:** `engine3.py`, `backtest_engine.py`, `BacktestParams` definition

## Out of Scope

- `brk_trail_mult`, `base_trail_mult` — open-trade trailing stop management, not applicable to signal display
- `brk_gap_pct` — T+1 gap skip logic, cannot be applied at signal detection time (next day's open unknown)
- Engine 3 stop ATR — no corresponding BacktestParams field exists

## Testing

- Unit tests: engine6 and engine5 with explicit params, verify stop_loss and take_profit match expected formula
- Integration: call live scanner endpoint, confirm signal dicts contain BacktestParams-derived levels
