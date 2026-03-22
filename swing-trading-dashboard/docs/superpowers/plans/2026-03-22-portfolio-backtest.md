# Portfolio-Coordinated Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-ticker independent backtest with a global-cap portfolio simulation, add UI config, and fix the "V4 baseline" label.

**Architecture:** New `portfolio_backtest.py` owns the coordinator (`run_portfolio_backtest_universe`), two dataclasses (`BacktestConfig`, `TickerSimState`), and private helpers. `BacktestEngine` gains a `prepare()` method that extracts data-loading from `run()` so both paths share the same logic. `main.py` endpoint accepts an optional JSON body. `DiagnosticsTab.jsx` gains a compact config panel above the run button.

**Tech Stack:** Python 3.10+, FastAPI, asyncio, pandas/numpy, React 18

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `backend/portfolio_backtest.py` | `BacktestConfig`, `TickerSimState`, `_detect_signals_for_date`, `_build_open_position`, `_build_trade_record`, `run_portfolio_backtest_universe` |
| Modify | `backend/backtest_engine.py` | Add `BacktestEngine.prepare()`; refactor `run()` to delegate data-loading to it |
| Modify | `backend/main.py` | `BacktestRunRequest` Pydantic model; updated `/api/diagnostics/backtest/run` endpoint |
| Modify | `frontend/src/components/DiagnosticsTab.jsx` | Config state, config panel UI, label fix, updated API call |
| Create | `backend/tests/test_portfolio_backtest.py` | Unit tests for the new module |

---

## Task 1: portfolio_backtest.py — Dataclasses + Signal Detection Helper

**Files:**
- Create: `backend/portfolio_backtest.py`
- Create: `backend/tests/test_portfolio_backtest.py`

### Context

`_detect_signals` in `backtest_engine.py` has signature:
```python
def _detect_signals(ticker, df_slice, spy_slice, setup_types, sr_zones=None, precomputed_rs=None, params=None)
```
Note: `setup_types` is the **4th** positional arg (not `sr_zones`). Callers that swap these will silently pass wrong data.

`scan_pullback_scored` is in `backend/engines/engine3.py`.
`scan_vcp` is in `backend/engines/engine2.py` with signature:
```python
def scan_vcp(ticker, df, sr_zones, spy_3m_return=0.0, rs_score=0.0, ...) -> Optional[Dict]
```
(No `spy_df` param — it takes `spy_3m_return` as a float.)

VCP co-signal boost is `params.vcp_bonus` (a `BacktestParams` field, default 1.370). There is **no** `VCP_COSIGNAL_BOOST` constant.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_portfolio_backtest.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_backtest_config_defaults():
    from portfolio_backtest import BacktestConfig
    cfg = BacktestConfig()
    assert cfg.start_date == "2017-01-01"
    assert cfg.end_date == "2024-12-31"
    assert cfg.max_positions == 4
    assert cfg.ticker_count is None
    assert cfg.min_score == 0.0
    assert "PULLBACK" in cfg.setup_types
    assert "VCP" not in cfg.setup_types


def test_ticker_sim_state_mutable_reset():
    """Mutable fields reset to defaults on fresh construction."""
    from portfolio_backtest import TickerSimState
    import pandas as pd
    ts = TickerSimState(
        ticker="TEST",
        ticker_df=pd.DataFrame(),
        spy_df=pd.DataFrame(),
        adj_col="Close",
        ticker_dates=pd.DatetimeIndex([]),
        ema20_full=pd.Series(dtype=float),
        atr14_full=pd.Series(dtype=float),
        sr_zones_cache=[],
        rs_ratio_s=pd.Series(dtype=float),
        rs_52wh_s=pd.Series(dtype=float),
        rs_score_s=pd.Series(dtype=float),
        spy_3m_s=pd.Series(dtype=float),
        params=None,
    )
    assert ts.is_in_trade is False
    assert ts.last_close_date is None


def test_run_portfolio_backtest_universe_empty():
    """Empty ticker list returns empty list immediately."""
    import asyncio
    from portfolio_backtest import run_portfolio_backtest_universe, BacktestConfig
    result = asyncio.run(run_portfolio_backtest_universe([], BacktestConfig()))
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

```
cd swing-trading-dashboard/backend
python -m pytest tests/test_portfolio_backtest.py -v
```
Expected: `ModuleNotFoundError: No module named 'portfolio_backtest'`

- [ ] **Step 3: Create `backend/portfolio_backtest.py`**

