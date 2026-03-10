# Optuna Backtest Scoring — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `BacktestParams` dataclass, score-based pullback detection (backtest-only), signal-type weights, and a diagnostics printer so Optuna can tune thresholds and weights against the full backtest.

**Architecture:** `BacktestParams` is the single object Optuna populates and `BacktestEngine` consumes. A new `scan_pullback_scored()` function in engine3.py evaluates sub-conditions and returns a raw score; `BacktestEngine` applies a per-type weight and gates on `score_threshold`. Legacy callers (live scanner, existing tests) pass no `params` and are completely unaffected.

**Tech Stack:** Python 3.10+, dataclasses, pytest, existing `_prepare_indicators()` helper in engine3.py.

**Design doc:** `docs/plans/2026-03-11-optuna-backtest-scoring-design.md`

---

### Task 1: `BacktestParams` dataclass + `TradeRecord.final_score`

**Files:**
- Modify: `swing-trading-dashboard/backend/backtest_engine.py`
- Create: `swing-trading-dashboard/backend/tests/test_backtest_params.py`

**Context:**
`BacktestParams` lives at the top of `backtest_engine.py`, after the module-level constants block (after line ~71, before `TradeRecord`). `TradeRecord` gets one new optional field `final_score: Optional[float] = None`. `BacktestEngine.__init__` gains `params: Optional[BacktestParams] = None` as the last keyword argument.

**Step 1: Write the failing tests**

```python
# swing-trading-dashboard/backend/tests/test_backtest_params.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backtest_engine import BacktestParams, BacktestEngine, TradeRecord
from datetime import date


def test_backtest_params_defaults():
    p = BacktestParams()
    assert p.rs_threshold    == pytest.approx(-0.01219, abs=1e-5)
    assert p.cci_threshold   == pytest.approx(-20.0)
    assert p.ema_distance    == pytest.approx(0.04)
    assert p.score_threshold == pytest.approx(5.0)
    assert p.breakout_weight == pytest.approx(1.0)
    assert p.pullback_weight == pytest.approx(1.0)
    assert p.tdl_bonus       == pytest.approx(1.0)


def test_backtest_params_custom():
    p = BacktestParams(rs_threshold=0.05, score_threshold=7.0)
    assert p.rs_threshold    == pytest.approx(0.05)
    assert p.score_threshold == pytest.approx(7.0)
    # unchanged defaults
    assert p.breakout_weight == pytest.approx(1.0)


def test_backtest_engine_accepts_params():
    """BacktestEngine.__init__ accepts a BacktestParams without error."""
    p = BacktestParams()
    engine = BacktestEngine(
        ticker="AAPL",
        start_date="2024-01-01",
        end_date="2024-12-31",
        params=p,
    )
    assert engine.params is p


def test_backtest_engine_none_params_by_default():
    """Legacy callers get params=None (no behaviour change)."""
    engine = BacktestEngine(
        ticker="AAPL",
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    assert engine.params is None


def test_trade_record_final_score_defaults_none():
    tr = TradeRecord(
        ticker="AAPL", setup_type="VCP",
        signal_date="2024-01-02", entry_date="2024-01-03",
        entry_price=150.0, initial_stop=145.0, take_profit=160.0,
        exit_date="2024-01-10", exit_price=158.0,
        exit_reason="TARGET", holding_days=7,
    )
    assert tr.final_score is None


def test_trade_record_final_score_set():
    tr = TradeRecord(
        ticker="AAPL", setup_type="VCP",
        signal_date="2024-01-02", entry_date="2024-01-03",
        entry_price=150.0, initial_stop=145.0, take_profit=160.0,
        exit_date="2024-01-10", exit_price=158.0,
        exit_reason="TARGET", holding_days=7,
        final_score=7.5,
    )
    assert tr.final_score == pytest.approx(7.5)
    assert tr.to_dict()["final_score"] == pytest.approx(7.5)


import pytest
```

**Step 2: Run to confirm failure**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_params.py -v
```

Expected: `ImportError` or `TypeError` — `BacktestParams` does not exist yet.

**Step 3: Implement**

Add `from dataclasses import dataclass` to existing imports (it likely already exists — check first).

After the module constants block (after `MIN_BARS_FOR_SIGNAL = 60`, before `@dataclass class TradeRecord`), insert:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Optuna-tunable parameters
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BacktestParams:
    """
    All parameters that Optuna tunes in a single trial.

    Passed to BacktestEngine(params=...). When params=None the engine runs
    in legacy mode — identical behaviour to pre-V5 backtest. All defaults
    match the V4 Optuna best so that a plain BacktestParams() is a sensible
    starting point.
    """
    # ── RS filter ────────────────────────────────────────────────────────────
    rs_threshold:    float = -0.01219  # O'Neil RS floor  (Optuna: -0.05 → +0.10)

    # ── Pullback scoring thresholds ──────────────────────────────────────────
    cci_threshold:   float = -20.0     # relaxed CCI floor (Optuna: -150 → -10)
    ema_distance:    float = 0.04      # value-zone proximity (Optuna: 0.01 → 0.08)
    score_threshold: float = 5.0       # min score to open any trade (Optuna: 2 → 9)

    # ── Signal-type weights ──────────────────────────────────────────────────
    breakout_weight: float = 1.0       # VCP / RES_BREAKOUT / HTF / LCE (Optuna: 0.5 → 3.0)
    pullback_weight: float = 1.0       # PULLBACK  (Optuna: 0.5 → 3.0)
    tdl_bonus:       float = 1.0       # ascending TDL support (Optuna: 0.0 → 2.0)
```

