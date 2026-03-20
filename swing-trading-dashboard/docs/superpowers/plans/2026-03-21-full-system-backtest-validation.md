# Full System Backtest Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a full 2020–2024 backtest across all setups and regimes, emit a structured validation report with regime breakdown, setup-type breakdown, ATR entry quality filtering, and capital curve vs SPY.

**Architecture:** Single standalone script (`scripts/backtest_full_validation.py`) using the existing `BacktestEngine` in legacy mode (`params=None`) — identical to the live scanner parameters. `backtest_engine.py` gets one small addition: `atr` and `entry` captured in `_meta_keys` so the script can classify entry quality per trade. All output is printed to stdout (no DB writes, no cache files written).

**Tech Stack:** Python 3.10+, asyncio, pandas, numpy. Parquet cache at `backend/data/price_cache/`. Reuses patterns from `scripts/backtest_selective_brk.py`.

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `backend/backtest_engine.py` | Modify (1 line) | Add `"atr"` and `"entry"` to `_meta_keys` so trade dicts carry ATR and signal-day entry for quality classification |
| `scripts/backtest_full_validation.py` | Create | Full validation runner: load parquet cache → backtest → classify entry quality → segment by regime+setup → capital curve vs SPY → print structured report |
| `backend/tests/test_full_validation_helpers.py` | Create | Unit tests for helper functions (entry quality, stats, capital curve) — no network calls |

---

## Task 1: Capture `atr` and `entry` in BacktestEngine `_meta_keys`

**Files:**
- Modify: `backend/backtest_engine.py` line ~982
- Test: `backend/tests/test_full_validation_helpers.py`

### Context for the implementer

`_meta_keys` in `backtest_engine.py` (around line 980–983) controls which fields from the signal dict get saved into `trade["setup_meta"]`. We need `atr` (ATR14 at signal time, already emitted by all engines) and `entry` (signal-day close = the "ideal" entry price) so the validation script can compute entry quality:

```python
entry_atr_dist = (trade["entry_price"] - trade["setup_meta"]["entry"]) / trade["setup_meta"]["atr"]
quality = "EARLY" if entry_atr_dist < 0.1 else "OPTIMAL" if entry_atr_dist < 0.5 else "EXTENDED"
```

`trade["entry_price"]` is the T+1 open (actual fill). `setup_meta["entry"]` is the signal-day close (intended entry). The gap between them, normalized by ATR, tells us whether we chased.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_full_validation_helpers.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_setup_meta_captures_atr_and_entry():
    """_meta_keys must include 'atr' and 'entry' so trade dicts carry them."""
    import inspect
    from backtest_engine import BacktestEngine
    src = inspect.getsource(BacktestEngine.run)
    assert '"atr"' in src or "'atr'" in src, \
        "'atr' not found in BacktestEngine.run — add it to _meta_keys"
    assert '"entry"' in src or "'entry'" in src, \
        "'entry' not found in BacktestEngine.run — add it to _meta_keys"
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd backend
pytest tests/test_full_validation_helpers.py::test_setup_meta_captures_atr_and_entry -v
```

Expected: FAIL with assertion error about `'atr'` or `'entry'` not found.

- [ ] **Step 3: Add `"atr"` and `"entry"` to `_meta_keys` in `backtest_engine.py`**

Find this line (around line 980):
```python
_meta_keys = ("volume_ratio", "breakout_pct", "resistance_level",
              "zone_upper", "support_source", "zone_source",
              "pullback_score", "days_since_breakout")
```

Change to:
```python
_meta_keys = ("volume_ratio", "breakout_pct", "resistance_level",
              "zone_upper", "support_source", "zone_source",
              "pullback_score", "days_since_breakout",
              "atr", "entry")   # entry = signal-day close; atr = ATR14 at signal
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
cd backend
pytest tests/test_full_validation_helpers.py::test_setup_meta_captures_atr_and_entry -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_full_validation_helpers.py
git commit -m "feat(backtest): capture atr+entry in setup_meta for entry quality classification"
```

---

## Task 2: Entry quality helpers + stats helper (with tests)

**Files:**
- Test + implement: `backend/tests/test_full_validation_helpers.py` (expand)
- These helpers will be defined inline in `scripts/backtest_full_validation.py` — we test the logic here first.

### Context for the implementer

Three pure functions needed by the validation script:

1. `_entry_quality(trade)` — returns `"EARLY"`, `"OPTIMAL"`, `"EXTENDED"`, or `"UNKNOWN"`
2. `_stats(trades)` — same pattern as `backtest_selective_brk.py` but adds `max_dd` and `avg_hold`
3. `_capital_curve(trades, start_year=2020, end_year=2024)` — returns `{year: equity}` dict using `portfolio_pnl_pct`, where equity starts at 1.0

- [ ] **Step 1: Write failing tests for all three helpers**

Add to `backend/tests/test_full_validation_helpers.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from constants import ATR_ENTRY_EARLY_THRESHOLD, ATR_ENTRY_EXTENDED_THRESHOLD