```python
"""
Portfolio-coordinated backtest.

Replaces the per-ticker independent run_backtest_universe() with a global
portfolio cap: at most BacktestConfig.max_positions trades open at any time.
When a slot opens, the highest-scoring available signal fills it.

Public API
----------
run_portfolio_backtest_universe(tickers, config, params, progress_cb)
    -> List[dict]   (same TradeRecord.to_dict() format as run_backtest_universe)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import constants as _constants
from constants import (
    CONCURRENCY_LIMIT,
    RS_BLUE_DOT_TOLERANCE_PCT,
    SELECTIVE_SETUP_WEIGHTS,   # confirmed in constants.py: {"PULLBACK": 0.5, "RES_BREAKOUT": 1.0}
    SELECTIVE_HARD_FILTER,     # confirmed in constants.py: False
)
from filters import compute_regime_label_series, passes_liquidity

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public config
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    """User-configurable parameters for run_portfolio_backtest_universe()."""
    start_date:    str           = "2017-01-01"
    end_date:      str           = "2024-12-31"
    max_positions: int           = 4
    ticker_count:  Optional[int] = None      # None = full universe
    min_score:     float         = 0.0
    setup_types:   List[str]     = field(default_factory=lambda: [
        "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"
    ])
    # VCP intentionally excluded: used only as a co-signal boost in scored mode,
    # never as a standalone trade entry.


# ─────────────────────────────────────────────────────────────────────────────
# Per-ticker prepared state
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TickerSimState:
    """
    All pre-computed data for one ticker. Produced by BacktestEngine.prepare().

    Immutable fields (set once, never changed):
        ticker, ticker_df, spy_df, adj_col, ticker_dates, ema20_full, atr14_full,
        sr_zones_cache, rs_ratio_s, rs_52wh_s, rs_score_s, spy_3m_s, params

    Mutable runtime fields (reset at start of each portfolio run):
        is_in_trade, last_close_date
    """
    # ── Immutable data ──────────────────────────────────────────────────────
    ticker:          str
    ticker_df:       pd.DataFrame
    spy_df:          pd.DataFrame
    adj_col:         str
    ticker_dates:    pd.DatetimeIndex
    ema20_full:      pd.Series
    atr14_full:      Optional[pd.Series]
    sr_zones_cache:  list
    rs_ratio_s:      pd.Series
    rs_52wh_s:       pd.Series
    rs_score_s:      pd.Series
    spy_3m_s:        pd.Series
    params:          object  # Optional[BacktestParams] — typed as object to avoid circular import
    # ── Mutable runtime state ───────────────────────────────────────────────
    is_in_trade:     bool           = False
    last_close_date: Optional[date] = None


# ─────────────────────────────────────────────────────────────────────────────
# Signal detection helper
# ─────────────────────────────────────────────────────────────────────────────

def _detect_signals_for_date(
    ts: TickerSimState,
    T_date: pd.Timestamp,
    full_idx: int,
    setup_types: List[str],
) -> Optional[dict]:
    """
    Detect one setup signal for ticker ts on date T_date (bar at full_idx).

    Mirrors BacktestEngine.run() signal detection:
      - Scored mode (ts.params is not None):
          PULLBACK routed through scan_pullback_scored with VCP co-signal boost.
          Other types routed through _detect_signals with params forwarded.
          Sets _raw_score on the returned signal.
      - Legacy mode (ts.params is None):
          All types routed through _detect_signals.

    Returns raw signal dict (with _raw_score) or None. No scoring/threshold applied.
    """
    from backtest_engine import _detect_signals, _SIGNAL_BASE_SCORES, _SIGNAL_BASE_SCORE_DEFAULT

    df_slice  = ts.ticker_df.iloc[:full_idx + 1]
    spy_slice = ts.spy_df.loc[ts.spy_df.index <= T_date]

    rs_t = {
        "rs_ratio":    float(ts.rs_ratio_s.iloc[full_idx]),
        "rs_52w_high": float(ts.rs_52wh_s.iloc[full_idx]),
        "rs_blue_dot": bool(
            ts.rs_ratio_s.iloc[full_idx] >= ts.rs_52wh_s.iloc[full_idx] * (1.0 - RS_BLUE_DOT_TOLERANCE_PCT)
        ),
        "rs_score":    float(ts.rs_score_s.iloc[full_idx]),
        "spy_3m":      float(ts.spy_3m_s.iloc[full_idx]),
    }

    if ts.params is not None:
        # RS threshold gate (same as BacktestEngine.run() line 886)
        if rs_t["rs_score"] < ts.params.rs_threshold:
            return None

        if "PULLBACK" in setup_types:
            from engines.engine3 import scan_pullback_scored as _sps
            pb_setup, pb_score = _sps(
                ts.ticker, df_slice, ts.sr_zones_cache, ts.params,
                rs_score=rs_t["rs_score"],
            )
            if pb_setup is not None:
                # VCP co-signal boost (best-effort, never blocks pullback)
                try:
                    from engines.engine2 import scan_vcp as _scan_vcp
                    _vcp = _scan_vcp(
                        ts.ticker, df_slice, ts.sr_zones_cache,
                        spy_3m_return=rs_t["spy_3m"],
                        rs_score=rs_t["rs_score"],
                    )
                    if _vcp is not None:
                        pb_score += ts.params.vcp_bonus
                except Exception:
                    pass
                pb_setup["_raw_score"] = pb_score
                return pb_setup

        non_pb = [s for s in setup_types if s not in ("PULLBACK", "VCP")]
        if non_pb:
            return _detect_signals(
                ts.ticker, df_slice, spy_slice, non_pb,
                sr_zones=ts.sr_zones_cache,
                precomputed_rs=rs_t,
                params=ts.params,
            )
        return None

    # Legacy mode
    return _detect_signals(
        ts.ticker, df_slice, spy_slice, setup_types,
        sr_zones=ts.sr_zones_cache,
        precomputed_rs=rs_t,
        params=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Position management helpers
# ─────────────────────────────────────────────────────────────────────────────

_META_KEYS = (
    "volume_ratio", "breakout_pct", "resistance_level",
    "zone_upper", "support_level", "support_source", "zone_source",
    "pullback_score", "days_since_breakout", "geometry",
    "atr", "entry",
)


def _build_open_position(
    signal: dict,
    ts: TickerSimState,
    signal_date: pd.Timestamp,
    entry_date: pd.Timestamp,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    full_idx: int,
) -> dict:
    """
    Build the open-position dict used by _manage_open_trade().

    trade_state keys must match what _manage_open_trade() and _build_trade_record()
    expect — mirrors the open_trades.append() block in BacktestEngine.run().
    """
    from backtest_engine import _extract_ref_level

    sig_type   = signal.get("setup_type", "")
    setup_meta = {k: signal[k] for k in _META_KEYS if k in signal}

    # Per-setup trail multiplier overrides (matches BacktestEngine.run() lines 1032-1037)
    trail_mult = None
    if ts.params is not None:
        if sig_type == "RES_BREAKOUT":
            trail_mult = ts.params.brk_trail_mult
        elif sig_type == "BASE":
            trail_mult = ts.params.base_trail_mult

    trail_mode = ts.params.trail_mode if ts.params is not None else _constants.TRAIL_MODE

    return {
        "ticker_state": ts,
        "trade_state": {
            "setup_type":          sig_type,
            "ticker":              ts.ticker,
            "signal_date":         signal_date.strftime("%Y-%m-%d"),
            "entry_date":          entry_date.strftime("%Y-%m-%d"),
            "entry_price":         entry_price,
            "initial_stop":        stop_loss,
            "trailing_stop":       stop_loss,
            "take_profit":         take_profit,
            "trail_mult_override": trail_mult,
            "_final_score":        signal.get("_final_score"),
            "_regime":             signal.get("_regime", "UNKNOWN"),
            "_rs_score":           float(ts.rs_score_s.iloc[full_idx]),
            "_setup_meta":         setup_meta,
            "_trail_mode":         trail_mode,
            "_trail_triggered":    False,
            "_bars_since_entry":   0,
            "_ref_level":          _extract_ref_level(setup_meta, sig_type),
            "_prev_ema20":         None,
        },
    }


def _build_trade_record(
    pos: dict,
    exit_date: pd.Timestamp,
    exit_price: float,
    exit_reason: str,
) -> dict:
    """Build a TradeRecord.to_dict() compatible dict from a completed position."""
    from backtest_engine import TradeRecord

    ts    = pos["ticker_state"]
    state = pos["trade_state"]

    entry_dt     = pd.Timestamp(state["entry_date"])
    holding_days = max(1, (exit_date - entry_dt).days)

    return TradeRecord(
        ticker       = ts.ticker,
        setup_type   = state["setup_type"],
        signal_date  = state["signal_date"],
        entry_date   = state["entry_date"],
        entry_price  = state["entry_price"],
        initial_stop = state["initial_stop"],
        take_profit  = state["take_profit"],
        exit_date    = exit_date.strftime("%Y-%m-%d"),
        exit_price   = exit_price,
        exit_reason  = exit_reason,
        holding_days = holding_days,
        final_score  = state.get("_final_score"),
        regime       = state.get("_regime", "UNKNOWN"),
        rs_score     = state.get("_rs_score", 0.0),
        setup_meta   = state.get("_setup_meta", {}),
        trail_mode   = state.get("_trail_mode", "atr"),
        trail_phase  = ("ema20" if state.get("_trail_triggered") else "initial"),
    ).to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# Stub for portfolio runner (implemented in Task 4)
# ─────────────────────────────────────────────────────────────────────────────

async def run_portfolio_backtest_universe(
    tickers: List[str],
    config: BacktestConfig,
    params=None,
    progress_cb=None,
) -> List[dict]:
    """
    Portfolio-coordinated backtest. Stub — full implementation in Task 4.
    """
    if not tickers:
        return []
    raise NotImplementedError("Implement in Task 4")
```

