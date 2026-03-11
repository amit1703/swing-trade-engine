# Backtest V5 Improvements — Design

**Date:** 2026-03-11
**Status:** Approved

## Overview

Four improvements to the backtest engine before the next Optuna run:

1. Market regime 4/7 factors in backtest replay
2. Pullback engine pin-bar score component
3. VCP as score booster (not standalone setup)
4. Per-ticker cooldown (Optuna-tunable)

---

## 1. Market Regime in Backtest (4/7 Factors)

### Problem
All trades currently show `regime = UNKNOWN` because the backtest never computes market regime during replay.

### Design

**New function:** `build_regime_map(spy_df: pd.DataFrame) -> Dict[date, dict]`
- Located in `backtest_engine.py`
- Called once in `run_backtest_universe` after SPY is fetched
- Iterates over every date in SPY history, computes 4 SPY-only factors:

| Factor | Logic | Points |
|--------|-------|--------|
| F1 | SPY close > EMA20 | 20 |
| F2 | SPY close > SMA50 | 15 |
| F3 | SMA50 > SMA200 | 15 |
| F4 | EMA20 slope 5-day (linear 0–10) | 0–10 |
| **Max** | | **60** |

**Thresholds (proportionally scaled from 100-pt system):**
- AGGRESSIVE: ≥ 42 pts (was 70/100)
- SELECTIVE: ≥ 24 pts (was 40/100)
- DEFENSIVE: < 24 pts

**Integration:**
- `run_backtest_universe` fetches SPY once, calls `build_regime_map`, passes `regime_map: Dict[date, dict]` to each `BacktestEngine.__init__`
- In the per-bar replay loop: look up `regime_map.get(bar_date)` → if DEFENSIVE, skip new entries
- Regime label stored on `TradeRecord` → diagnostics show per-regime breakdown (fixes UNKNOWN bucket)

---

## 2. Pullback Engine Pin-Bar Score Component

### Problem
`scan_pullback_scored` has no pin-bar check. A stock can score 5.0 (trend=2 + support=2 + near-EMA=1) without closing back above EMA20, generating too many low-quality setups.

### Design

Add to `scan_pullback_scored` scoring block:

```
+2  close ≥ EMA20        (full pin bar — closed back above the value zone)
+1  close ≥ EMA20 × 0.98 (near miss)
+0  otherwise
```

With `score_threshold=5.0`, a setup with no pin bar, no deep CCI, and only near-EMA proximity now scores 4 and is rejected. Optuna continues to tune `score_threshold` to find the optimal quality gate.

---

## 3. VCP as Score Booster

### Problem
VCP as a standalone setup has −0.19R expectancy (33% win rate, PF 0.58). It's actively destroying P&L. Conceptually, VCP (volatility contraction) should *validate* a pullback, not fire independently.

### Design

**New `BacktestParams` field:** `vcp_bonus: float = 1.0` (Optuna: 0.0 → 3.0)

**In scored-mode replay loop:**
1. `scan_pullback_scored` returns `(pb_setup, pb_score)`
2. If `pb_setup` found → run `scan_vcp` on the same ticker/bar
3. If VCP fires → `pb_score += params.vcp_bonus`
4. Continue with normal weight × score threshold gate

**VCP standalone:** Disabled in scored mode. The `_detect_signals` fallback path no longer routes VCP as a standalone setup when `params` is not None. VCP's base score entry removed from `_SIGNAL_BASE_SCORES` lookup (or gated by a `params is not None` check).

**Result:** VCP contributes only when it co-fires with a pullback, boosting high-confidence setups rather than generating independent trades.

---

## 4. Per-Ticker Cooldown

### Problem
Some tickers (NU: 107 trades, CMG: 87, NFLX: 83) dominate P&L. Optuna would overfit to parameters that work for those specific tickers.

### Design

**New `BacktestParams` field:** `cooldown_days: int = 3` (Optuna: 1 → 15)

**In `BacktestEngine`:**
- Track `_last_close_date: Optional[date] = None` per engine instance (one ticker per engine)
- Before opening a new position: if `_last_close_date` is set and `(bar_date - _last_close_date).days < params.cooldown_days` → skip
- When a trade closes: `_last_close_date = close_date`

Simple, per-ticker, no cross-ticker state needed.

---

## Updated BacktestParams

```python
@dataclass
class BacktestParams:
    # RS filter
    rs_threshold:    float = BACKTEST_RS_THRESHOLD_DEFAULT

    # Pullback scoring
    cci_threshold:   float = -20.0
    ema_distance:    float = 0.04
    score_threshold: float = 5.0

    # Signal weights
    breakout_weight: float = 1.0
    pullback_weight: float = 1.0
    tdl_bonus:       float = 1.0

    # New
    vcp_bonus:       float = 1.0   # VCP co-signal bonus (Optuna: 0.0 → 3.0)
    cooldown_days:   int   = 3     # bars blocked after close (Optuna: 1 → 15)
```

---

## Files Changed

| File | Change |
|------|--------|
| `backtest_engine.py` | `build_regime_map()`, `BacktestEngine.__init__` gains `regime_map`, replay loop regime gate, cooldown tracking, VCP booster |
| `engines/engine3.py` | Add pin-bar score component to `scan_pullback_scored` |
| `backtest_engine.py` | `BacktestParams` gains `vcp_bonus`, `cooldown_days` |
| `main.py` | `run_backtest_universe` fetches SPY once, builds regime map, passes to engines |

---

## Success Criteria

- Backtest re-run shows regime distribution (AGGRESSIVE / SELECTIVE / DEFENSIVE) instead of all UNKNOWN
- Pullback trade count drops meaningfully (pin-bar gate filters low-quality setups)
- No VCP standalone trades in scored mode
- High-frequency tickers (NU, CMG, NFLX) show reduced trade counts with cooldown > 1