# ── _entry_quality ────────────────────────────────────────────────────────────

def _entry_quality(trade: dict) -> str:
    """Classify entry quality based on ATR-normalized gap between T+1 open and signal close."""
    meta = trade.get("setup_meta", {})
    atr  = meta.get("atr", 0)
    sig_entry = meta.get("entry", None)
    fill_price = trade.get("entry_price")
    if atr is None or atr <= 0 or sig_entry is None or fill_price is None:
        return "UNKNOWN"
    dist = (fill_price - sig_entry) / atr
    if dist < ATR_ENTRY_EARLY_THRESHOLD:
        return "EARLY"
    elif dist < ATR_ENTRY_EXTENDED_THRESHOLD:
        return "OPTIMAL"
    else:
        return "EXTENDED"


def test_entry_quality_early():
    t = {"entry_price": 100.05, "setup_meta": {"atr": 1.0, "entry": 100.0}}
    assert _entry_quality(t) == "EARLY"   # 0.05 ATR < 0.1


def test_entry_quality_optimal():
    t = {"entry_price": 100.3, "setup_meta": {"atr": 1.0, "entry": 100.0}}
    assert _entry_quality(t) == "OPTIMAL"  # 0.3 ATR in [0.1, 0.5)


def test_entry_quality_extended():
    t = {"entry_price": 101.0, "setup_meta": {"atr": 1.0, "entry": 100.0}}
    assert _entry_quality(t) == "EXTENDED"  # 1.0 ATR >= 0.5


def test_entry_quality_unknown_no_atr():
    t = {"entry_price": 100.0, "setup_meta": {"entry": 100.0}}
    assert _entry_quality(t) == "UNKNOWN"


# ── _stats ────────────────────────────────────────────────────────────────────