- [ ] **Step 4: Run tests — dataclass and empty-list tests pass, NotImplementedError test may fail**

```
cd swing-trading-dashboard/backend
python -m pytest tests/test_portfolio_backtest.py::test_backtest_config_defaults tests/test_portfolio_backtest.py::test_ticker_sim_state_mutable_reset -v
```
Expected: 2 PASSED.

The `test_run_portfolio_backtest_universe_empty` test should also pass because the `if not tickers: return []` guard runs before the `raise NotImplementedError`.

```
python -m pytest tests/test_portfolio_backtest.py -v
```
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/portfolio_backtest.py backend/tests/test_portfolio_backtest.py
git commit -m "feat: add portfolio_backtest.py dataclasses and signal detection helper"
```

---

## Task 2: BacktestEngine.prepare() method

**Files:**
- Modify: `backend/backtest_engine.py` (add `prepare()` method to `BacktestEngine` class)

### Context

`BacktestEngine.__init__` is at line ~662. The `run()` method starts at line ~688. Sections 1–3 of `run()` (lines ~696–778) handle data fetch, replay window, price column ID, SR zones, indicator compute, and RS series. `prepare()` extracts exactly this work.

WFO compatibility: `wfo_engine.py` pre-loads `ticker_df` and `spy_df` on the engine instance before calling `run()`. The `prepare()` method checks `if self.ticker_df is not None` and skips the network fetch — so WFO continues to work unchanged.

The `prepare()` method does a lazy import: `from portfolio_backtest import TickerSimState`. This is inside the method body (not module level) to avoid circular import between `backtest_engine.py` and `portfolio_backtest.py`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_portfolio_backtest.py`:

```python
def test_backtest_engine_has_prepare_method():
    from backtest_engine import BacktestEngine
    engine = BacktestEngine("AAPL", "2023-01-01", "2023-03-01")
    assert hasattr(engine, "prepare")
    assert callable(engine.prepare)
```

- [ ] **Step 2: Run test to verify it fails**

```
cd swing-trading-dashboard/backend
python -m pytest tests/test_portfolio_backtest.py::test_backtest_engine_has_prepare_method -v
```
Expected: FAIL — `AttributeError: 'BacktestEngine' object has no attribute 'prepare'`

- [ ] **Step 3: Add `prepare()` to `BacktestEngine`**

Add this method to the `BacktestEngine` class in `backend/backtest_engine.py`, after `__init__` and before `run()`:

```python
async def prepare(self, shared_spy_df: Optional[pd.DataFrame] = None) -> "Optional[TickerSimState]":
    """
    Fetch and pre-compute all data for this ticker.

    Returns a TickerSimState ready for use by run_portfolio_backtest_universe().
    Returns None if data fetch fails or the ticker has insufficient history.

    WFO compatibility: if self.ticker_df and self.spy_df are already set
    (pre-loaded by wfo_engine.py), uses them directly without re-fetching.

    shared_spy_df: pass the already-fetched SPY df to avoid re-downloading
                   SPY once per ticker (used by the portfolio coordinator).
    """
    # ── 1. Fetch or use preloaded data ────────────────────────────────────
    if self.ticker_df is not None and self.spy_df is not None:
        ticker_df = self.ticker_df
        spy_df    = self.spy_df
    else:
        ticker_df, spy_df_fetched = await _fetch_data(self.ticker, self.start_date)
        spy_df = shared_spy_df if shared_spy_df is not None else spy_df_fetched
        if ticker_df is None or spy_df is None:
            logger.warning("BacktestEngine.prepare: data fetch failed for %s", self.ticker)
            return None

    # ── 2. Price column identification ────────────────────────────────────
    adj_col = "Adj Close" if "Adj Close" in ticker_df.columns else "Close"

    # ── 3. SR zones (full window — same intentional trade-off as run()) ───
    from engines.engine1 import calculate_sr_zones as _calc_sr_zones
    sr_zones_cache = _calc_sr_zones(self.ticker, ticker_df)

    # ── 4. Indicator columns ──────────────────────────────────────────────
    if "_EMA8" not in ticker_df.columns:
        ticker_df = ticker_df.copy()
        _c = ticker_df[adj_col]
        _h = ticker_df["High"]
        _l = ticker_df["Low"]
        ticker_df["_EMA8"]    = _ema(_c, 8)
        ticker_df["_EMA20"]   = _ema(_c, 20)
        ticker_df["_SMA50"]   = _sma(_c, 50)
        ticker_df["_SMA200"]  = _sma(_c, 200)
        ticker_df["_ATR14"]   = _atr(_h, _l, _c, 14)
        ticker_df["_CCI20"]   = _cci(_h, _l, _c, 20)
        if "Volume" in ticker_df.columns:
            ticker_df["_VOLSMA50"] = ticker_df["Volume"].rolling(50, min_periods=10).mean()

    ema20_full = ticker_df["_EMA20"]
    atr14_full = ticker_df["_ATR14"] if "_ATR14" in ticker_df.columns else None

    # ── 5. RS series (O(1) per-bar lookup in the coordinator loop) ────────
    _close_s     = ticker_df[adj_col]
    _spy_adj     = "Adj Close" if "Adj Close" in spy_df.columns else "Close"
    _spy_aligned = spy_df[_spy_adj].reindex(ticker_df.index, method="ffill").fillna(0.0)
    _mask        = _spy_aligned > 0
    _rs_ratio_s  = pd.Series(0.0, index=ticker_df.index)
    _rs_ratio_s[_mask] = _close_s[_mask] / _spy_aligned[_mask]
    _rs_52wh_s   = _rs_ratio_s.rolling(252, min_periods=1).max()

    _PERIODS = [63, 126, 189, 252]
    _WEIGHTS = [0.40, 0.20, 0.20, 0.20]
    _rs_score_s = pd.Series(0.0, index=ticker_df.index)
    _rs_wt_s    = pd.Series(0.0, index=ticker_df.index)
    for _p, _w in zip(_PERIODS, _WEIGHTS):
        _tk_ret  = _close_s / _close_s.shift(_p) - 1.0
        _spy_ret = _spy_aligned / _spy_aligned.shift(_p) - 1.0
        _valid   = ~(_tk_ret.isna() | _spy_ret.isna() | ~_mask)
        _rs_score_s = _rs_score_s + _w * (_tk_ret.where(_valid, 0.0) - _spy_ret.where(_valid, 0.0))
        _rs_wt_s    = _rs_wt_s    + _w * _valid.astype(float)
    _rs_score_s = (_rs_score_s / _rs_wt_s.replace(0.0, np.nan)).fillna(0.0)
    _spy_3m_s   = (_spy_aligned / _spy_aligned.shift(63) - 1.0).fillna(0.0)

    # Lazy import to avoid circular import (portfolio_backtest imports backtest_engine)
    from portfolio_backtest import TickerSimState
    return TickerSimState(
        ticker       = self.ticker,
        ticker_df    = ticker_df,
        spy_df       = spy_df,
        adj_col      = adj_col,
        ticker_dates = ticker_df.index,
        ema20_full   = ema20_full,
        atr14_full   = atr14_full,
        sr_zones_cache = sr_zones_cache,
        rs_ratio_s   = _rs_ratio_s,
        rs_52wh_s    = _rs_52wh_s,
        rs_score_s   = _rs_score_s,
        spy_3m_s     = _spy_3m_s,
        params       = self.params,
    )
```