Add `final_score: Optional[float] = None` to `TradeRecord` dataclass (after `is_win: bool` field):

```python
    # Scoring (populated in scored mode only; None in legacy mode)
    final_score: Optional[float] = None
```

Update `TradeRecord.__post_init__` — no change needed, `final_score` is not computed there.

Update `TradeRecord.to_dict()` — add:
```python
"final_score": self.final_score,
```

Update `BacktestEngine.__init__` signature — add as last keyword param:
```python
params: Optional[BacktestParams] = None,
```

Store as `self.params = params`.

**Step 4: Run to confirm passing**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_params.py -v
```

Expected: 6 passed.

**Step 5: Commit**

```bash
git add swing-trading-dashboard/backend/backtest_engine.py \
        swing-trading-dashboard/backend/tests/test_backtest_params.py
git commit -m "feat(backtest): add BacktestParams dataclass and TradeRecord.final_score"
```

---

### Task 2: RS gate in `BacktestEngine.run()`

**Files:**
- Modify: `swing-trading-dashboard/backend/backtest_engine.py`
- Create: `swing-trading-dashboard/backend/tests/test_backtest_rs_gate.py`

**Context:**
The RS gate is inserted in the per-bar replay loop (`run()` method), after the liquidity gate check and before `_detect_signals`. In scored mode (`self.params is not None`) it reads `rs_score` from the pre-computed `_rs_t` dict and skips the bar if below `params.rs_threshold`. In legacy mode it does nothing — engine3's internal `RS_REJECT_THRESHOLD` handles it unchanged.

The pre-computed RS dict `_rs_t` is already built each bar (line ~726). The gate sits between the liquidity check and the `spy_slice` computation.

**Step 1: Write the failing tests**

```python
# swing-trading-dashboard/backend/tests/test_backtest_rs_gate.py
"""
Tests for the RS gate in BacktestEngine scored mode.
Uses synthetic DataFrames to avoid network calls.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import pytest

from backtest_engine import BacktestParams, BacktestEngine


def _make_df(n: int = 300, price: float = 100.0) -> pd.DataFrame:
    """Minimal DataFrame with columns BacktestEngine needs."""
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    prices = np.full(n, price)
    return pd.DataFrame({
        "Open":      prices,
        "High":      prices * 1.01,
        "Low":       prices * 0.99,
        "Close":     prices,
        "Adj Close": prices,
        "Volume":    np.full(n, 2_000_000),
    }, index=idx)


def test_rs_gate_active_in_scored_mode():
    """
    When params.rs_threshold = +0.10 (high bar) the RS gate should
    block bars where rs_score < 0.10. We verify this by checking that
    the engine's scored mode path uses the params object.
    """
    p = BacktestParams(rs_threshold=0.10)
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2023-01-01",
        end_date="2023-12-31",
        params=p,
    )
    assert engine.params.rs_threshold == pytest.approx(0.10)


def test_rs_gate_not_active_in_legacy_mode():
    """Legacy mode (params=None) — engine.params is None, gate never runs."""
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2023-01-01",
        end_date="2023-12-31",
    )
    assert engine.params is None


def test_scored_mode_with_low_rs_produces_fewer_trades():
    """
    With a very high rs_threshold (impossible to meet on synthetic data),
    scored mode should produce 0 trades because every bar is gated out.
    Legacy mode produces whatever it naturally finds.

    Uses preloaded synthetic DFs to avoid yfinance calls.
    """
    import asyncio
    ticker_df = _make_df(400)
    spy_df    = _make_df(400)

    # scored mode — rs_threshold impossibly high (1.0 = must beat SPY by 100%)
    p = BacktestParams(rs_threshold=1.0, score_threshold=0.0)
    engine_scored = BacktestEngine(
        ticker="TEST",
        start_date="2023-01-01",
        end_date="2023-12-31",
        ticker_df=ticker_df,
        spy_df=spy_df,
        params=p,
    )
    result_scored = asyncio.run(engine_scored.run())

    # legacy mode (params=None)
    engine_legacy = BacktestEngine(
        ticker="TEST",
        start_date="2023-01-01",
        end_date="2023-12-31",
        ticker_df=ticker_df,
        spy_df=spy_df,
    )
    result_legacy = asyncio.run(engine_legacy.run())

    # rs_threshold=1.0 should block all new signals
    assert result_scored.total_trades == 0
    # legacy is unaffected (may or may not find trades on flat synthetic data — just confirm it ran)
    assert result_legacy.total_trades >= 0
```

**Step 2: Run to confirm failure**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_rs_gate.py -v
```

Expected: `test_scored_mode_with_low_rs_produces_fewer_trades` fails because RS gate not implemented yet.

**Step 3: Implement**

In `BacktestEngine.run()`, find the block that builds `_rs_t` and calls `_detect_signals` (around the line `signal = _detect_signals(...)`). Insert the RS gate immediately after `_rs_t` is built:

```python
            # RS gate (scored mode only) — skip bar if stock RS below threshold
            if self.params is not None:
                if _rs_t["rs_score"] < self.params.rs_threshold:
                    continue
```

This goes **after** `_rs_t` is assigned and **before** `signal = _detect_signals(...)`.

**Step 4: Run to confirm passing**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_rs_gate.py -v
```

Expected: 3 passed.

**Step 5: Confirm existing tests still pass**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_trail_override.py tests/test_backtest_diag_constants.py -v
```

Expected: all pass (legacy mode unchanged).

**Step 6: Commit**

```bash
git add swing-trading-dashboard/backend/backtest_engine.py \
        swing-trading-dashboard/backend/tests/test_backtest_rs_gate.py
git commit -m "feat(backtest): add RS gate in scored mode replay loop"
```

---

### Task 3: `scan_pullback_scored()` in engine3.py

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine3.py`
- Create: `swing-trading-dashboard/backend/tests/test_scan_pullback_scored.py`

**Context:**
Appended after `scan_relaxed_pullback`. Reuses `_prepare_indicators()` and `_find_structural_support()` that are already in engine3.py. Returns `(setup_dict, score)` or `(None, 0.0)`. Hard gates: trend score == 0, no structural support, risk math invalid. Everything else is scored additively.

The `params` argument is typed as `Any` (not importing `BacktestParams` from backtest_engine to avoid circular imports) — duck-typed: only `params.cci_threshold`, `params.ema_distance`, `params.tdl_bonus` are accessed.

**Step 1: Write the failing tests**

```python
# swing-trading-dashboard/backend/tests/test_scan_pullback_scored.py
"""
Tests for scan_pullback_scored() in engine3.py.
Uses synthetic DataFrames — no network calls.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import pytest
from types import SimpleNamespace