def _stats(trades: list) -> dict:
    if not trades:
        return {"n": 0, "win_rate": 0.0, "avg_r": 0.0, "expectancy": 0.0,
                "profit_factor": 0.0, "max_dd": 0.0, "avg_hold": 0.0}
    sorted_t = sorted(trades, key=lambda t: t.get("exit_date", t.get("entry_date", "")))
    rr      = [t["rr_achieved"] for t in sorted_t]
    wins    = [r for r in rr if r > 0]
    losses  = [r for r in rr if r <= 0]
    hold    = [t.get("holding_days", 0) for t in sorted_t]
    pnl     = [t.get("portfolio_pnl_pct", 0.0) for t in sorted_t]

    win_rate      = len(wins) / len(rr) * 100
    avg_r         = float(np.mean(rr))
    avg_win       = float(np.mean(wins))   if wins   else 0.0
    avg_loss      = float(np.mean(losses)) if losses else 0.0
    expectancy    = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss
    gross_profit  = sum(p for p in pnl if p > 0)
    gross_loss    = abs(sum(p for p in pnl if p < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    # Peak-to-trough on cumulative portfolio_pnl_pct
    eq, peak, max_dd = 1.0, 1.0, 0.0
    for p in pnl:
        eq *= (1 + p / 100)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    return {
        "n":            len(trades),
        "win_rate":     win_rate,
        "avg_r":        avg_r,
        "expectancy":   expectancy,
        "profit_factor": profit_factor,
        "max_dd":       max_dd,
        "avg_hold":     float(np.mean(hold)),
    }


def test_stats_empty():
    s = _stats([])
    assert s["n"] == 0
    assert s["win_rate"] == 0.0


def test_stats_two_trades():
    trades = [
        {"rr_achieved": 2.0, "portfolio_pnl_pct": 0.4, "holding_days": 10, "is_win": True},
        {"rr_achieved": -1.0, "portfolio_pnl_pct": -0.2, "holding_days": 5, "is_win": False},
    ]
    s = _stats(trades)
    assert s["n"] == 2
    assert abs(s["win_rate"] - 50.0) < 0.01
    assert abs(s["avg_r"] - 0.5) < 0.001
    assert s["max_dd"] > 0   # drawdown occurred


# ── _capital_curve ────────────────────────────────────────────────────────────

def _capital_curve(trades: list, start_year: int = 2020, end_year: int = 2024) -> dict:
    """
    Returns year-end equity for each year from start_year to end_year.
    Trades sorted by exit_date (P&L is realized at exit, not entry).
    Equity starts at 1.0.
    Result dict: {2020: 1.03, 2021: 1.12, ...}
    """
    if not trades:
        return {y: 1.0 for y in range(start_year, end_year + 1)}

    sorted_trades = sorted(trades, key=lambda t: t.get("exit_date", t.get("entry_date", "")))

    equity = 1.0
    year_equity = {}
    trade_idx   = 0
    n           = len(sorted_trades)

    for year in range(start_year, end_year + 1):
        cutoff = f"{year}-12-31"
        while trade_idx < n and sorted_trades[trade_idx].get("entry_date", "") <= cutoff:
            p = sorted_trades[trade_idx].get("portfolio_pnl_pct", 0.0)
            equity *= (1 + p / 100)
            trade_idx += 1
        year_equity[year] = round(equity, 4)

    return year_equity


def test_capital_curve_grows():
    trades = [
        {"entry_date": "2020-06-01", "portfolio_pnl_pct": 0.5},
        {"entry_date": "2021-03-01", "portfolio_pnl_pct": 0.5},
    ]
    curve = _capital_curve(trades)
    assert curve[2020] > 1.0
    assert curve[2021] > curve[2020]


def test_capital_curve_empty():
    curve = _capital_curve([])
    assert all(v == 1.0 for v in curve.values())
```

- [ ] **Step 2: Run to confirm tests pass (these are self-contained — no imports needed)**

```bash
cd backend
pytest tests/test_full_validation_helpers.py -v
```

Expected: All tests PASS (the helper functions are defined inside the test file itself — they test the logic before we copy it to the script).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_full_validation_helpers.py
git commit -m "test(validation): helper tests for entry quality, stats, capital curve"
```

---

## Task 3: Write `scripts/backtest_full_validation.py`

**Files:**
- Create: `scripts/backtest_full_validation.py`

### Context for the implementer

This script:
1. Loads all parquet files from `backend/data/price_cache/`
2. Runs `BacktestEngine` in **legacy mode** (`params=None`) over all tickers, 2020-2024
3. Classifies each trade's entry quality (EARLY/OPTIMAL/EXTENDED) using `setup_meta["atr"]` and `setup_meta["entry"]`
4. By default, **excludes EXTENDED entries** (pass `--show-extended` to include them)
5. Segments trades by regime (AGGRESSIVE / SELECTIVE / DEFENSIVE) and setup type
6. Computes capital curve vs SPY buy-and-hold
7. Prints structured report to stdout

The SPY capital curve is computed differently from the system curve:
- Load SPY parquet → filter to 2020-01-02 to 2024-12-31 → compute daily returns → compound from 1.0 → record year-end values

**Command-line usage:**
```bash
cd backend
python ../scripts/backtest_full_validation.py             # EARLY+OPTIMAL only
python ../scripts/backtest_full_validation.py --show-extended  # all entries
```

**Output sections:**
1. Header + run config
2. Combined summary table (all regimes, EARLY+OPTIMAL only vs all)
3. Per-regime breakdown table (regime × setup type)
4. Capital curve simulation (year-end equity, CAGR, max drawdown)
5. Key insights (profit concentration, loss concentration, SELECTIVE contribution)

- [ ] **Step 1: Create the script**

Create `scripts/backtest_full_validation.py`:

```python
"""
backtest_full_validation.py — Full System Validation (2020-2024)
================================================================
Runs the complete strategy across all market regimes and setup types.
Outputs regime segmentation, setup breakdown, entry quality analysis,
and capital curve vs SPY.

Usage:
    cd backend
    python ../scripts/backtest_full_validation.py               # default: exclude EXTENDED
    python ../scripts/backtest_full_validation.py --show-extended

Requirements:
    - Parquet cache at backend/data/price_cache/
    - SPY.parquet must be present in the cache
    - Run from backend/ directory (or cache path will fail)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import numpy as np
import pandas as pd

# ── Path setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..", "backend")
sys.path.insert(0, BACKEND_DIR)

sys.stdout.reconfigure(encoding="utf-8")

from backtest_engine import BacktestEngine
from indicators import ema as _ema, sma as _sma, atr as _atr, cci as _cci
from constants import CONCURRENCY_LIMIT, ATR_ENTRY_EARLY_THRESHOLD, ATR_ENTRY_EXTENDED_THRESHOLD

# ── Config ────────────────────────────────────────────────────────────────────
START_DATE  = "2020-01-01"
END_DATE    = "2024-12-31"
CACHE_DIR   = os.path.join(BACKEND_DIR, "data", "price_cache")
ALL_REGIMES = ("AGGRESSIVE", "SELECTIVE", "DEFENSIVE", "UNKNOWN")
SETUP_ORDER = ("VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE")


# ── Entry quality classification ──────────────────────────────────────────────

def _entry_quality(trade: dict) -> str:
    meta      = trade.get("setup_meta", {})
    atr       = meta.get("atr", 0)
    sig_entry = meta.get("entry", None)
    fill      = trade.get("entry_price")
    if not atr or atr <= 0 or sig_entry is None or fill is None:
        return "UNKNOWN"
    dist = (fill - sig_entry) / atr
    if dist < ATR_ENTRY_EARLY_THRESHOLD:
        return "EARLY"
    elif dist < ATR_ENTRY_EXTENDED_THRESHOLD:
        return "OPTIMAL"
    else:
        return "EXTENDED"


# ── Stats ─────────────────────────────────────────────────────────────────────

def _stats(trades: list) -> dict:
    if not trades:
        return {"n": 0, "win_rate": 0.0, "avg_r": 0.0, "expectancy": 0.0,
                "profit_factor": 0.0, "max_dd": 0.0, "avg_hold": 0.0}

    # Sort by exit_date for deterministic drawdown calculation
    sorted_t = sorted(trades, key=lambda t: t.get("exit_date", t.get("entry_date", "")))

    rr   = [t["rr_achieved"] for t in sorted_t]
    wins = [r for r in rr if r > 0]
    loss = [r for r in rr if r <= 0]
    pnl  = [t.get("portfolio_pnl_pct", 0.0) for t in sorted_t]
    hold = [t.get("holding_days", 0) for t in sorted_t]

    win_rate   = len(wins) / len(rr) * 100
    avg_r      = float(np.mean(rr))
    avg_win    = float(np.mean(wins)) if wins else 0.0
    avg_loss   = float(np.mean(loss)) if loss else 0.0
    expectancy = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss

    gp = sum(p for p in pnl if p > 0)
    gl = abs(sum(p for p in pnl if p < 0))
    pf = (gp / gl) if gl > 0 else float("inf")

    eq, peak, max_dd = 1.0, 1.0, 0.0
    for p in pnl:
        eq *= (1 + p / 100)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    return {
        "n":             len(trades),
        "win_rate":      win_rate,
        "avg_r":         avg_r,
        "expectancy":    expectancy,
        "profit_factor": pf,
        "max_dd":        max_dd,
        "avg_hold":      float(np.mean(hold)),
    }


# ── Capital curve ─────────────────────────────────────────────────────────────

def _capital_curve(trades: list, start_year: int = 2020, end_year: int = 2024) -> dict:
    """Year-end equity starting at 1.0, using portfolio_pnl_pct.
    Sorted by exit_date — P&L is realized at exit, not entry."""
    if not trades:
        return {y: 1.0 for y in range(start_year, end_year + 1)}
    sorted_trades = sorted(trades, key=lambda t: t.get("exit_date", t.get("entry_date", "")))
    equity, idx, n = 1.0, 0, len(sorted_trades)
    result = {}
    for year in range(start_year, end_year + 1):
        cutoff = f"{year}-12-31"
        while idx < n and sorted_trades[idx].get("exit_date", sorted_trades[idx].get("entry_date", "")) <= cutoff:
            equity *= (1 + sorted_trades[idx].get("portfolio_pnl_pct", 0.0) / 100)
            idx += 1
        result[year] = round(equity, 4)
    return result


def _spy_curve(spy_df: pd.DataFrame, start_year: int = 2020, end_year: int = 2024) -> dict:
    """Year-end SPY buy-and-hold equity starting at 1.0."""
    adj = "Adj Close" if "Adj Close" in spy_df.columns else "Close"
    spy = spy_df[adj].copy()
    spy = spy[(spy.index >= f"{start_year}-01-01") & (spy.index <= f"{end_year}-12-31")]
    if spy.empty:
        return {y: 1.0 for y in range(start_year, end_year + 1)}
    base = float(spy.iloc[0])
    result = {}
    for year in range(start_year, end_year + 1):
        end_slice = spy[spy.index <= f"{year}-12-31"]
        if end_slice.empty:
            result[year] = result.get(year - 1, 1.0)
        else:
            result[year] = round(float(end_slice.iloc[-1]) / base, 4)
    return result


def _cagr(start_equity: float, end_equity: float, years: int) -> float:
    if start_equity <= 0 or years <= 0:
        return 0.0
    return round((end_equity / start_equity) ** (1 / years) - 1, 4) * 100


# ── Printing helpers ──────────────────────────────────────────────────────────

def _hr(width: int = 78) -> None:
    print("─" * width)


def _double_hr(width: int = 78) -> None:
    print("═" * width)


def _print_summary_table(label: str, sections: dict) -> None:
    """Print a multi-column comparison table for a dict of {label: stats_dict}."""
    keys = list(sections.keys())
    col_w = 22
    metrics = [
        ("Trade count",    "n",             "{:.0f}"),
        ("Win rate",       "win_rate",      "{:.1f}%"),
        ("Avg R",          "avg_r",         "{:.3f}R"),
        ("Expectancy",     "expectancy",    "{:.3f}R"),
        ("Profit factor",  "profit_factor", "{:.2f}"),
        ("Max drawdown",   "max_dd",        "{:.1f}%"),
        ("Avg hold days",  "avg_hold",      "{:.1f}d"),
    ]
    width = 20 + col_w * len(keys)
    print(f"\n{label}")
    print("─" * width)
    header = f"{'Metric':<20}" + "".join(f"{k:<{col_w}}" for k in keys)
    print(header)
    print("─" * width)
    for name, key, fmt in metrics:
        row = f"{name:<20}"
        for k in keys:
            val = sections[k].get(key, 0)
            row += f"{('inf' if val == float('inf') else fmt.format(val)):<{col_w}}"
        print(row)
    print("─" * width)


def _print_regime_breakdown(regime: str, trades: list, show_extended: bool) -> None:
    """Print per-setup stats within a regime."""
    if not show_extended:
        trades = [t for t in trades if _entry_quality(t) != "EXTENDED"]

    if not trades:
        print(f"  (no trades in {regime} after filtering)")
        return

    col_w = 8
    headers = ["Setup", "N", "Win%", "AvgR", "Exp", "PF", "MaxDD%", "Hold"]
    widths  = [12, 6, 7, 8, 8, 7, 8, 7]
    header_row = "".join(f"{h:<{w}}" for h, w in zip(headers, widths))
    sep = "─" * sum(widths)
    print(f"\n  {header_row}")
    print(f"  {sep}")

    all_setups = list(SETUP_ORDER) + [
        s for s in {t["setup_type"] for t in trades} if s not in SETUP_ORDER
    ]

    for stype in all_setups:
        subset = [t for t in trades if t["setup_type"] == stype]
        if not subset:
            continue
        s = _stats(subset)
        pf_str = "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
        row = (
            f"{stype:<12}"
            f"{s['n']:<6}"
            f"{s['win_rate']:.1f}%  "
            f"{s['avg_r']:+.3f}   "
            f"{s['expectancy']:+.3f}   "
            f"{pf_str:<7}"
            f"{s['max_dd']:.1f}%    "
            f"{s['avg_hold']:.1f}d"
        )
        print(f"  {row}")

    # Total row
    tot = _stats(trades)
    pf_str = "inf" if tot["profit_factor"] == float("inf") else f"{tot['profit_factor']:.2f}"
    print(f"  {sep}")
    total_row = (
        f"{'TOTAL':<12}"
        f"{tot['n']:<6}"
        f"{tot['win_rate']:.1f}%  "
        f"{tot['avg_r']:+.3f}   "
        f"{tot['expectancy']:+.3f}   "
        f"{pf_str:<7}"
        f"{tot['max_dd']:.1f}%    "
        f"{tot['avg_hold']:.1f}d"
    )
    print(f"  {total_row}")


# ── Parquet loader (reuse pattern from backtest_selective_brk.py) ─────────────

def _load_all_cached(cache_dir: str):
    from pathlib import Path
    loaded_dfs: dict = {}
    spy_df = None
    parquet_files = sorted(Path(cache_dir).glob("*.parquet"))
    print(f"Found {len(parquet_files)} parquet files in {cache_dir}")
    for fpath in parquet_files:
        ticker = fpath.stem.upper()
        try:
            df = pd.read_parquet(fpath)
        except Exception as exc:
            print(f"  WARN: {fpath.name}: {exc}")
            continue
        if ticker == "SPY":
            spy_df = df
        loaded_dfs[ticker] = df

    if spy_df is None:
        raise RuntimeError(f"SPY.parquet not found in {cache_dir}.")

    print(f"Loaded {len(loaded_dfs)} tickers (including SPY)")

    for ticker, df in loaded_dfs.items():
        if ticker == "SPY" or "_EMA8" in df.columns:
            continue
        _adj = "Adj Close" if "Adj Close" in df.columns else "Close"
        _c, _h, _l = df[_adj], df["High"], df["Low"]
        df["_EMA8"]    = _ema(_c, 8)
        df["_EMA20"]   = _ema(_c, 20)
        df["_SMA50"]   = _sma(_c, 50)
        df["_SMA200"]  = _sma(_c, 200)
        df["_ATR14"]   = _atr(_h, _l, _c, 14)
        df["_CCI20"]   = _cci(_h, _l, _c, 20)
        if "Volume" in df.columns:
            df["_VOLSMA50"] = df["Volume"].rolling(50, min_periods=10).mean()

    return loaded_dfs, spy_df


# ── Backtest runner ───────────────────────────────────────────────────────────

async def _run_all(loaded_dfs: dict, spy_df) -> list:
    sem        = asyncio.Semaphore(CONCURRENCY_LIMIT)
    all_trades = []
    lock       = asyncio.Lock()
    done       = [0]
    total      = len(loaded_dfs) - 1   # exclude SPY

    async def _run_one(ticker: str, ticker_df) -> list:
        async with sem:
            try:
                engine = BacktestEngine(
                    ticker=ticker,
                    start_date=START_DATE,
                    end_date=END_DATE,
                    params=None,       # LEGACY MODE — same as live scanner
                    ticker_df=ticker_df,
                    spy_df=spy_df,
                )
                summary = await engine.run()
                return [t.to_dict() for t in summary.trades]
            except Exception as exc:
                print(f"  WARN {ticker}: {exc}")
                return []
            finally:
                async with lock:
                    done[0] += 1
                    if done[0] % 100 == 0 or done[0] == total:
                        print(f"  Progress: {done[0]}/{total} tickers", flush=True)

    results = await asyncio.gather(*[
        _run_one(ticker, df)
        for ticker, df in loaded_dfs.items()
        if ticker != "SPY"
    ])
    for batch in results:
        all_trades.extend(batch)
    return all_trades


# ── Report ────────────────────────────────────────────────────────────────────

def _print_report(all_trades: list, spy_df, show_extended: bool) -> None:
    n_years = int(END_DATE[:4]) - int(START_DATE[:4]) + 1

    # Annotate each trade with entry quality
    for t in all_trades:
        t["_quality"] = _entry_quality(t)

    # Filtered trades (default: exclude EXTENDED)
    if show_extended:
        filt = all_trades
        filter_label = "ALL (including EXTENDED)"
    else:
        filt = [t for t in all_trades if t["_quality"] != "EXTENDED"]
        filter_label = "EARLY + OPTIMAL (EXTENDED excluded)"

    _double_hr()
    print(f"  FULL SYSTEM VALIDATION — {START_DATE[:4]}–{END_DATE[:4]}")
    print(f"  Mode:   Legacy (params=None) — identical to live scanner")
    print(f"  Filter: {filter_label}")
    print(f"  Universe: {len({t['ticker'] for t in all_trades})} tickers")
    _double_hr()

    # ── [1] Entry quality breakdown ───────────────────────────────────────────
    print("\n[1] ENTRY QUALITY BREAKDOWN (all trades before filtering)")
    for q in ("EARLY", "OPTIMAL", "EXTENDED", "UNKNOWN"):
        subset = [t for t in all_trades if t["_quality"] == q]
        if not subset:
            continue
        s = _stats(subset)
        print(f"  {q:<10} n={s['n']:>5}  win={s['win_rate']:.1f}%  "
              f"exp={s['expectancy']:+.3f}R  pf={s['profit_factor'] if s['profit_factor'] != float('inf') else 'inf':.2f}  "
              f"dd={s['max_dd']:.1f}%")

    # ── [2] Combined summary ──────────────────────────────────────────────────
    sections = {
        f"ALL ({len(all_trades)})":  _stats(all_trades),
        f"EARLY+OPT ({len(filt)})":  _stats(filt),
        f"EARLY ({len([t for t in all_trades if t['_quality']=='EARLY'])})":
            _stats([t for t in all_trades if t["_quality"] == "EARLY"]),
        f"OPTIMAL ({len([t for t in all_trades if t['_quality']=='OPTIMAL'])})":
            _stats([t for t in all_trades if t["_quality"] == "OPTIMAL"]),
    }
    _print_summary_table("\n[2] COMBINED SUMMARY", sections)

    # ── [3] By regime ─────────────────────────────────────────────────────────
    print("\n[3] REGIME BREAKDOWN (using filter above)")
    _double_hr()
    for regime in ALL_REGIMES:
        regime_trades = [t for t in filt if t.get("regime") == regime]
        if not regime_trades and regime == "DEFENSIVE":
            print(f"\n  {regime} — 0 trades (all blocked by regime gate, as expected)")
            continue
        if not regime_trades:
            continue
        s = _stats(regime_trades)
        pct_of_all = len(regime_trades) / len(filt) * 100 if filt else 0
        print(f"\n  ── {regime}  ({len(regime_trades)} trades, {pct_of_all:.1f}% of filtered)")
        _print_regime_breakdown(regime, regime_trades, show_extended=True)  # already filtered

    # ── [4] Capital curve ─────────────────────────────────────────────────────
    print("\n[4] CAPITAL CURVE SIMULATION")
    _double_hr()
    sys_curve = _capital_curve(filt)
    spy_curve = _spy_curve(spy_df)

    print(f"\n  {'Year':<8} {'System':>10} {'SPY':>10} {'vs SPY':>10} {'YoY System':>12}")
    print(f"  {'────':<8} {'──────':>10} {'───':>10} {'──────':>10} {'──────────':>12}")
    prev_sys = 1.0
    for year in range(int(START_DATE[:4]), int(END_DATE[:4]) + 1):
        sys_eq  = sys_curve.get(year, 1.0)
        spy_eq  = spy_curve.get(year, 1.0)
        vs_spy  = sys_eq - spy_eq
        yoy     = (sys_eq / prev_sys - 1) * 100 if prev_sys > 0 else 0.0
        prev_sys = sys_eq
        sign = "+" if vs_spy >= 0 else ""
        print(f"  {year:<8} {sys_eq:>9.3f}x {spy_eq:>9.3f}x {sign}{vs_spy:>+.3f}x {yoy:>+10.1f}%")

    sys_final = sys_curve.get(int(END_DATE[:4]), 1.0)
    spy_final = spy_curve.get(int(END_DATE[:4]), 1.0)
    sys_cagr  = _cagr(1.0, sys_final, n_years)
    spy_cagr  = _cagr(1.0, spy_final, n_years)

    # Max drawdown of system curve (computed per trade)
    s_all = _stats(filt)
    print(f"\n  System CAGR:    {sys_cagr:+.1f}%")
    print(f"  SPY CAGR:       {spy_cagr:+.1f}%")
    print(f"  Alpha (CAGR):   {sys_cagr - spy_cagr:+.1f}%")
    print(f"  System max DD:  -{s_all['max_dd']:.1f}%")

    # ── [5] Key insights ──────────────────────────────────────────────────────
    print("\n[5] KEY INSIGHTS")
    _double_hr()

    # Profit concentration: which regime+setup combo generates the most expectancy
    combos = []
    for regime in ("AGGRESSIVE", "SELECTIVE"):
        for stype in SETUP_ORDER:
            subset = [t for t in filt if t.get("regime") == regime and t["setup_type"] == stype]
            if len(subset) >= 10:
                s = _stats(subset)
                combos.append((regime, stype, s["n"], s["expectancy"], s["win_rate"]))

    combos.sort(key=lambda x: x[3], reverse=True)
    print("\n  Best expectancy combos (regime × setup, min 10 trades):")
    for regime, stype, n, exp, wr in combos[:5]:
        print(f"    {regime:<12} {stype:<14} n={n:<5} exp={exp:+.3f}R  win={wr:.1f}%")

    # Worst combos (loss concentration)
    print("\n  Worst expectancy combos:")
    for regime, stype, n, exp, wr in combos[-3:]:
        print(f"    {regime:<12} {stype:<14} n={n:<5} exp={exp:+.3f}R  win={wr:.1f}%")

    # SELECTIVE contribution
    sel_all  = [t for t in filt if t.get("regime") == "SELECTIVE"]
    agg_all  = [t for t in filt if t.get("regime") == "AGGRESSIVE"]
    sel_s    = _stats(sel_all)
    agg_s    = _stats(agg_all)
    print(f"\n  SELECTIVE contribution:")
    print(f"    SELECTIVE trades: {sel_s['n']}  ({sel_s['n'] / len(filt) * 100:.1f}% of filtered)")
    print(f"    SELECTIVE expectancy: {sel_s['expectancy']:+.3f}R  vs AGGRESSIVE: {agg_s['expectancy']:+.3f}R")

    sel_brk = [t for t in sel_all if t["setup_type"] == "RES_BREAKOUT"]
    sel_pb  = [t for t in sel_all if t["setup_type"] == "PULLBACK"]
    if sel_brk:
        b = _stats(sel_brk)
        print(f"    SELECTIVE RES_BREAKOUT: n={b['n']}  exp={b['expectancy']:+.3f}R  win={b['win_rate']:.1f}%")
    if sel_pb:
        p = _stats(sel_pb)
        print(f"    SELECTIVE PULLBACK:     n={p['n']}  exp={p['expectancy']:+.3f}R  win={p['win_rate']:.1f}%")

    _double_hr()
    print(f"\n  Run complete. Total trades: {len(all_trades)} raw | {len(filt)} after quality filter.")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Full system backtest validation 2020-2024")
    parser.add_argument("--show-extended", action="store_true",
                        help="Include EXTENDED entries (default: exclude them)")
    args = parser.parse_args()

    print(f"\nFull System Backtest Validation")
    print(f"Period:  {START_DATE} → {END_DATE}")
    print(f"Cache:   {CACHE_DIR}")
    print(f"Mode:    legacy (params=None) — matches live scanner")
    print(f"Filter:  {'--show-extended (all entries)' if args.show_extended else 'EARLY+OPTIMAL only (--show-extended to include EXTENDED)'}")
    print()

    loaded_dfs, spy_df = _load_all_cached(CACHE_DIR)

    print(f"\nRunning backtest {START_DATE} → {END_DATE}...")
    all_trades = asyncio.run(_run_all(loaded_dfs, spy_df))
    print(f"Total raw trades: {len(all_trades)}\n")

    _print_report(all_trades, spy_df, show_extended=args.show_extended)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the script structure (no actual backtest)**

```bash
cd backend
python -c "
import sys; sys.path.insert(0, '.')
sys.argv = ['test']
# Import only — check no syntax errors
import importlib.util, os
spec = importlib.util.spec_from_file_location('val', '../scripts/backtest_full_validation.py')
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Test helpers directly
t_early    = {'entry_price': 100.05, 'setup_meta': {'atr': 1.0, 'entry': 100.0}, 'rr_achieved': 1.5, 'portfolio_pnl_pct': 0.3, 'holding_days': 8}
t_extended = {'entry_price': 101.0,  'setup_meta': {'atr': 1.0, 'entry': 100.0}, 'rr_achieved': -1.0, 'portfolio_pnl_pct': -0.2, 'holding_days': 4}
assert mod._entry_quality(t_early) == 'EARLY',    f'Expected EARLY, got {mod._entry_quality(t_early)}'
assert mod._entry_quality(t_extended) == 'EXTENDED', f'Expected EXTENDED, got {mod._entry_quality(t_extended)}'
s = mod._stats([t_early, t_extended])
assert s['n'] == 2
assert abs(s['win_rate'] - 50.0) < 0.01
print('Smoke test PASSED')
"
```

Expected output: `Smoke test PASSED`

- [ ] **Step 3: Commit**

```bash
git add scripts/backtest_full_validation.py
git commit -m "feat(scripts): add full system validation script 2020-2024 with regime/setup/quality breakdown"
```

---

## Task 4: Run the backtest and present results

**Files:** No new files — just execution.

### Context

This task runs the actual backtest and captures output. The run will take several minutes. Run from the `backend/` directory so relative imports work correctly.

- [ ] **Step 1: Run the validation (takes 5–20 min depending on cache size)**

```bash
cd backend
python ../scripts/backtest_full_validation.py 2>&1 | tee ../docs/backtest_validation_2026-03-21.txt
```

If cache is missing or incomplete:
```bash
# Check cache exists
ls data/price_cache/*.parquet | wc -l
# Expected: 700+ files
```

- [ ] **Step 2: Also run with --show-extended to see what gets filtered**

```bash
cd backend
python ../scripts/backtest_full_validation.py --show-extended 2>&1 | tee ../docs/backtest_validation_extended_2026-03-21.txt
```

- [ ] **Step 3: Present key results to user**

After both runs complete, summarize:
- Total trade counts (raw vs filtered)
- Combined expectancy (EARLY+OPTIMAL only)
- Best regime × setup combo
- SELECTIVE contribution
- System CAGR vs SPY CAGR
- Where profits are concentrated
- Where losses are concentrated

- [ ] **Step 4: Commit output files**

```bash
git add docs/backtest_validation_2026-03-21.txt docs/backtest_validation_extended_2026-03-21.txt
git commit -m "docs(backtest): full system validation results 2020-2024"
git push origin main
```

---

## Summary

| Task | Output |
|------|--------|
| 1 | `backtest_engine.py` captures ATR + signal entry in `setup_meta` |
| 2 | Tests for all helpers (entry quality, stats, capital curve) |
| 3 | `scripts/backtest_full_validation.py` — complete validation runner |
| 4 | Actual backtest run + results presented |

**No parameters were changed.** This is a pure read-only validation using legacy mode (`params=None`).