- [ ] **Step 4: Run test**

```
cd swing-trading-dashboard/backend
python -m pytest tests/test_portfolio_backtest.py::test_backtest_engine_has_prepare_method -v
```
Expected: PASSED.

Also run all portfolio tests to confirm nothing broken:
```
python -m pytest tests/test_portfolio_backtest.py -v
```
Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_portfolio_backtest.py
git commit -m "feat: add BacktestEngine.prepare() for portfolio coordinator"
```

---

## Task 3: BacktestEngine.run() delegates to prepare()

**Files:**
- Modify: `backend/backtest_engine.py` (refactor `run()` sections 1–3 to call `prepare()`)

### Context

`BacktestEngine.run()` starts at line ~688. Sections 1–3 (lines ~696–778) are: data fetch, replay window, SR zones, indicator columns, RS series. After this refactor, `run()` calls `await self.prepare()` for sections 1–3 and unpacks the returned `TickerSimState`. The replay loop (sections 4–5) uses the unpacked fields unchanged.

This refactor must not change `run()`'s observable behavior. The existing test suite (`tests/test_backtest_engine.py`, `tests/test_backtest_scored_mode.py`, etc.) serves as the regression guard.

- [ ] **Step 1: Run existing backtest tests to establish baseline**

```
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_engine.py tests/test_backtest_scored_mode.py tests/test_backtest_trail_override.py tests/test_backtest_preloaded_df.py -v
```
Expected: all PASSED. Note the count — all must still pass after the refactor.

- [ ] **Step 2: Refactor `run()` to call `prepare()`**

Replace the content of `run()` from the start of the method through the end of section 3d (the RS series computation, just before the `# ── 4. Replay loop` comment). Replace it with:

```python
async def run(self) -> BacktestSummary:
    """Execute the backtest. Returns a BacktestSummary with all closed trades."""
    run_id = self.run_id
    logger.info(
        "Backtest [%s] %s %s→%s starting",
        run_id, self.ticker, self.start_date, self.end_date,
    )

    # ── 1–3. Fetch data and pre-compute indicators/RS via prepare() ───────
    state = await self.prepare()
    if state is None:
        return compute_metrics(
            self.ticker, "+".join(self.setup_types),
            self.start_date, self.end_date, [], run_id,
        )

    ticker_df       = state.ticker_df
    spy_df          = state.spy_df
    adj_col         = state.adj_col
    _sr_zones_cache = state.sr_zones_cache
    ema20_full      = state.ema20_full
    _rs_ratio_s     = state.rs_ratio_s
    _rs_52wh_s      = state.rs_52wh_s
    _rs_score_s     = state.rs_score_s
    _spy_3m_s       = state.spy_3m_s

    # ── 2. Identify replay window ─────────────────────────────────────────
    start = pd.Timestamp(self.start_date)
    end   = pd.Timestamp(self.end_date)

    all_dates    = ticker_df.index
    replay_dates = all_dates[(all_dates >= start) & (all_dates <= end)]

    if len(replay_dates) < 2:
        logger.warning("Backtest: no dates in replay window for %s", self.ticker)
        return compute_metrics(
            self.ticker, "+".join(self.setup_types),
            self.start_date, self.end_date, [], run_id,
        )

    # ── 4. Replay loop ... (unchanged from original)
```

Key: Keep `_close_s = ticker_df[adj_col]` and `ema20_full = ticker_df["_EMA20"]` assignments if they appear independently in section 4; check and keep them if used later in `run()`.

**Exact edit:** In the current `run()`, locate the block `if self.ticker_df is not None and self.spy_df is not None:` (section 1) through the line `_spy_3m_s = (_spy_aligned / ...` (end of section 3d). Delete this entire block and replace with the delegation code above.

- [ ] **Step 3: Run existing backtest tests**

```
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_engine.py tests/test_backtest_scored_mode.py tests/test_backtest_trail_override.py tests/test_backtest_preloaded_df.py tests/test_backtest_rs_gate.py -v
```
Expected: same count of PASSED as Step 1 baseline.

Also run all portfolio tests:
```
python -m pytest tests/test_portfolio_backtest.py -v
```
Expected: all still PASSED.

- [ ] **Step 4: Commit**

```bash
git add backend/backtest_engine.py
git commit -m "refactor: run() delegates data loading to prepare() — no behavior change"
```

---

## Task 4: run_portfolio_backtest_universe() — Full Implementation

**Files:**
- Modify: `backend/portfolio_backtest.py` (replace stub with full implementation)

### Context

The coordinator runs in two phases:
- **Phase 1** (parallel): fetch and prepare all tickers using `BacktestEngine.prepare()`, sharing one SPY fetch
- **Phase 2** (sequential): single day-by-day loop across the union calendar; advance open positions first, then collect signals from free tickers, rank by score, fill up to `max_positions`

Regime check: use `compute_regime_label_series(spy_df)` which returns a `pd.Series` indexed by SPY dates with values `"AGGRESSIVE" | "SELECTIVE" | "DEFENSIVE"`. Skip signal collection (but still advance open positions) when DEFENSIVE.

Scoring (mirrors BacktestEngine.run() lines 950–990):
- `_raw_score * weight` where weight = `breakout_weight` (VCP/RES_BREAKOUT/HTF/LCE), `base_weight` (BASE), or `pullback_weight` (PULLBACK)
- RES_BREAKOUT in SELECTIVE: multiply by `brk_regime_factor` (or `continue` if `brk_aggressive_only=True`)
- SELECTIVE setup weights from `constants.SELECTIVE_SETUP_WEIGHTS` (dict) + hard filter
- Score threshold: `final_score < params.score_threshold → continue`
- Config gate: `score < config.min_score → continue`

Gap gate for RES_BREAKOUT: skip if T+1 open > `zone_upper * (1 + params.brk_gap_pct)`.

Take-profit override: `entry_price + params.tp_multiple * (entry_price - stop_loss)` in scored mode.