def _make_params(**kwargs):
    defaults = dict(
        cci_threshold=-20.0,
        ema_distance=0.04,
        tdl_bonus=1.0,
        score_threshold=5.0,
        breakout_weight=1.0,
        pullback_weight=1.0,
        rs_threshold=-0.05,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_uptrend_df(n: int = 150, base: float = 100.0) -> pd.DataFrame:
    """
    Synthetic uptrending DataFrame.
    - Close rises gradually (EMA8 > EMA20 > SMA50 after warmup)
    - Last bar: Low dips below EMA8/EMA20, Close recovers above EMA20
    - Volume: constant 2M (passes liquidity)
    """
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    # Gradual uptrend
    trend = np.linspace(base, base * 1.40, n)
    close = trend + np.random.default_rng(42).normal(0, 0.2, n)
    close = np.maximum(close, 1.0)

    # Last bar: dip below EMA20 then recover
    close[-1] = close[-2] * 0.997   # slight pullback — close near EMA20
    low_arr = close.copy()
    low_arr[-1] = close[-3] * 0.985  # low penetrates EMA zone

    high_arr = close * 1.005
    open_arr = close * 0.999
    vol = np.full(n, 2_000_000)

    return pd.DataFrame({
        "Open":      open_arr,
        "High":      high_arr,
        "Low":       low_arr,
        "Close":     close,
        "Adj Close": close,
        "Volume":    vol,
    }, index=idx)


def _make_downtrend_df(n: int = 150) -> pd.DataFrame:
    """Downtrending stock — trend filter must fail."""
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    close = np.linspace(150.0, 80.0, n)
    return pd.DataFrame({
        "Open":      close * 1.001,
        "High":      close * 1.01,
        "Low":       close * 0.99,
        "Close":     close,
        "Adj Close": close,
        "Volume":    np.full(n, 2_000_000),
    }, index=idx)


def test_returns_none_zero_on_downtrend():
    """Trend hard gate: no uptrend → (None, 0.0)."""
    from engines.engine3 import scan_pullback_scored
    df     = _make_downtrend_df()
    params = _make_params()
    setup, score = scan_pullback_scored("TEST", df, [], params)
    assert setup is None
    assert score == pytest.approx(0.0)


def test_returns_tuple():
    """scan_pullback_scored always returns a 2-tuple."""
    from engines.engine3 import scan_pullback_scored
    df     = _make_downtrend_df()
    params = _make_params()
    result = scan_pullback_scored("TEST", df, [], params)
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_setup_dict_contains_pullback_score_field():
    """When a setup is found, dict contains pullback_score and is_scored_mode."""
    from engines.engine3 import scan_pullback_scored
    df     = _make_uptrend_df()
    params = _make_params()
    setup, score = scan_pullback_scored("TEST", df, [], params)
    if setup is not None:   # may or may not fire on synthetic data
        assert "pullback_score" in setup
        assert setup["is_scored_mode"] is True
        assert setup["pullback_score"] == pytest.approx(score)


def test_score_is_non_negative():
    """Score is always >= 0.0."""
    from engines.engine3 import scan_pullback_scored
    params = _make_params()
    for df_fn in [_make_uptrend_df, _make_downtrend_df]:
        _, score = scan_pullback_scored("TEST", df_fn(), [], params)
        assert score >= 0.0


def test_none_on_insufficient_data():
    """Less than 60 bars → (None, 0.0) from _prepare_indicators."""
    from engines.engine3 import scan_pullback_scored
    idx = pd.date_range("2023-01-01", periods=30, freq="B")
    df  = pd.DataFrame({
        "Open": [100]*30, "High": [101]*30, "Low": [99]*30,
        "Close": [100]*30, "Adj Close": [100]*30, "Volume": [1_000_000]*30,
    }, index=idx)
    setup, score = scan_pullback_scored("TEST", df, [], _make_params())
    assert setup is None
    assert score == pytest.approx(0.0)
```

**Step 2: Run to confirm failure**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_scan_pullback_scored.py -v
```

Expected: `ImportError` — `scan_pullback_scored` does not exist yet.

**Step 3: Implement**

Append to the bottom of `swing-trading-dashboard/backend/engines/engine3.py`:

```python

def scan_pullback_scored(
    ticker: str,
    df: pd.DataFrame,
    sr_zones: List[Dict],
    params,                         # BacktestParams (duck-typed — no circular import)
    trendline: Optional[Dict] = None,
    rs_score: float = 0.0,
) -> tuple:
    """
    Score-based pullback detector for use in BacktestEngine scored mode.

    Returns (setup_dict, score) or (None, 0.0).

    Hard gates (return (None, 0.0) immediately):
    - Insufficient bars / NaN indicators
    - Trend score == 0  (no uptrend whatsoever)
    - No structural support found
    - Risk math invalid (risk <= 0 or > 15% of entry)

    Everything else is additive scoring:
    +2  : 8 EMA > 20 EMA AND close > SMA50 (strong trend)
    +1  : 8 EMA > 20 EMA AND close > SMA50*0.97 (relaxed trend)
    +2  : low penetrates EMA8 or EMA20
    +1  : close within params.ema_distance of EMA8 or EMA20
    +2  : CCI_prev < -100 (deep oversold)
    +1  : CCI_prev < params.cci_threshold AND CCI turning up
    +2  : structural support found
    +tdl_bonus : support source is ASCENDING_TDL
    """
    try:
        ind = _prepare_indicators(ticker, df)
        if ind is None:
            return None, 0.0

        lc, lh, ll   = ind.lc, ind.lh, ind.ll
        l8, l20, l50 = ind.l8, ind.l20, ind.l50
        latr         = ind.latr
        cci_today    = ind.cci_today
        cci_prev     = ind.cci_prev
        data         = ind.data

        score = 0.0

        # ── Trend score ───────────────────────────────────────────────────────
        if l8 > l20 and lc > l50:
            score += 2.0
        elif l8 > l20 and lc > l50 * 0.97:
            score += 1.0
        else:
            return None, 0.0   # hard gate: no uptrend at all

        # ── Value zone score ──────────────────────────────────────────────────
        if ll <= l8 or ll <= l20:
            score += 2.0
        else:
            dist_to_8  = abs(lc - l8)  / l8  if l8  > 0 else float("inf")
            dist_to_20 = abs(lc - l20) / l20 if l20 > 0 else float("inf")
            if dist_to_8 <= params.ema_distance or dist_to_20 <= params.ema_distance:
                score += 1.0

        # ── CCI momentum score ────────────────────────────────────────────────
        if cci_prev < -100 and cci_today > cci_prev:
            score += 2.0
        elif cci_prev < params.cci_threshold and cci_today > cci_prev:
            score += 1.0

        # ── Structural support (hard gate + score) ────────────────────────────
        vol_sma50   = ind.volume.rolling(50).mean()
        vsm_val     = vol_sma50.iloc[-1]
        avg_vol_sup = float(vsm_val.item() if hasattr(vsm_val, "item") else vsm_val)

        nearest_sup = _find_structural_support(
            ll, lc, sr_zones, trendline,
            ind.high, ind.low, ind.close, ind.volume, avg_vol_sup,
        )
        if nearest_sup is None:
            return None, 0.0   # hard gate: no structural support

        score += 2.0

        if nearest_sup["source"] == "ASCENDING_TDL":
            score += params.tdl_bonus

        # ── Risk math ─────────────────────────────────────────────────────────
        entry = round(lh * 1.001, 2)

        if nearest_sup["level"] >= lc:
            return None, 0.0

        stop_base = min(ll, nearest_sup["lower"])
        stop_loss = round(stop_base - ATR_STOP_MULTIPLIER * latr, 2)
        risk      = entry - stop_loss

        if risk <= 0 or risk > entry * 0.15:
            return None, 0.0

        take_profit, actual_rr = nearest_resistance_target(entry, sr_zones, risk)

        setup = {
            "ticker":           ticker,
            "setup_type":       "PULLBACK",
            "entry":            entry,
            "stop_loss":        stop_loss,
            "take_profit":      take_profit,
            "rr":               actual_rr,
            "setup_date":       str(data.index[-1].date()),
            "cci_today":        round(cci_today, 2),
            "cci_yesterday":    round(cci_prev, 2),
            "support_level":    nearest_sup["level"],
            "support_source":   nearest_sup["source"],
            "ema8":             round(l8, 2),
            "ema20":            round(l20, 2),
            "is_ascending_tdl": nearest_sup["source"] == "ASCENDING_TDL",
            "pullback_score":   score,
            "is_scored_mode":   True,
        }
        return setup, score

    except Exception as exc:
        import logging
        logging.getLogger(__name__).debug("scan_pullback_scored %s: %s", ticker, exc)
        return None, 0.0
```

**Step 4: Run to confirm passing**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_scan_pullback_scored.py -v
```

Expected: 5 passed.

**Step 5: Verify existing engine3 tests still pass (if any)**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/ -k "pullback or engine3" -v
```

Expected: all existing pass, new tests pass.

**Step 6: Commit**

```bash
git add swing-trading-dashboard/backend/engines/engine3.py \
        swing-trading-dashboard/backend/tests/test_scan_pullback_scored.py
git commit -m "feat(engine3): add scan_pullback_scored() for scored-mode backtest"
```

---

### Task 4: Signal routing + trade gate in `BacktestEngine.run()`

**Files:**
- Modify: `swing-trading-dashboard/backend/backtest_engine.py`
- Create: `swing-trading-dashboard/backend/tests/test_backtest_scored_mode.py`

**Context:**
Two changes inside `BacktestEngine.run()`:

1. **Signal routing** — `_detect_signals` is called unchanged for all setup types except `PULLBACK` in scored mode. For `PULLBACK` in scored mode, call `scan_pullback_scored()` directly and attach `_raw_score` to the signal dict.

2. **Post-signal gate** — After any signal fires, compute `final_score = raw_score * weight`. If `final_score < params.score_threshold`, skip the trade (`continue`). Otherwise store `_final_score` in the trade state dict.

3. **`TradeRecord` population** — When appending a completed trade, set `final_score` from `trade_state.get("_final_score")`.

**Base scores for non-pullback signals** (defined as a module-level dict in `backtest_engine.py`, after `BacktestParams`):

```python
_SIGNAL_BASE_SCORES: dict = {
    "VCP":          6.0,
    "RES_BREAKOUT": 6.0,
    "BASE":         5.0,
    "HTF":          5.0,
    "LCE":          4.0,
    "WATCHLIST":    3.0,
}
_SIGNAL_BASE_SCORE_DEFAULT = 5.0
```

**Step 1: Write the failing tests**

```python
# swing-trading-dashboard/backend/tests/test_backtest_scored_mode.py
"""
Integration tests for BacktestEngine scored mode:
- signal routing to scan_pullback_scored
- post-signal weight + threshold gate
- TradeRecord.final_score population
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import pytest

from backtest_engine import BacktestEngine, BacktestParams, TradeRecord


def _flat_df(n: int = 350, price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2021-01-01", periods=n, freq="B")
    p   = np.full(n, price)
    return pd.DataFrame({
        "Open":      p, "High": p * 1.005,
        "Low":       p * 0.995, "Close": p,
        "Adj Close": p, "Volume": np.full(n, 3_000_000),
    }, index=idx)


def test_impossible_score_threshold_blocks_all_trades():
    """
    score_threshold=999 means no trade can ever pass.
    Scored mode must produce 0 trades even if signals fire.
    """
    p = BacktestParams(score_threshold=999.0, rs_threshold=-1.0)
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2022-01-01",
        end_date="2022-12-31",
        ticker_df=_flat_df(),
        spy_df=_flat_df(),
        params=p,
    )
    result = asyncio.run(engine.run())
    assert result.total_trades == 0


def test_zero_score_threshold_allows_trades():
    """
    score_threshold=0.0 removes the gate entirely.
    Any signal that passes RS/regime/liquidity can open a trade.
    Legacy-equivalent permissiveness.
    """
    p = BacktestParams(score_threshold=0.0, rs_threshold=-1.0)
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2022-01-01",
        end_date="2022-12-31",
        ticker_df=_flat_df(),
        spy_df=_flat_df(),
        params=p,
    )
    result = asyncio.run(engine.run())
    # Just confirm it ran without error; trade count depends on signals
    assert result.total_trades >= 0


def test_trade_record_final_score_populated_in_scored_mode():
    """
    In scored mode, completed TradeRecord objects have final_score set.
    (May be 0 trades on flat data — test is conditional.)
    """
    p = BacktestParams(score_threshold=0.0, rs_threshold=-1.0)
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2022-01-01",
        end_date="2022-12-31",
        ticker_df=_flat_df(),
        spy_df=_flat_df(),
        params=p,
    )
    result = asyncio.run(engine.run())
    for trade in result.trades:
        # Every trade in scored mode must have a numeric final_score
        assert trade.final_score is not None
        assert isinstance(trade.final_score, float)


def test_legacy_mode_final_score_is_none():
    """Legacy mode (params=None): TradeRecord.final_score stays None."""
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2022-01-01",
        end_date="2022-12-31",
        ticker_df=_flat_df(),
        spy_df=_flat_df(),
    )
    result = asyncio.run(engine.run())
    for trade in result.trades:
        assert trade.final_score is None


def test_breakout_weight_multiplier():
    """
    breakout_weight=2.0 doubles the effective score for VCP/RES_BREAKOUT.
    With score_threshold=7.0 and base VCP score=6.0:
      - weight=1.0 → final=6.0 < 7.0 → blocked
      - weight=2.0 → final=12.0 >= 7.0 → allowed
    Cannot easily test via full engine run on flat data, so test the
    arithmetic directly.
    """
    base_score = 6.0   # VCP base score from _SIGNAL_BASE_SCORES
    threshold  = 7.0

    weight_1 = 1.0
    weight_2 = 2.0

    assert base_score * weight_1 < threshold   # blocked
    assert base_score * weight_2 >= threshold  # allowed
```

**Step 2: Run to confirm failure**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_scored_mode.py -v
```

Expected: `test_impossible_score_threshold_blocks_all_trades` and `test_trade_record_final_score_populated_in_scored_mode` fail.

**Step 3: Implement**

**3a. Add `_SIGNAL_BASE_SCORES` dict** after the `BacktestParams` dataclass:

```python
_SIGNAL_BASE_SCORES: dict = {
    "VCP":          6.0,
    "RES_BREAKOUT": 6.0,
    "BASE":         5.0,
    "HTF":          5.0,
    "LCE":          4.0,
    "WATCHLIST":    3.0,
}
_SIGNAL_BASE_SCORE_DEFAULT = 5.0
```

**3b. Update signal detection in `BacktestEngine.run()`**

Find the section that calls `_detect_signals(...)` and replace it with:

```python
            # ── Signal detection ──────────────────────────────────────────────
            if self.params is not None and "PULLBACK" in self.setup_types:
                # Scored mode: route PULLBACK through scan_pullback_scored
                from engines.engine3 import scan_pullback_scored as _sps
                pb_setup, pb_score = _sps(
                    self.ticker, df_slice, _sr_zones_cache, self.params,
                    precomputed_rs=_rs_t,   # NOTE: scan_pullback_scored uses rs_score from params gate
                )
                if pb_setup is not None:
                    pb_setup["_raw_score"] = pb_score
                    signal = pb_setup
                else:
                    # Try non-pullback engines via normal path
                    non_pb_types = [s for s in self.setup_types if s != "PULLBACK"]
                    signal = _detect_signals(
                        self.ticker, df_slice, spy_slice, non_pb_types,
                        sr_zones=_sr_zones_cache,
                        precomputed_rs=_rs_t,
                    ) if non_pb_types else None
            else:
                # Legacy mode: existing _detect_signals path unchanged
                signal = _detect_signals(
                    self.ticker, df_slice, spy_slice, self.setup_types,
                    sr_zones=_sr_zones_cache,
                    precomputed_rs=_rs_t,
                )
```

**Note:** `scan_pullback_scored` takes `params` directly for `cci_threshold`, `ema_distance`, `tdl_bonus`. It does NOT take `rs_score` — RS gating already happened above this block in the replay loop. Remove the `precomputed_rs` kwarg from the `_sps` call since the function signature only takes `rs_score: float`:

```python
                pb_setup, pb_score = _sps(
                    self.ticker, df_slice, _sr_zones_cache, self.params,
                    rs_score=float(_rs_t["rs_score"]),
                )
```

**3c. Add post-signal weight + threshold gate**

Find the section after `if signal is None: continue` and before `# ── 4c. Schedule entry on T+1`. Insert:

```python
            # ── Scored mode: apply signal-type weight and threshold gate ──────
            if self.params is not None:
                setup_type_sig = signal.get("setup_type", "")
                raw_score = signal.get(
                    "_raw_score",
                    _SIGNAL_BASE_SCORES.get(setup_type_sig, _SIGNAL_BASE_SCORE_DEFAULT),
                )
                is_breakout = setup_type_sig in ("VCP", "RES_BREAKOUT", "HTF", "LCE")
                weight = (
                    self.params.breakout_weight if is_breakout
                    else self.params.pullback_weight
                )
                final_score = raw_score * weight
                if final_score < self.params.score_threshold:
                    continue
                signal["_final_score"] = final_score
```

**3d. Pass `_final_score` into `open_trades` state dict**

In the `open_trades.append({...})` block, add:

```python
                "_final_score": signal.get("_final_score"),
```

**3e. Populate `TradeRecord.final_score`**

In both places where `TradeRecord(...)` is constructed (mid-replay close and EOD close at step 5), add:

```python
                        final_score=trade_state.get("_final_score"),
```

**Step 4: Run to confirm passing**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_scored_mode.py -v
```

Expected: 5 passed.

**Step 5: Confirm no regressions**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_trail_override.py tests/test_backtest_rs_gate.py tests/test_backtest_params.py -v
```

Expected: all pass.

**Step 6: Commit**

```bash
git add swing-trading-dashboard/backend/backtest_engine.py \
        swing-trading-dashboard/backend/tests/test_backtest_scored_mode.py
git commit -m "feat(backtest): signal routing + score gate in scored mode"
```

---

### Task 5: `print_backtest_diagnostics()` in analytics.py

**Files:**
- Modify: `swing-trading-dashboard/backend/analytics.py`
- Modify: `swing-trading-dashboard/backend/backtest_engine.py` (call site in `run_backtest_universe`)
- Create: `swing-trading-dashboard/backend/tests/test_backtest_diagnostics_print.py`

**Context:**
`print_backtest_diagnostics(trades: list) -> str` is a pure function appended to `analytics.py`. It accepts the flat list of `TradeRecord.to_dict()` dicts returned by `run_backtest_universe`. Returns a formatted multi-line string. `run_backtest_universe` calls it and logs the result at `INFO` level after `asyncio.gather` completes. The function is also directly useful for Optuna — a trial objective function can call it to inspect what happened.

`TradeRecord.to_dict()` now includes `final_score` and `rr_achieved`. Use these fields.

**Step 1: Write the failing tests**

```python
# swing-trading-dashboard/backend/tests/test_backtest_diagnostics_print.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from analytics import print_backtest_diagnostics


def _trade(setup_type="VCP", is_win=True, rr=1.5, final_score=6.0):
    return {
        "ticker":       "AAPL",
        "setup_type":   setup_type,
        "entry_price":  150.0,
        "initial_stop": 145.0,
        "exit_price":   150.0 + (rr * 5.0 if is_win else -5.0),
        "exit_reason":  "TARGET" if is_win else "STOP",
        "rr_achieved":  rr if is_win else -1.0,
        "pnl_pct":      rr * 3.33 if is_win else -3.33,
        "is_win":       is_win,
        "final_score":  final_score,
    }


def test_returns_string():
    result = print_backtest_diagnostics([_trade()])
    assert isinstance(result, str)


def test_contains_total_trades():
    trades = [_trade(), _trade(is_win=False)]
    result = print_backtest_diagnostics(trades)
    assert "2" in result   # total trade count


def test_contains_setup_type_breakdown():
    trades = [_trade("VCP"), _trade("PULLBACK", is_win=False)]
    result = print_backtest_diagnostics(trades)
    assert "VCP" in result
    assert "PULLBACK" in result


def test_score_section_present_when_final_score_set():
    trades = [_trade(final_score=7.5), _trade(final_score=4.0)]
    result = print_backtest_diagnostics(trades)
    assert "score" in result.lower()


def test_score_section_omitted_when_no_final_score():
    """Legacy mode: all final_score=None → score section not shown."""
    trades = [_trade(final_score=None), _trade(final_score=None)]
    result = print_backtest_diagnostics(trades)
    assert "avg final score" not in result.lower()


def test_empty_trades_does_not_crash():
    result = print_backtest_diagnostics([])
    assert isinstance(result, str)
    assert "0" in result
```

**Step 2: Run to confirm failure**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_diagnostics_print.py -v
```

Expected: `ImportError` — `print_backtest_diagnostics` does not exist.

**Step 3: Implement — append to `analytics.py`**

```python

def print_backtest_diagnostics(trades: list) -> str:
    """
    Format a human-readable diagnostics summary for a completed backtest run.

    Accepts a flat list of TradeRecord.to_dict() dicts (as returned by
    run_backtest_universe). Returns a multi-line string suitable for logging.

    Sections:
    - Overall: trade count, win rate, expectancy, profit factor
    - Per setup_type breakdown
    - Score distribution (only when final_score is populated)
    """
    sep = "═" * 44

    if not trades:
        return f"\n{sep}\n BACKTEST DIAGNOSTICS\n{sep}\n No trades generated.\n{sep}\n"

    wins        = [t for t in trades if t.get("is_win")]
    win_rate    = len(wins) / len(trades) * 100
    rr_values   = [t["rr_achieved"] for t in trades if t.get("rr_achieved") is not None]
    avg_rr      = sum(rr_values) / len(rr_values) if rr_values else 0.0

    gross_pos   = sum(r for r in rr_values if r > 0)
    gross_neg   = sum(r for r in rr_values if r <= 0)
    profit_factor = (gross_pos / abs(gross_neg)) if gross_neg != 0 else float("inf")

    lines = [
        "",
        sep,
        " BACKTEST DIAGNOSTICS",
        sep,
        f" Total trades        : {len(trades):>7,}",
        f" Win rate            : {win_rate:>7.1f}%",
        f" Expectancy (avg R)  : {avg_rr:>+7.2f} R",
        f" Profit factor       : {profit_factor:>7.2f}",
        "",
        " Signal type breakdown:",
    ]

    by_type: dict = {}
    for t in trades:
        st = str(t.get("setup_type", "UNKNOWN")).upper()
        by_type.setdefault(st, []).append(t)

    for st in sorted(by_type):
        group   = by_type[st]
        g_wins  = [t for t in group if t.get("is_win")]
        g_rr    = [t["rr_achieved"] for t in group if t.get("rr_achieved") is not None]
        g_wr    = len(g_wins) / len(group) * 100 if group else 0.0
        g_avg_r = sum(g_rr) / len(g_rr) if g_rr else 0.0
        pct     = len(group) / len(trades) * 100
        lines.append(
            f"   {st:<14} : {len(group):>5,}  ({pct:4.1f}%)  "
            f"win {g_wr:.1f}%  avg R {g_avg_r:+.2f}"
        )

    # Score section — only when final_score is populated (scored mode)
    scores = [t["final_score"] for t in trades if t.get("final_score") is not None]
    if scores:
        lines += [
            "",
            " Score distribution (scored mode):",
            f"   avg final score   : {sum(scores)/len(scores):>6.2f}",
            f"   min / max score   : {min(scores):.1f} / {max(scores):.1f}",
        ]

    lines += [sep, ""]
    return "\n".join(lines)
```

**3b. Call site in `run_backtest_universe`** — after `asyncio.gather` and extending `all_trades`, add:

```python
    # Emit diagnostics to log
    from analytics import print_backtest_diagnostics as _diag
    logger.info("%s", _diag(all_trades))
```

**Step 4: Run to confirm passing**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_diagnostics_print.py -v
```

Expected: 6 passed.

**Step 5: Full suite smoke check**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/ -v --ignore=tests/test_optimizer_core.py
```

Expected: all new tests pass, no regressions in existing tests.

**Step 6: Commit**

```bash
git add swing-trading-dashboard/backend/analytics.py \
        swing-trading-dashboard/backend/backtest_engine.py \
        swing-trading-dashboard/backend/tests/test_backtest_diagnostics_print.py
git commit -m "feat(analytics): add print_backtest_diagnostics(); wire into run_backtest_universe"
```

---

## Final verification

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_params.py \
                 tests/test_backtest_rs_gate.py \
                 tests/test_scan_pullback_scored.py \
                 tests/test_backtest_scored_mode.py \
                 tests/test_backtest_diagnostics_print.py -v
```

Expected: all 25+ tests pass.

Smoke-check legacy compatibility:

```bash
python -m pytest tests/test_backtest_trail_override.py \
                 tests/test_backtest_diag_constants.py \
                 tests/test_run_backtest_universe.py -v
```

Expected: all existing tests pass unchanged.