`_SIGNAL_BASE_SCORES` and `_SIGNAL_BASE_SCORE_DEFAULT` are module-level dicts in `backtest_engine.py` — import them.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_portfolio_backtest.py`:

```python
def test_portfolio_cap_never_exceeded(monkeypatch):
    """
    With max_positions=2 and prepare() returning a TickerSimState that always
    fires a signal, never more than 2 positions are open at any time.
    """
    import asyncio
    import pandas as pd
    import numpy as np
    from portfolio_backtest import (
        BacktestConfig, TickerSimState, run_portfolio_backtest_universe
    )
    import backtest_engine as be

    # Build a minimal TickerSimState with synthetic price data
    dates = pd.date_range("2023-01-02", periods=50, freq="B")
    price = pd.Series(np.linspace(100, 110, 50), index=dates)
    vol   = pd.Series(np.ones(50) * 1_000_000, index=dates)
    df    = pd.DataFrame({
        "Open":      price,
        "High":      price * 1.01,
        "Low":       price * 0.99,
        "Close":     price,
        "Adj Close": price,
        "Volume":    vol,
    }, index=dates)
    spy_dates  = dates
    spy_price  = pd.Series(np.linspace(400, 410, 50), index=spy_dates)
    spy_df     = pd.DataFrame({"Close": spy_price, "Adj Close": spy_price}, index=spy_dates)
    flat_s     = pd.Series(np.zeros(50), index=dates)

    def _make_state(ticker):
        return TickerSimState(
            ticker=ticker, ticker_df=df.copy(), spy_df=spy_df,
            adj_col="Adj Close", ticker_dates=dates,
            ema20_full=price, atr14_full=flat_s,
            sr_zones_cache=[],
            rs_ratio_s=flat_s, rs_52wh_s=flat_s,
            rs_score_s=flat_s, spy_3m_s=flat_s,
            params=None,
        )

    # Monkeypatch prepare() to return our synthetic state
    tickers = [f"T{i}" for i in range(10)]

    async def fake_prepare(self, shared_spy_df=None):
        return _make_state(self.ticker)

    monkeypatch.setattr(be.BacktestEngine, "prepare", fake_prepare)

    # Monkeypatch _detect_signals_for_date to always return a PULLBACK signal
    import portfolio_backtest as pb

    def fake_detect(ts, T_date, full_idx, setup_types):
        if full_idx < 1:
            return None
        return {
            "setup_type": "PULLBACK",
            "stop_loss":  float(ts.ticker_df["Close"].iloc[full_idx]) * 0.95,
            "take_profit": float(ts.ticker_df["Close"].iloc[full_idx]) * 1.15,
            "_raw_score": 5.0,
        }

    monkeypatch.setattr(pb, "_detect_signals_for_date", fake_detect)

    config = BacktestConfig(
        start_date="2023-01-02", end_date="2023-03-31",
        max_positions=2, setup_types=["PULLBACK"],
    )
    # Monkeypatch compute_regime_label_series to always return AGGRESSIVE
    import filters
    from unittest.mock import MagicMock
    mock_series = pd.Series(
        ["AGGRESSIVE"] * 50,
        index=spy_dates,
    )
    monkeypatch.setattr(filters, "compute_regime_label_series",
                        lambda df: mock_series)

    trades = asyncio.run(run_portfolio_backtest_universe(tickers, config))

    # If cap works: at most 2 positions opened simultaneously.
    # Since each PULLBACK here has stop=price*0.95 and target=price*1.15,
    # they stay open until EOD. Total trades should be 2 (cap=2, no exits until EOD).
    assert len(trades) <= len(tickers)  # sanity: can't have more trades than tickers
    # Verify max concurrent: track open periods
    if trades:
        opens  = pd.to_datetime([t["entry_date"] for t in trades])
        exits  = pd.to_datetime([t["exit_date"]  for t in trades])
        for d in pd.date_range(config.start_date, config.end_date, freq="B"):
            concurrent = sum(1 for o, e in zip(opens, exits) if o <= d <= e)
            assert concurrent <= config.max_positions, \
                f"{d}: {concurrent} concurrent positions > cap {config.max_positions}"
```

- [ ] **Step 2: Run test to verify it fails**

```
cd swing-trading-dashboard/backend
python -m pytest tests/test_portfolio_backtest.py::test_portfolio_cap_never_exceeded -v
```
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement `run_portfolio_backtest_universe()`**

Replace the stub in `backend/portfolio_backtest.py`:

```python
async def run_portfolio_backtest_universe(
    tickers: List[str],
    config: BacktestConfig,
    params=None,
    progress_cb=None,
) -> List[dict]:
    """
    Portfolio-coordinated backtest over all tickers.

    Phase 1: Prepare all tickers concurrently (fetch + indicator compute).
    Phase 2: Single day-by-day replay with global position cap.

    Returns flat list of TradeRecord.to_dict() dicts.
    """
    from backtest_engine import (
        BacktestEngine, _manage_open_trade,
        _SIGNAL_BASE_SCORES, _SIGNAL_BASE_SCORE_DEFAULT,
        _fetch_data,
    )

    if not tickers:
        return []

    # ── Phase 1a: Fetch SPY once (shared across all tickers) ─────────────
    _, spy_df = await _fetch_data("SPY", config.start_date)
    if spy_df is None:
        logger.error("run_portfolio_backtest_universe: SPY fetch failed")
        return []

    # ── Phase 1b: Regime label series from SPY ────────────────────────────
    regime_label_s: pd.Series = (
        compute_regime_label_series(spy_df)
        if spy_df is not None and len(spy_df) > 0
        else pd.Series(dtype=object)
    )

    # ── Phase 1c: Prepare all tickers concurrently ────────────────────────
    sem          = asyncio.Semaphore(CONCURRENCY_LIMIT)
    ticker_states: List[TickerSimState] = []
    total        = len(tickers)
    done_count   = 0
    lock         = asyncio.Lock()

    async def _prepare_one(ticker: str) -> None:
        nonlocal done_count
        async with sem:
            try:
                engine = BacktestEngine(
                    ticker=ticker,
                    start_date=config.start_date,
                    end_date=config.end_date,
                    setup_types=config.setup_types,
                    params=params,
                )
                state = await engine.prepare(shared_spy_df=spy_df)
                if state is not None:
                    async with lock:
                        ticker_states.append(state)
            except Exception as exc:
                logger.warning("prepare failed for %s: %s", ticker, exc)
            finally:
                async with lock:
                    done_count += 1
                    if progress_cb is not None:
                        await progress_cb(done_count, total)

    await asyncio.gather(*[_prepare_one(t) for t in tickers])

    if not ticker_states:
        return []

    # ── Phase 2: Reset mutable state ──────────────────────────────────────
    for ts in ticker_states:
        ts.is_in_trade     = False
        ts.last_close_date = None

    # ── Phase 2: Build union trading calendar ─────────────────────────────
    start_ts = pd.Timestamp(config.start_date)
    end_ts   = pd.Timestamp(config.end_date)
    all_union = sorted(set().union(*[set(ts.ticker_dates) for ts in ticker_states]))
    replay_dates = [d for d in all_union if start_ts <= d <= end_ts]

    open_positions: List[dict]   = []
    completed_trades: List[dict] = []

    for T_date in replay_dates:

        # ── Step 1: Advance all open positions ────────────────────────────
        still_open = []
        for pos in open_positions:
            ts = pos["ticker_state"]
            if T_date not in ts.ticker_dates:
                still_open.append(pos)
                continue
            full_idx = ts.ticker_dates.get_loc(T_date)
            ema20_T  = float(ts.ema20_full.iloc[full_idx])
            atr14_T  = (float(ts.atr14_full.iloc[full_idx])
                        if ts.atr14_full is not None and not np.isnan(ts.atr14_full.iloc[full_idx])
                        else 0.0)
            bar = {
                "date":  T_date.strftime("%Y-%m-%d"),
                "open":  float(ts.ticker_df["Open"].iloc[full_idx]),
                "high":  float(ts.ticker_df["High"].iloc[full_idx]),
                "low":   float(ts.ticker_df["Low"].iloc[full_idx]),
                "close": float(ts.ticker_df[ts.adj_col].iloc[full_idx]),
                "ema20": ema20_T if not np.isnan(ema20_T) else 0.0,
                "atr14": atr14_T,
            }
            closed, exit_price, exit_reason = _manage_open_trade(pos["trade_state"], bar)
            if closed:
                completed_trades.append(
                    _build_trade_record(pos, T_date, exit_price, exit_reason)
                )
                ts.is_in_trade     = False
                ts.last_close_date = T_date.date()
            else:
                still_open.append(pos)
        open_positions = still_open

        # ── Step 2: Check available slots ─────────────────────────────────
        available = config.max_positions - len(open_positions)
        if available <= 0:
            continue

        # ── Step 3: Resolve regime ─────────────────────────────────────────
        spy_before = regime_label_s.index[regime_label_s.index <= T_date]
        current_regime = (
            str(regime_label_s.loc[spy_before[-1]])
            if len(spy_before) > 0
            else "UNKNOWN"
        )
        if current_regime == "DEFENSIVE":
            continue

        # ── Step 4: Collect signals from all free tickers ─────────────────
        candidates = []
        for ts in ticker_states:
            if ts.is_in_trade:
                continue
            if T_date not in ts.ticker_dates:
                continue
            full_idx = ts.ticker_dates.get_loc(T_date)
            if full_idx + 1 >= len(ts.ticker_dates):
                continue   # no T+1 bar available for entry

            # Cooldown gate
            if ts.last_close_date is not None and ts.params is not None:
                days_since = (T_date.date() - ts.last_close_date).days
                if days_since < ts.params.cooldown_days:
                    continue

            # Liquidity gate
            if not passes_liquidity(ts.ticker_df.iloc[:full_idx + 1]):
                continue

            # Signal detection
            signal = _detect_signals_for_date(ts, T_date, full_idx, config.setup_types)
            if signal is None:
                continue

            # ── Scored mode: apply weights, regime, threshold ─────────────
            if ts.params is not None:
                signal["_regime"] = current_regime
                setup_type_sig    = signal.get("setup_type", "")
                raw_score         = signal.get(
                    "_raw_score",
                    _SIGNAL_BASE_SCORES.get(setup_type_sig, _SIGNAL_BASE_SCORE_DEFAULT),
                )
                is_breakout = setup_type_sig in ("VCP", "RES_BREAKOUT", "HTF", "LCE")
                is_base     = setup_type_sig == "BASE"
                weight      = (
                    ts.params.breakout_weight if is_breakout
                    else ts.params.base_weight if is_base
                    else ts.params.pullback_weight
                )
                final_score = raw_score * weight

                # RES_BREAKOUT regime gate
                if setup_type_sig == "RES_BREAKOUT" and current_regime == "SELECTIVE":
                    if ts.params.brk_aggressive_only:
                        continue
                    final_score *= ts.params.brk_regime_factor

                # SELECTIVE setup weights
                if current_regime == "SELECTIVE" and SELECTIVE_SETUP_WEIGHTS:
                    sel_w = SELECTIVE_SETUP_WEIGHTS.get(setup_type_sig, 1.0)
                    if SELECTIVE_HARD_FILTER and sel_w == 0.0:
                        continue
                    final_score *= sel_w

                if final_score < ts.params.score_threshold:
                    continue

                signal["_final_score"] = final_score

                # Gap gate for RES_BREAKOUT
                if setup_type_sig == "RES_BREAKOUT":
                    zone_upper = signal.get("zone_upper", 0.0)
                    next_open  = float(ts.ticker_df["Open"].iloc[full_idx + 1])
                    if zone_upper > 0 and next_open > zone_upper * (1 + ts.params.brk_gap_pct):
                        continue

            else:
                signal["_regime"] = current_regime

            score = signal.get("_final_score") or 0.0
            if score < config.min_score:
                continue

            candidates.append((score, signal, ts, full_idx))

        # ── Step 5: Fill slots — best score first ──────────────────────────
        candidates.sort(key=lambda x: -x[0])
        for score, signal, ts, full_idx in candidates[:available]:
            next_idx    = full_idx + 1
            entry_date  = ts.ticker_dates[next_idx]
            entry_price = float(ts.ticker_df["Open"].iloc[next_idx])
            stop_loss   = signal.get("stop_loss", 0.0)

            # Take-profit override in scored mode
            if ts.params is not None:
                risk        = entry_price - stop_loss
                take_profit = round(entry_price + ts.params.tp_multiple * risk, 2) if risk > 0 else 0.0
            else:
                take_profit = signal.get("take_profit", 0.0)

            # Guard: valid entry
            if stop_loss <= 0 or stop_loss >= entry_price or take_profit <= entry_price:
                continue

            pos = _build_open_position(
                signal, ts, T_date, entry_date, entry_price, stop_loss, take_profit, full_idx
            )
            open_positions.append(pos)
            ts.is_in_trade = True

    # ── Step 6: Force-close any positions still open at end_date ──────────
    for pos in open_positions:
        ts = pos["ticker_state"]
        valid = ts.ticker_dates[ts.ticker_dates <= end_ts]
        if len(valid) == 0:
            continue
        last_date  = valid[-1]
        last_idx   = ts.ticker_dates.get_loc(last_date)
        exit_price = float(ts.ticker_df[ts.adj_col].iloc[last_idx])
        completed_trades.append(
            _build_trade_record(pos, last_date, exit_price, "EOD")
        )
        ts.is_in_trade = False

    logger.info(
        "run_portfolio_backtest_universe: %d trades from %d tickers",
        len(completed_trades), len(ticker_states),
    )
    return completed_trades
```

- [ ] **Step 4: Run tests**

```
cd swing-trading-dashboard/backend
python -m pytest tests/test_portfolio_backtest.py -v
```
Expected: all PASSED (including `test_portfolio_cap_never_exceeded`).

- [ ] **Step 5: Commit**

```bash
git add backend/portfolio_backtest.py
git commit -m "feat: implement run_portfolio_backtest_universe() with global position cap"
```

---

## Task 5: main.py endpoint update

**Files:**
- Modify: `backend/main.py`

### Context

Current endpoint at line ~3299: `run_backtest_diagnostics(background_tasks: BackgroundTasks)` — no request body.

Changes:
1. Add `BacktestRunRequest` Pydantic model (after existing `BacktestRequest` model near line ~1983)
2. Add `from portfolio_backtest import run_portfolio_backtest_universe, BacktestConfig` to imports
3. Update endpoint signature to `req: BacktestRunRequest = Body(default=BacktestRunRequest())`
4. Build `BacktestConfig` from `req`, call `run_portfolio_backtest_universe` instead of `run_backtest_universe`
5. Add `max_positions`, `min_score`, `setup_types` to the saved report dict
6. Fix "V4 backtest" label in progress message (line ~3353: `"Running V4 backtest"`)

`Body(default=BacktestRunRequest())` ensures callers that POST with no body (like the current frontend before the UI update) still get defaults. Import `Body` from `fastapi`.

- [ ] **Step 1: Add `BacktestRunRequest` model**

Find the existing `BacktestRequest` model (near line ~1983). Add `BacktestRunRequest` right after it:

```python
class BacktestRunRequest(BaseModel):
    start_date:    str           = Field(default_factory=lambda: BACKTEST_DIAG_START_DATE)
    end_date:      str           = Field(default_factory=lambda: BACKTEST_DIAG_END_DATE)
    max_positions: int           = 4
    ticker_count:  Optional[int] = None
    min_score:     float         = 0.0
    setup_types:   List[str]     = Field(default_factory=lambda: [
        "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"
    ])
```

Add to the import block at the top of `main.py`:
```python
from portfolio_backtest import run_portfolio_backtest_universe, BacktestConfig
```
And ensure `Body` is imported from `fastapi` (check existing fastapi imports and add `Body` if missing).

- [ ] **Step 2: Update the endpoint**

Replace the entire `run_backtest_diagnostics` function (lines ~3299–3374) with:

```python
@app.post("/api/diagnostics/backtest/run", status_code=202)
async def run_backtest_diagnostics(
    background_tasks: BackgroundTasks,
    req: BacktestRunRequest = Body(default=BacktestRunRequest()),
):
    """
    Trigger a background portfolio-coordinated backtest.
    Accepts optional JSON body (BacktestRunRequest). No body = defaults used.
    Returns 409 if a run is already in progress.
    """
    global _backtest_diag_status
    if _backtest_diag_status["status"] == "running":
        raise HTTPException(status_code=409, detail="Backtest already running")

    all_tickers = list(ACTIVE_UNIVERSE) if ACTIVE_UNIVERSE else list(SCAN_UNIVERSE)
    tickers     = all_tickers[:req.ticker_count] if req.ticker_count else all_tickers

    _backtest_diag_status.update({
        "status": "running",
        "done":   0,
        "total":  len(tickers),
    })

    config = BacktestConfig(
        start_date    = req.start_date,
        end_date      = req.end_date,
        max_positions = req.max_positions,
        ticker_count  = req.ticker_count,
        min_score     = req.min_score,
        setup_types   = req.setup_types,
    )

    async def _do_backtest():
        global _backtest_diag_status
        try:
            async def _progress(done: int, total: int):
                _backtest_diag_status["done"] = done

            raw_trades = await run_portfolio_backtest_universe(
                tickers,
                config,
                params=BacktestParams(),
                progress_cb=_progress,
            )
            adapted = [_backtest_trade_to_analytics(t) for t in raw_trades]

            report = {
                "generated_at":        datetime.now(timezone.utc).isoformat(),
                "start_date":          req.start_date,
                "end_date":            req.end_date,
                "max_positions":       req.max_positions,
                "tickers_run":         len(tickers),
                "setup_types":         req.setup_types,
                "min_score":           req.min_score,
                "total_trades":        len(adapted),
                "summary":             compute_live_diagnostics(adapted),
                "setup_breakdown":     compute_setup_breakdown(adapted),
                "ticker_distribution": compute_ticker_distribution(adapted),
                "regime_performance":  compute_regime_performance(adapted),
                "selective_analysis":  compute_selective_breakdown(adapted),
                "trades":              raw_trades,
            }

            os.makedirs(os.path.dirname(BACKTEST_DIAG_CACHE_PATH), exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(BACKTEST_DIAG_CACHE_PATH))
            try:
                with os.fdopen(tmp_fd, "w") as f:
                    json.dump(report, f, cls=_NumpyEncoder)
                os.replace(tmp_path, BACKTEST_DIAG_CACHE_PATH)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            now_iso = datetime.now(timezone.utc).isoformat()
            _backtest_diag_status.update({"status": "completed", "last_run": now_iso})
            log.info("Portfolio backtest complete: %d trades from %d tickers",
                     len(adapted), len(tickers))
        except Exception as exc:
            _backtest_diag_status["status"] = "failed"
            log.error("Portfolio backtest failed: %s", exc)

    background_tasks.add_task(_do_backtest)
    return {"status": "started", "tickers": len(tickers)}
```

- [ ] **Step 3: Verify the import of `run_portfolio_backtest_universe` doesn't break startup**

```
cd swing-trading-dashboard/backend
python -c "import main; print('OK')"
```
Expected: `OK` (no import errors).

- [ ] **Step 4: Verify backward-compat POST with no body**

```
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_diag_endpoint.py -v
```
Expected: existing tests still PASS. If any test POSTs without a body, it should still get 202.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat: backtest endpoint accepts config body, uses portfolio coordinator"
```

---

## Task 6: DiagnosticsTab.jsx — Config UI + Label Fix

**Files:**
- Modify: `frontend/src/components/DiagnosticsTab.jsx`

### Context

The component has:
- Line ~342: `{src === 'live' ? 'Live Trades' : 'Backtest (V4 baseline)'}` — fix label
- Line ~287: `handleRunBacktest()` — POSTs to `/api/diagnostics/backtest/run` with no body
- Line ~349–379: Empty state with "Run V4 Backtest" button — update text and add config panel above it
- Line ~321: Subtitle text `'V4 strategy — scored mode, default params (2023–2024).'` — update

Config panel appears above the "Run" button in the empty state, and is also available when data is loaded (persistent config section).

The `btConfig` state holds the user's config. Year dropdowns and setup type checkboxes are in the empty-state section. The sub-header under loaded results shows what config was used (from `backtestData`).

- [ ] **Step 1: Add `btConfig` state**

In the `DiagnosticsTab` component's `useState` declarations, add:

```jsx
const [btConfig, setBtConfig] = useState({
  startYear:    2017,
  endYear:      2024,   // matches backend BACKTEST_DIAG_END_DATE default "2024-12-31"
  maxPositions: 4,
  tickerCount:  null,
  minScore:     0,
  setupTypes:   ['PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE'],
})
```

- [ ] **Step 2: Update `handleRunBacktest` to send config**

Replace:
```js
await fetch('/api/diagnostics/backtest/run', { method: 'POST' })
```
With:
```js
await fetch('/api/diagnostics/backtest/run', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    start_date:    `${btConfig.startYear}-01-01`,
    end_date:      `${btConfig.endYear}-12-31`,
    max_positions: btConfig.maxPositions,
    ticker_count:  btConfig.tickerCount,
    min_score:     btConfig.minScore,
    setup_types:   btConfig.setupTypes,
  }),
})
```

- [ ] **Step 3: Fix the "V4 baseline" label**

Line ~342 — change:
```jsx
{src === 'live' ? 'Live Trades' : 'Backtest (V4 baseline)'}
```
To:
```jsx
{src === 'live' ? 'Live Trades' : 'Full System Backtest'}
```

- [ ] **Step 4: Fix the subtitle and result sub-header**

Line ~321–323 — change the subtitle:
```jsx
{source === 'backtest'
  ? 'Portfolio-coordinated simulation — best params, global position cap.'
  : 'Live trading performance from closed portfolio trades.'}
```

After the subtitle div, add a config-used sub-header (only shown when backtest data is loaded):
```jsx
{source === 'backtest' && data && (
  <div style={{ fontSize: 10, color: 'var(--muted)', fontFamily: '"IBM Plex Mono", monospace', marginBottom: 8 }}>
    {data.start_date} → {data.end_date}
    {' · '}{data.tickers_run} tickers
    {' · '}max {data.max_positions ?? '—'} positions
    {' · '}{Array.isArray(data.setup_types) ? data.setup_types.join(', ') : '—'}
  </div>
)}
```

- [ ] **Step 5: Fix the progress text**

Line ~354 — change:
```jsx
Running V4 backtest — {backtestStatus.done} / {backtestStatus.total} tickers…
```
To:
```jsx
Running backtest — {backtestStatus.done} / {backtestStatus.total} tickers…
```

- [ ] **Step 6: Add config panel above the "Run" button**

In the empty-state block (around line ~364), before the `<button onClick={handleRunBacktest}>` element, add:

```jsx
{/* Config panel */}
<div style={{
  display: 'flex', flexDirection: 'column', gap: 10,
  marginBottom: 16, maxWidth: 520, margin: '0 auto 16px',
}}>
  {/* Date range + positions + universe */}
  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'center' }}>
    <select
      value={btConfig.startYear}
      onChange={e => setBtConfig(c => ({ ...c, startYear: +e.target.value }))}
      style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 8px', fontSize: 11, fontFamily: '"IBM Plex Mono", monospace' }}
    >
      {[2015,2016,2017,2018,2019,2020,2021,2022].map(y => <option key={y} value={y}>{y}</option>)}
    </select>
    <span style={{ color: 'var(--muted)', fontSize: 11 }}>→</span>
    <select
      value={btConfig.endYear}
      onChange={e => setBtConfig(c => ({ ...c, endYear: +e.target.value }))}
      style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 8px', fontSize: 11, fontFamily: '"IBM Plex Mono", monospace' }}
    >
      {[2021,2022,2023,2024,2025].map(y => <option key={y} value={y}>{y}</option>)}
    </select>
    <span style={{ color: 'var(--muted)', fontSize: 10 }}>·</span>
    <label style={{ fontSize: 10, color: 'var(--muted)' }}>Positions</label>
    <input
      type="number" min={1} max={20} value={btConfig.maxPositions}
      onChange={e => setBtConfig(c => ({ ...c, maxPositions: +e.target.value }))}
      style={{ width: 44, background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 6px', fontSize: 11, fontFamily: '"IBM Plex Mono", monospace', textAlign: 'center' }}
    />
    <span style={{ color: 'var(--muted)', fontSize: 10 }}>·</span>
    <label style={{ fontSize: 10, color: 'var(--muted)' }}>Min Score</label>
    <input
      type="number" min={0} max={20} step={0.5} value={btConfig.minScore}
      onChange={e => setBtConfig(c => ({ ...c, minScore: +e.target.value }))}
      style={{ width: 44, background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 6px', fontSize: 11, fontFamily: '"IBM Plex Mono", monospace', textAlign: 'center' }}
    />
    <span style={{ color: 'var(--muted)', fontSize: 10 }}>·</span>
    <select
      value={btConfig.tickerCount ?? ''}
      onChange={e => setBtConfig(c => ({ ...c, tickerCount: e.target.value === '' ? null : +e.target.value }))}
      style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 8px', fontSize: 11, fontFamily: '"IBM Plex Mono", monospace' }}
    >
      <option value="">Full (~700)</option>
      <option value="200">Top 200</option>
      <option value="100">Top 100</option>
      <option value="50">Top 50</option>
    </select>
  </div>

  {/* Setup type checkboxes */}
  <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
    {['PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE'].map(st => (
      <label key={st} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: 'var(--muted)', cursor: 'pointer', fontFamily: '"IBM Plex Mono", monospace' }}>
        <input
          type="checkbox"
          checked={btConfig.setupTypes.includes(st)}
          onChange={e => {
            if (e.target.checked) {
              setBtConfig(c => ({ ...c, setupTypes: [...c.setupTypes, st] }))
            } else {
              setBtConfig(c => ({ ...c, setupTypes: c.setupTypes.filter(s => s !== st) }))
            }
          }}
          style={{ accentColor: 'var(--accent)' }}
        />
        {st}
      </label>
    ))}
  </div>
</div>
```

Also update the "Run V4 Backtest" button text and "No V4 backtest data" text to remove "V4":

```jsx
// Before:
'No V4 backtest data. Run the baseline to generate a strategy audit.'
// After:
'No backtest data. Configure and run to generate a strategy audit.'

// Before (button text):
Run V4 Backtest
// After:
RUN FULL SYSTEM BACKTEST
```

- [ ] **Step 7: Verify the build**

```
cd swing-trading-dashboard/frontend
npm run build 2>&1 | tail -20
```
Expected: build succeeds with no errors. Warnings about unused variables are OK.

- [ ] **Step 8: Manual testing checklist**

Open http://localhost:5173, navigate to Diagnostics, select "Full System Backtest" tab:
- [ ] Tab label shows "Full System Backtest" (not "V4 baseline")
- [ ] Config panel visible: year dropdowns, positions input, universe dropdown, setup checkboxes
- [ ] Changing startYear to 2020 and clicking Run sends `start_date: "2020-01-01"` in the POST body (verify in browser Network tab)
- [ ] After run completes, sub-header shows the config used (dates, tickers, max positions)
- [ ] Unchecking RES_BREAKOUT sends `setup_types` array without it

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/DiagnosticsTab.jsx
git commit -m "feat: add backtest config panel, fix labels (V4 baseline → Full System Backtest)"
```

---

## Testing Summary

```
# All backend tests
cd swing-trading-dashboard/backend
python -m pytest tests/test_portfolio_backtest.py tests/test_backtest_engine.py tests/test_backtest_scored_mode.py tests/test_backtest_preloaded_df.py tests/test_run_backtest_universe.py tests/test_backtest_diag_endpoint.py -v

# Frontend build
cd swing-trading-dashboard/frontend
npm run build
```

Expected outcomes:
- `test_portfolio_backtest.py`: 5 tests pass (config defaults, state reset, empty list, engine has prepare, portfolio cap)
- All pre-existing backtest tests: same pass count as before (no regression)
- Frontend: clean build

---

## Deployment

After all tasks pass:

```bash
git push origin main
# On VPS (89.167.25.25):
# cd /path/to/swing-trading-dashboard && git pull && sudo systemctl restart dashboard
```
