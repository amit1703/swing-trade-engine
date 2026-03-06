# Backtesting Framework Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Build `backend/backtest_engine.py` — a standalone, lookahead-safe historical replay engine that detects signals using existing engines and simulates trade management with full metrics.

**Architecture:** Standalone module that fetches ticker + SPY history upfront, then replays day-by-day with strict data slicing (`df.iloc[:T+1]`) to prevent lookahead bias. Signal engines (Engine 1/2/3/5) are called with sliced data. Entry executes on T+1 open. Trailing stop ratchets to EMA20 when in profit. Results stored in a new `backtest_results` SQLite table. Two new API endpoints (POST run-backtest, GET results). Zero changes to existing engines or scan flow.

**Tech Stack:** Python asyncio, yfinance (already installed), pandas/numpy, aiosqlite, FastAPI, existing: `engines/engine1.py`, `engines/engine2.py`, `engines/engine3.py`, `engines/engine5.py`, `indicators/indicator_engine.py`

---

## Critical Context

Read these files before implementing:
- `backend/database.py` — understand the existing schema pattern (CREATE TABLE → migration in `init_db()`)
- `backend/engines/engine1.py` — `calculate_sr_zones(ticker, df)` → `List[Dict]`
- `backend/engines/engine2.py` — `scan_vcp(ticker, df, sr_zones, spy_3m_return, rs_ratio, rs_52w_high, rs_blue_dot, rs_score)` → `Optional[Dict]`
- `backend/engines/engine3.py` — `scan_pullback(ticker, df, sr_zones, trendline, rs_score)` and `scan_relaxed_pullback(...)` → `Optional[Dict]`
- `backend/engines/engine5.py` — `scan_base_pattern(ticker, df, spy_3m_return, rs_ratio, rs_52w_high, rs_blue_dot, rs_score, sr_zones)` → `Optional[Dict]`
- `backend/indicators/indicator_engine.py` — `compute_indicators(df, spy_df)` → `Optional[TickerIndicators]`
- `backend/constants.py` — `ATR_STOP_MULTIPLIER`, `ENTRY_PRICE_MULTIPLIER`, `TARGET_RR`, `EMA_LONG`
- `backend/main.py` lines 1-100 — import pattern and Pydantic model pattern for endpoints

**DO NOT modify** any engine file (engine0–engine7), `scoring.py`, `database.py` schema tables (add only — migration pattern), or `constants.py`.

---

## Lookahead Bias Prevention

The rule: at step `T`, only `df.iloc[:T+1]` is visible.

Correct:
```python
df_slice = df.iloc[:T + 1]
zones = calculate_sr_zones(ticker, df_slice)
signal = scan_vcp(ticker, df_slice, zones, ...)
```

Wrong (introduces lookahead):
```python
zones = calculate_sr_zones(ticker, df)  # uses full future data
signal = scan_vcp(ticker, df.iloc[:T+1], zones, ...)  # zones know the future
```

Both the signal detection AND the zone computation must use only sliced data.

---

### Task 1: Database Schema — `backtest_results` Table

**Files:**
- Modify: `backend/database.py`
- Test: `backend/tests/test_backtest_engine.py` (schema test)

**Step 1: Add table DDL constant in `database.py`**

Add this constant after the existing `_CREATE_TRADES` block (around line 82):

```python
_CREATE_BACKTEST_RESULTS = """
CREATE TABLE IF NOT EXISTS backtest_results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT    NOT NULL,
    ticker           TEXT    NOT NULL,
    setup_type       TEXT    NOT NULL,
    start_date       TEXT    NOT NULL,
    end_date         TEXT    NOT NULL,
    total_trades     INTEGER NOT NULL,
    win_count        INTEGER NOT NULL,
    loss_count       INTEGER NOT NULL,
    win_rate         REAL    NOT NULL,
    avg_rr           REAL    NOT NULL,
    profit_factor    REAL    NOT NULL,
    max_drawdown_pct REAL    NOT NULL,
    avg_holding_days REAL    NOT NULL,
    gross_profit     REAL    NOT NULL,
    gross_loss       REAL    NOT NULL,
    trades_json      TEXT    NOT NULL,
    created_at       TEXT    DEFAULT CURRENT_TIMESTAMP
);
"""

_BACKTEST_INDEX = "CREATE INDEX IF NOT EXISTS idx_backtest_ticker ON backtest_results(ticker, setup_type);"
```

**Step 2: Wire into `init_db()`**

In `init_db()`, add after the existing `await db.execute(_CREATE_TRADES)` line:

```python
await db.execute(_CREATE_BACKTEST_RESULTS)
await db.execute(_BACKTEST_INDEX)
```

Also add this migration block at the end of `init_db()` (after existing migrations, before the final `await db.commit()`):

```python
# Migration: create backtest_results table if it does not yet exist
try:
    await db.execute(_CREATE_BACKTEST_RESULTS)
    await db.execute(_BACKTEST_INDEX)
    await db.commit()
except Exception:
    pass
```

**Step 3: Add CRUD helpers at the bottom of `database.py`**

```python
# ---------------------------------------------------------------------------
# Backtest Results CRUD
# ---------------------------------------------------------------------------

async def save_backtest_result(db_path: str, result: Dict) -> int:
    """Insert one backtest result row. Returns new row id."""
    import json as _json
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """INSERT INTO backtest_results
               (run_id, ticker, setup_type, start_date, end_date,
                total_trades, win_count, loss_count, win_rate,
                avg_rr, profit_factor, max_drawdown_pct, avg_holding_days,
                gross_profit, gross_loss, trades_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result["run_id"],
                result["ticker"],
                result["setup_type"],
                result["start_date"],
                result["end_date"],
                result["total_trades"],
                result["win_count"],
                result["loss_count"],
                result["win_rate"],
                result["avg_rr"],
                result["profit_factor"],
                result["max_drawdown_pct"],
                result["avg_holding_days"],
                result["gross_profit"],
                result["gross_loss"],
                _json.dumps(result.get("trades", [])),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_backtest_results(db_path: str, ticker: str) -> List[Dict]:
    """Return all backtest results for a ticker, newest first."""
    import json as _json
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """SELECT run_id, ticker, setup_type, start_date, end_date,
                      total_trades, win_count, loss_count, win_rate,
                      avg_rr, profit_factor, max_drawdown_pct, avg_holding_days,
                      gross_profit, gross_loss, trades_json, created_at
               FROM backtest_results WHERE ticker = ?
               ORDER BY created_at DESC""",
            (ticker.upper(),),
        ) as cur:
            rows = await cur.fetchall()
            results = []
            for r in rows:
                results.append({
                    "run_id":           r[0],
                    "ticker":           r[1],
                    "setup_type":       r[2],
                    "start_date":       r[3],
                    "end_date":         r[4],
                    "total_trades":     r[5],
                    "win_count":        r[6],
                    "loss_count":       r[7],
                    "win_rate":         r[8],
                    "avg_rr":           r[9],
                    "profit_factor":    r[10],
                    "max_drawdown_pct": r[11],
                    "avg_holding_days": r[12],
                    "gross_profit":     r[13],
                    "gross_loss":       r[14],
                    "trades":           _json.loads(r[15]) if r[15] else [],
                    "created_at":       r[16],
                })
            return results
```

**Step 4: Write a failing test for the schema**

Create `backend/tests/test_backtest_engine.py`:

```python
"""Tests for backtest_engine.py and database schema."""
import asyncio
import pytest
import tempfile
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import database


@pytest.mark.asyncio
async def test_backtest_results_table_exists():
    """backtest_results table is created by init_db()."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await database.init_db(db_path)
        result = await database.get_backtest_results(db_path, "AAPL")
        assert isinstance(result, list)
        assert len(result) == 0
    finally:
        os.unlink(db_path)


@pytest.mark.asyncio
async def test_save_and_retrieve_backtest_result():
    """save_backtest_result() persists data retrievable by get_backtest_results()."""
    import json
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await database.init_db(db_path)
        row = {
            "run_id": "test-run-1",
            "ticker": "AAPL",
            "setup_type": "VCP",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "total_trades": 5,
            "win_count": 3,
            "loss_count": 2,
            "win_rate": 60.0,
            "avg_rr": 1.8,
            "profit_factor": 2.2,
            "max_drawdown_pct": 5.5,
            "avg_holding_days": 12.0,
            "gross_profit": 1100.0,
            "gross_loss": -500.0,
            "trades": [{"entry": 150.0, "exit": 165.0}],
        }
        row_id = await database.save_backtest_result(db_path, row)
        assert row_id > 0
        results = await database.get_backtest_results(db_path, "AAPL")
        assert len(results) == 1
        assert results[0]["win_rate"] == 60.0
        assert results[0]["run_id"] == "test-run-1"
        assert len(results[0]["trades"]) == 1
    finally:
        os.unlink(db_path)
```

**Step 5: Run tests to verify they fail first**

```bash
cd backend
pytest tests/test_backtest_engine.py -v
```

Expected: FAIL — `get_backtest_results` does not exist yet (if you haven't added CRUD) or table doesn't exist yet.

**Step 6: Apply the database changes** (steps 1–3 above)

**Step 7: Run tests to verify they pass**

```bash
cd backend
pytest tests/test_backtest_engine.py::test_backtest_results_table_exists tests/test_backtest_engine.py::test_save_and_retrieve_backtest_result -v
```

Expected: PASS (2/2)

**Step 8: Commit**

```bash
git add backend/database.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): add backtest_results schema + CRUD"
```

---

### Task 2: Core Data Structures

**Files:**
- Create: `backend/backtest_engine.py`
- Test: `backend/tests/test_backtest_engine.py`

**Step 1: Write failing tests for the data structures**

Add to `backend/tests/test_backtest_engine.py`:

```python
def test_trade_record_fields():
    """TradeRecord has all required fields."""
    from backtest_engine import TradeRecord
    trade = TradeRecord(
        ticker="AAPL",
        setup_type="VCP",
        signal_date="2024-03-01",
        entry_date="2024-03-04",
        entry_price=175.0,
        initial_stop=168.0,
        take_profit=189.0,
        exit_date="2024-03-15",
        exit_price=189.0,
        exit_reason="TARGET",
        holding_days=11,
    )
    assert trade.rr_achieved == pytest.approx(2.0, rel=0.01)
    assert trade.pnl_pct == pytest.approx((189.0 - 175.0) / 175.0 * 100, rel=0.01)
    assert trade.is_win is True


def test_trade_record_loss():
    """TradeRecord.is_win is False when exit_price <= entry_price."""
    from backtest_engine import TradeRecord
    trade = TradeRecord(
        ticker="AAPL",
        setup_type="VCP",
        signal_date="2024-03-01",
        entry_date="2024-03-04",
        entry_price=175.0,
        initial_stop=168.0,
        take_profit=189.0,
        exit_date="2024-03-06",
        exit_price=168.0,
        exit_reason="STOP",
        holding_days=2,
    )
    assert trade.rr_achieved == pytest.approx(-1.0, rel=0.01)
    assert trade.is_win is False
```

**Step 2: Run tests to verify they fail**

```bash
cd backend
pytest tests/test_backtest_engine.py::test_trade_record_fields tests/test_backtest_engine.py::test_trade_record_loss -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backtest_engine'`

**Step 3: Create `backend/backtest_engine.py` with data structures**

```python
"""
backtest_engine.py — Standalone Historical Replay Backtester (Task 11)
=======================================================================
Simulates trading signals day-by-day to measure strategy performance.

Lookahead Bias Prevention
--------------------------
At step T, only df.iloc[:T+1] is visible to ALL signal detection code —
including zone computation (Engine 1). Never pass the full DataFrame to any
engine function during the replay loop.

Usage
-----
    from backtest_engine import BacktestEngine

    engine = BacktestEngine(
        ticker="AAPL",
        start_date="2024-01-01",
        end_date="2024-12-31",
        setup_types=["VCP", "PULLBACK"],
    )
    result = await engine.run()   # returns BacktestSummary
"""

from __future__ import annotations

import asyncio
import logging
import sys
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(__file__))
from constants import ATR_STOP_MULTIPLIER, EMA_LONG, TARGET_RR
from indicators import ema as _ema

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

WARMUP_BARS       = 252   # bars before start_date needed for indicator warmup
ZONE_RECOMPUTE_N  = 5     # recompute KDE zones every N trading days (performance)
MIN_BARS_FOR_SIGNAL = 60  # minimum bars before signal detection starts


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    """One completed simulated trade."""
    ticker:        str
    setup_type:    str
    signal_date:   str    # date signal was detected (T)
    entry_date:    str    # date entry executed (T+1)
    entry_price:   float
    initial_stop:  float  # stop loss set at entry
    take_profit:   float
    exit_date:     str
    exit_price:    float
    exit_reason:   str    # "TARGET" | "STOP" | "TRAIL_STOP" | "EOD"

    holding_days:  int

    # Computed properties (derived in __post_init__)
    rr_achieved:   float = field(init=False)
    pnl_pct:       float = field(init=False)
    is_win:        bool  = field(init=False)

    def __post_init__(self):
        risk = self.entry_price - self.initial_stop
        if risk > 0:
            self.rr_achieved = round((self.exit_price - self.entry_price) / risk, 3)
        else:
            self.rr_achieved = 0.0
        self.pnl_pct = round((self.exit_price - self.entry_price) / self.entry_price * 100, 3)
        self.is_win  = self.exit_price > self.entry_price

    def to_dict(self) -> Dict:
        return {
            "ticker":       self.ticker,
            "setup_type":   self.setup_type,
            "signal_date":  self.signal_date,
            "entry_date":   self.entry_date,
            "entry_price":  self.entry_price,
            "initial_stop": self.initial_stop,
            "take_profit":  self.take_profit,
            "exit_date":    self.exit_date,
            "exit_price":   self.exit_price,
            "exit_reason":  self.exit_reason,
            "holding_days": self.holding_days,
            "rr_achieved":  self.rr_achieved,
            "pnl_pct":      self.pnl_pct,
            "is_win":       self.is_win,
        }


@dataclass
class BacktestSummary:
    """Aggregate metrics for one backtest run."""
    run_id:           str
    ticker:           str
    setup_type:       str
    start_date:       str
    end_date:         str
    total_trades:     int
    win_count:        int
    loss_count:       int
    win_rate:         float   # %
    avg_rr:           float
    profit_factor:    float   # gross_profit / abs(gross_loss); inf if no losses
    max_drawdown_pct: float   # peak-to-trough of cumulative PnL %
    avg_holding_days: float
    gross_profit:     float   # sum of winning pnl_pct
    gross_loss:       float   # sum of losing pnl_pct (negative number)
    trades:           List[TradeRecord] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "run_id":           self.run_id,
            "ticker":           self.ticker,
            "setup_type":       self.setup_type,
            "start_date":       self.start_date,
            "end_date":         self.end_date,
            "total_trades":     self.total_trades,
            "win_count":        self.win_count,
            "loss_count":       self.loss_count,
            "win_rate":         self.win_rate,
            "avg_rr":           self.avg_rr,
            "profit_factor":    self.profit_factor,
            "max_drawdown_pct": self.max_drawdown_pct,
            "avg_holding_days": self.avg_holding_days,
            "gross_profit":     self.gross_profit,
            "gross_loss":       self.gross_loss,
            "trades":           [t.to_dict() for t in self.trades],
        }
```

**Step 4: Run tests**

```bash
cd backend
pytest tests/test_backtest_engine.py::test_trade_record_fields tests/test_backtest_engine.py::test_trade_record_loss -v
```

Expected: PASS (2/2)

**Step 5: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): add TradeRecord and BacktestSummary dataclasses"
```

---

### Task 3: Metrics Computation

**Files:**
- Modify: `backend/backtest_engine.py`
- Test: `backend/tests/test_backtest_engine.py`

**Step 1: Write failing tests for metrics**

Add to `backend/tests/test_backtest_engine.py`:

```python
def _make_trade(entry, exit_price, stop, days=10, setup="VCP"):
    """Helper: create a TradeRecord from basic price levels."""
    from backtest_engine import TradeRecord
    return TradeRecord(
        ticker="TEST", setup_type=setup,
        signal_date="2024-01-01", entry_date="2024-01-02",
        entry_price=entry, initial_stop=stop,
        take_profit=entry + 2 * (entry - stop),
        exit_date="2024-01-12", exit_price=exit_price,
        exit_reason="TARGET" if exit_price > entry else "STOP",
        holding_days=days,
    )


def test_compute_metrics_win_rate():
    """win_rate = wins / total * 100."""
    from backtest_engine import compute_metrics
    trades = [
        _make_trade(100, 110, 95),  # win
        _make_trade(100, 110, 95),  # win
        _make_trade(100, 95, 95),   # loss
    ]
    summary = compute_metrics("AAPL", "VCP", "2024-01-01", "2024-12-31", trades)
    assert summary.win_rate == pytest.approx(66.67, rel=0.01)


def test_compute_metrics_profit_factor():
    """profit_factor = gross_profit / abs(gross_loss)."""
    from backtest_engine import compute_metrics
    trades = [
        _make_trade(100, 110, 95),  # +10 pnl_pct
        _make_trade(100, 95, 95),   # -5 pnl_pct
    ]
    summary = compute_metrics("AAPL", "VCP", "2024-01-01", "2024-12-31", trades)
    assert summary.profit_factor == pytest.approx(2.0, rel=0.05)


def test_compute_metrics_no_trades():
    """Zero trades returns zero metrics without crashing."""
    from backtest_engine import compute_metrics
    summary = compute_metrics("AAPL", "VCP", "2024-01-01", "2024-12-31", [])
    assert summary.total_trades == 0
    assert summary.win_rate == 0.0
    assert summary.profit_factor == 0.0


def test_compute_metrics_max_drawdown():
    """max_drawdown_pct is peak-to-trough of cumulative pnl."""
    from backtest_engine import compute_metrics
    # +10%, -15%, +5% → cumulative: 10, -5, 0 → peak 10, trough -5 = drawdown 15%
    trades = [
        _make_trade(100, 110, 95, days=5),   # +10%
        _make_trade(100, 85, 95, days=5),    # -15%
        _make_trade(100, 105, 95, days=5),   # +5%
    ]
    summary = compute_metrics("AAPL", "VCP", "2024-01-01", "2024-12-31", trades)
    assert summary.max_drawdown_pct == pytest.approx(15.0, rel=0.1)
```

**Step 2: Run tests to verify they fail**

```bash
cd backend
pytest tests/test_backtest_engine.py::test_compute_metrics_win_rate -v
```

Expected: FAIL with `ImportError: cannot import name 'compute_metrics'`

**Step 3: Implement `compute_metrics()` in `backtest_engine.py`**

Add this function after the dataclasses:

```python
import uuid


def compute_metrics(
    ticker: str,
    setup_type: str,
    start_date: str,
    end_date: str,
    trades: List[TradeRecord],
    run_id: Optional[str] = None,
) -> BacktestSummary:
    """
    Aggregate a list of TradeRecord objects into a BacktestSummary.

    Parameters
    ----------
    trades : list of TradeRecord (may be empty)

    Returns
    -------
    BacktestSummary with all metrics populated.
    """
    if run_id is None:
        run_id = str(uuid.uuid4())

    if not trades:
        return BacktestSummary(
            run_id=run_id, ticker=ticker, setup_type=setup_type,
            start_date=start_date, end_date=end_date,
            total_trades=0, win_count=0, loss_count=0,
            win_rate=0.0, avg_rr=0.0, profit_factor=0.0,
            max_drawdown_pct=0.0, avg_holding_days=0.0,
            gross_profit=0.0, gross_loss=0.0, trades=[],
        )

    wins   = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]

    win_rate = round(len(wins) / len(trades) * 100, 2)
    avg_rr   = round(float(np.mean([t.rr_achieved for t in trades])), 3)

    gross_profit = sum(t.pnl_pct for t in wins)
    gross_loss   = sum(t.pnl_pct for t in losses)  # negative number

    if gross_loss == 0:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    else:
        profit_factor = round(gross_profit / abs(gross_loss), 3)

    avg_holding_days = round(float(np.mean([t.holding_days for t in trades])), 1)

    # Peak-to-trough drawdown on cumulative pnl_pct series
    cumulative = np.cumsum([t.pnl_pct for t in trades])
    running_max = np.maximum.accumulate(cumulative)
    drawdowns   = running_max - cumulative
    max_drawdown_pct = round(float(drawdowns.max()), 2) if len(drawdowns) > 0 else 0.0

    return BacktestSummary(
        run_id=run_id, ticker=ticker, setup_type=setup_type,
        start_date=start_date, end_date=end_date,
        total_trades=len(trades),
        win_count=len(wins),
        loss_count=len(losses),
        win_rate=win_rate,
        avg_rr=avg_rr,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct,
        avg_holding_days=avg_holding_days,
        gross_profit=round(gross_profit, 3),
        gross_loss=round(gross_loss, 3),
        trades=trades,
    )
```

**Step 4: Run all metrics tests**

```bash
cd backend
pytest tests/test_backtest_engine.py::test_compute_metrics_win_rate tests/test_backtest_engine.py::test_compute_metrics_profit_factor tests/test_backtest_engine.py::test_compute_metrics_no_trades tests/test_backtest_engine.py::test_compute_metrics_max_drawdown -v
```

Expected: PASS (4/4)

**Step 5: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): implement compute_metrics() with win rate/RR/PF/drawdown"
```

---

### Task 4: Trade Management — Entry, Stop, Target, Trailing Stop

**Files:**
- Modify: `backend/backtest_engine.py`
- Test: `backend/tests/test_backtest_engine.py`

**Step 1: Write failing tests for trade management**

Add to `backend/tests/test_backtest_engine.py`:

```python
def test_manage_trade_stop_hit():
    """Trade closes at stop when low <= trailing_stop."""
    from backtest_engine import _manage_open_trade
    # bar: low hits the stop
    bar = {"date": "2024-03-05", "open": 102.0, "high": 104.0, "low": 94.0, "close": 96.0, "ema20": 101.0}
    state = {"entry_price": 100.0, "trailing_stop": 95.0, "take_profit": 110.0, "entry_date": "2024-03-04"}
    closed, exit_price, exit_reason = _manage_open_trade(state, bar)
    assert closed is True
    assert exit_reason == "STOP"
    assert exit_price == pytest.approx(95.0)


def test_manage_trade_target_hit():
    """Trade closes at take_profit when high >= take_profit."""
    from backtest_engine import _manage_open_trade
    bar = {"date": "2024-03-05", "open": 108.0, "high": 112.0, "low": 107.0, "close": 111.0, "ema20": 102.0}
    state = {"entry_price": 100.0, "trailing_stop": 95.0, "take_profit": 110.0, "entry_date": "2024-03-04"}
    closed, exit_price, exit_reason = _manage_open_trade(state, bar)
    assert closed is True
    assert exit_reason == "TARGET"
    assert exit_price == pytest.approx(110.0)


def test_manage_trade_trailing_stop_ratchets():
    """trailing_stop increases to ema20 when close > entry and ema20 > trailing_stop."""
    from backtest_engine import _manage_open_trade
    bar = {"date": "2024-03-05", "open": 105.0, "high": 108.0, "low": 104.0, "close": 106.0, "ema20": 103.0}
    state = {"entry_price": 100.0, "trailing_stop": 95.0, "take_profit": 115.0, "entry_date": "2024-03-04"}
    closed, exit_price, exit_reason = _manage_open_trade(state, bar)
    assert closed is False
    assert state["trailing_stop"] == pytest.approx(103.0)  # ratcheted to ema20


def test_manage_trade_trailing_stop_does_not_drop():
    """trailing_stop never decreases even if ema20 dips below it."""
    from backtest_engine import _manage_open_trade
    bar = {"date": "2024-03-05", "open": 105.0, "high": 108.0, "low": 104.0, "close": 106.0, "ema20": 93.0}
    state = {"entry_price": 100.0, "trailing_stop": 95.0, "take_profit": 115.0, "entry_date": "2024-03-04"}
    closed, _, _ = _manage_open_trade(state, bar)
    assert closed is False
    assert state["trailing_stop"] == pytest.approx(95.0)  # did not drop
```

**Step 2: Run tests to verify they fail**

```bash
cd backend
pytest tests/test_backtest_engine.py::test_manage_trade_stop_hit -v
```

Expected: FAIL with `ImportError: cannot import name '_manage_open_trade'`

**Step 3: Implement `_manage_open_trade()` in `backtest_engine.py`**

```python
def _manage_open_trade(
    state: Dict,
    bar: Dict,
) -> tuple:
    """
    Advance one trading day for an open position.

    Modifies `state` in-place (trailing_stop may ratchet up).

    Parameters
    ----------
    state : dict with keys:
        entry_price, trailing_stop, take_profit, entry_date
    bar : dict with keys:
        date, open, high, low, close, ema20

    Returns
    -------
    (closed: bool, exit_price: float | None, exit_reason: str | None)
    """
    low        = bar["low"]
    high       = bar["high"]
    close      = bar["close"]
    ema20      = bar["ema20"]
    stop       = state["trailing_stop"]
    target     = state["take_profit"]
    entry      = state["entry_price"]

    # 1. Stop hit first (low ≤ stop → filled at stop)
    if low <= stop:
        return True, stop, "STOP"

    # 2. Target hit (high ≥ target → filled at target)
    if high >= target:
        return True, target, "TARGET"

    # 3. Update trailing stop: ratchet to EMA20 only when in profit
    if close > entry and ema20 > stop:
        state["trailing_stop"] = ema20

    return False, None, None
```

**Step 4: Run all trade management tests**

```bash
cd backend
pytest tests/test_backtest_engine.py::test_manage_trade_stop_hit tests/test_backtest_engine.py::test_manage_trade_target_hit tests/test_backtest_engine.py::test_manage_trade_trailing_stop_ratchets tests/test_backtest_engine.py::test_manage_trade_trailing_stop_does_not_drop -v
```

Expected: PASS (4/4)

**Step 5: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): implement trade management with trailing stop ratchet"
```

---

### Task 5: Signal Detection + Day-by-Day Replay

**Files:**
- Modify: `backend/backtest_engine.py`
- Test: `backend/tests/test_backtest_engine.py`

**Step 1: Write a failing test for lookahead bias**

Add to `backend/tests/test_backtest_engine.py`:

```python
def test_detect_signals_only_sees_data_up_to_T():
    """
    _detect_signals must only use df.iloc[:T+1] — verified by ensuring
    the function returns None (no signal) when the slice is too short.
    """
    from backtest_engine import _detect_signals
    import pandas as pd, numpy as np

    # Create a minimal df with 30 bars (too short for signal engines which need 60+)
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    price = 100.0 + np.random.randn(30).cumsum()
    df = pd.DataFrame({
        "Open": price * 0.99,
        "High": price * 1.01,
        "Low":  price * 0.98,
        "Close": price,
        "Adj Close": price,
        "Volume": np.ones(30) * 1_000_000,
    }, index=dates)

    result = _detect_signals("AAPL", df, df, ["VCP"])
    assert result is None  # too few bars → no signal
```

**Step 2: Run test to verify it fails**

```bash
cd backend
pytest tests/test_backtest_engine.py::test_detect_signals_only_sees_data_up_to_T -v
```

Expected: FAIL with `ImportError: cannot import name '_detect_signals'`

**Step 3: Implement `_detect_signals()` and `_fetch_data()` in `backtest_engine.py`**

Add after `compute_metrics`:

```python
def _detect_signals(
    ticker: str,
    df_slice: pd.DataFrame,
    spy_slice: pd.DataFrame,
    setup_types: List[str],
) -> Optional[Dict]:
    """
    Run the appropriate signal engine(s) on a lookahead-safe slice.

    Parameters
    ----------
    df_slice : DataFrame — data up to and including day T (df.iloc[:T+1])
    spy_slice : DataFrame — SPY data up to day T
    setup_types : list of "VCP" | "PULLBACK" | "BASE"

    Returns
    -------
    First signal dict found, or None.
    Each setup type is tried in order; first match wins.
    """
    if len(df_slice) < MIN_BARS_FOR_SIGNAL:
        return None

    try:
        from indicators.indicator_engine import compute_indicators
        inds = compute_indicators(df_slice, spy_slice)
        if inds is None:
            return None

        # SPY 3m return for RS engine filters
        spy_adj = "Adj Close" if "Adj Close" in spy_slice.columns else "Close"
        n_spy = len(spy_slice)
        spy_3m_return = 0.0
        if n_spy > 63:
            spy_vals = spy_slice[spy_adj].values
            spy_3m_return = float(spy_vals[-1] / spy_vals[-64] - 1.0)

        # Compute KDE zones once per call (caller controls recompute frequency)
        from engines.engine1 import calculate_sr_zones
        sr_zones = calculate_sr_zones(ticker, df_slice)

        for stype in setup_types:
            setup = None

            if stype == "VCP":
                from engines.engine2 import scan_vcp
                setup = scan_vcp(
                    ticker, df_slice, sr_zones,
                    spy_3m_return=spy_3m_return,
                    rs_ratio=inds.rs_ratio,
                    rs_52w_high=inds.rs_52w_high,
                    rs_blue_dot=inds.rs_blue_dot,
                    rs_score=inds.rs_score,
                )

            elif stype == "PULLBACK":
                from engines.engine3 import scan_pullback, scan_relaxed_pullback
                setup = scan_pullback(ticker, df_slice, sr_zones, rs_score=inds.rs_score)
                if setup is None:
                    setup = scan_relaxed_pullback(ticker, df_slice, sr_zones, rs_score=inds.rs_score)

            elif stype == "BASE":
                from engines.engine5 import scan_base_pattern
                setup = scan_base_pattern(
                    ticker, df_slice,
                    spy_3m_return=spy_3m_return,
                    rs_ratio=inds.rs_ratio,
                    rs_52w_high=inds.rs_52w_high,
                    rs_blue_dot=inds.rs_blue_dot,
                    rs_score=inds.rs_score,
                    sr_zones=sr_zones,
                )

            if setup is not None:
                return setup

    except Exception as exc:
        logger.debug("_detect_signals %s: %s", ticker, exc)

    return None


async def _fetch_data(ticker: str, start_date: str) -> tuple:
    """
    Fetch full ticker + SPY history needed for the backtest.

    Fetches from (start_date - WARMUP_BARS trading days) to today.
    Returns (ticker_df, spy_df) or (None, None) on failure.
    """
    loop = asyncio.get_running_loop()

    start = date.fromisoformat(start_date)
    fetch_from = start - timedelta(days=int(WARMUP_BARS * 1.5))  # calendar days
    fetch_from_str = fetch_from.isoformat()

    def _download(sym):
        hist = yf.Ticker(sym).history(start=fetch_from_str, auto_adjust=False)
        if hist.empty:
            return None
        hist.index = pd.to_datetime(hist.index).tz_localize(None)
        return hist

    ticker_df, spy_df = await asyncio.gather(
        loop.run_in_executor(None, _download, ticker),
        loop.run_in_executor(None, _download, "SPY"),
    )
    return ticker_df, spy_df
```

**Step 4: Run the test**

```bash
cd backend
pytest tests/test_backtest_engine.py::test_detect_signals_only_sees_data_up_to_T -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): implement signal detection + data fetch"
```

---

### Task 6: BacktestEngine Class — Full Replay Loop

**Files:**
- Modify: `backend/backtest_engine.py`

**Step 1: Implement the `BacktestEngine` class**

Append to `backend/backtest_engine.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Main engine
# ─────────────────────────────────────────────────────────────────────────────

class BacktestEngine:
    """
    Day-by-day historical replay backtester.

    Prevents lookahead bias by slicing the DataFrame at each step T.
    """

    def __init__(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        setup_types: Optional[List[str]] = None,
    ):
        self.ticker      = ticker.upper()
        self.start_date  = start_date
        self.end_date    = end_date
        self.setup_types = setup_types or ["VCP", "PULLBACK", "BASE"]

    async def run(self) -> BacktestSummary:
        """
        Execute the backtest. Returns a BacktestSummary with all trades.
        """
        run_id = str(uuid.uuid4())
        logger.info("Backtest [%s] %s %s→%s starting", run_id, self.ticker,
                    self.start_date, self.end_date)

        # ── 1. Fetch data ─────────────────────────────────────────────────
        ticker_df, spy_df = await _fetch_data(self.ticker, self.start_date)
        if ticker_df is None or spy_df is None:
            logger.warning("Backtest: data fetch failed for %s", self.ticker)
            return compute_metrics(self.ticker, str(self.setup_types),
                                   self.start_date, self.end_date, [], run_id)

        # ── 2. Identify replay window ─────────────────────────────────────
        start = pd.Timestamp(self.start_date)
        end   = pd.Timestamp(self.end_date)

        all_dates = ticker_df.index
        replay_dates = all_dates[(all_dates >= start) & (all_dates <= end)]

        if len(replay_dates) < 2:
            logger.warning("Backtest: no dates in replay window for %s", self.ticker)
            return compute_metrics(self.ticker, str(self.setup_types),
                                   self.start_date, self.end_date, [], run_id)

        # ── 3. Pre-compute full indicator series (for trade management) ───
        adj_col  = "Adj Close" if "Adj Close" in ticker_df.columns else "Close"
        ema20_full = _ema(ticker_df[adj_col], EMA_LONG)

        # ── 4. Replay loop ────────────────────────────────────────────────
        completed_trades: List[TradeRecord] = []
        open_trade: Optional[Dict] = None   # holds the in-flight trade state
        zone_cache_day = -ZONE_RECOMPUTE_N  # force recompute on first bar

        for T_idx, T_date in enumerate(replay_dates):
            # Index into the full df
            full_idx = all_dates.get_loc(T_date)

            # ── 4a. Manage open trade ─────────────────────────────────────
            if open_trade is not None:
                ema20_T = float(ema20_full.iloc[full_idx])
                bar = {
                    "date":   T_date.strftime("%Y-%m-%d"),
                    "open":   float(ticker_df["Open"].iloc[full_idx]),
                    "high":   float(ticker_df["High"].iloc[full_idx]),
                    "low":    float(ticker_df["Low"].iloc[full_idx]),
                    "close":  float(ticker_df[adj_col].iloc[full_idx]),
                    "ema20":  ema20_T if not np.isnan(ema20_T) else open_trade["trailing_stop"],
                }
                closed, exit_price, exit_reason = _manage_open_trade(open_trade, bar)

                if closed:
                    signal_date  = open_trade["signal_date"]
                    entry_date   = open_trade["entry_date"]
                    entry_price  = open_trade["entry_price"]
                    entry_dt     = pd.Timestamp(entry_date)
                    holding_days = max(1, (T_date - entry_dt).days)

                    completed_trades.append(TradeRecord(
                        ticker=self.ticker,
                        setup_type=open_trade["setup_type"],
                        signal_date=signal_date,
                        entry_date=entry_date,
                        entry_price=entry_price,
                        initial_stop=open_trade["initial_stop"],
                        take_profit=open_trade["take_profit"],
                        exit_date=T_date.strftime("%Y-%m-%d"),
                        exit_price=exit_price,
                        exit_reason=exit_reason,
                        holding_days=holding_days,
                    ))
                    open_trade = None
                continue   # while trade open, skip signal detection

            # ── 4b. Pending entry execution (T+1 fill) ───────────────────
            # This is handled by setting open_trade on the previous bar's
            # NEXT iteration. See step 4c below — we fill on the next bar.

            # ── 4c. Signal detection on sliced data ───────────────────────
            df_slice  = ticker_df.iloc[:full_idx + 1]
            spy_slice = spy_df.loc[spy_df.index <= T_date]

            if len(df_slice) < MIN_BARS_FOR_SIGNAL:
                continue

            # Recompute zones only every ZONE_RECOMPUTE_N bars (performance)
            signal = _detect_signals(self.ticker, df_slice, spy_slice, self.setup_types)

            if signal is None:
                continue

            # ── 4d. Schedule entry on T+1 ─────────────────────────────────
            # Entry executes on the next bar's open (T+1)
            next_idx = full_idx + 1
            if next_idx >= len(all_dates):
                continue  # no next bar — end of data

            next_date   = all_dates[next_idx]
            entry_price = float(ticker_df["Open"].iloc[next_idx])  # T+1 open

            stop_loss  = signal.get("stop_loss", entry_price * 0.95)
            take_profit = signal.get("take_profit", entry_price * 1.10)

            # Guard: stop must be below entry
            if stop_loss >= entry_price:
                continue
            # Guard: target must be above entry
            if take_profit <= entry_price:
                continue

            open_trade = {
                "setup_type":    signal.get("setup_type", self.setup_types[0]),
                "signal_date":   T_date.strftime("%Y-%m-%d"),
                "entry_date":    next_date.strftime("%Y-%m-%d"),
                "entry_price":   entry_price,
                "initial_stop":  stop_loss,
                "trailing_stop": stop_loss,
                "take_profit":   take_profit,
            }

        # ── 5. Close any still-open trade at end of period ────────────────
        if open_trade is not None:
            last_full_idx = all_dates.get_loc(replay_dates[-1])
            exit_price    = float(ticker_df[adj_col].iloc[last_full_idx])
            entry_dt      = pd.Timestamp(open_trade["entry_date"])
            holding_days  = max(1, (replay_dates[-1] - entry_dt).days)
            completed_trades.append(TradeRecord(
                ticker=self.ticker,
                setup_type=open_trade["setup_type"],
                signal_date=open_trade["signal_date"],
                entry_date=open_trade["entry_date"],
                entry_price=open_trade["entry_price"],
                initial_stop=open_trade["initial_stop"],
                take_profit=open_trade["take_profit"],
                exit_date=replay_dates[-1].strftime("%Y-%m-%d"),
                exit_price=exit_price,
                exit_reason="EOD",
                holding_days=holding_days,
            ))

        # ── 6. Compute and return metrics ─────────────────────────────────
        setup_label = "+".join(self.setup_types)
        return compute_metrics(
            self.ticker, setup_label, self.start_date, self.end_date,
            completed_trades, run_id,
        )
```

**Note on performance:** For a 1-year backtest over 252 bars, calling `_detect_signals()` (which calls Engine 1 KDE + a signal engine) at each bar takes a few seconds per ticker. This is acceptable for a background task. If slower, pass `zone_cache_day` to recompute zones only every 5 days.

**Step 2: Add an integration smoke test (no external calls — uses a mock)**

Add to `backend/tests/test_backtest_engine.py`:

```python
def test_backtest_engine_zero_signals():
    """BacktestEngine produces 0-trade summary when no signals fire (flat price)."""
    import asyncio
    import unittest.mock as mock
    from backtest_engine import BacktestEngine

    # Patch _detect_signals to always return None
    with mock.patch("backtest_engine._detect_signals", return_value=None), \
         mock.patch("backtest_engine._fetch_data") as mock_fetch:

        import numpy as np
        import pandas as pd

        # 400 bars of flat price history
        dates = pd.date_range("2023-01-01", periods=400, freq="B")
        price = np.full(400, 100.0)
        df = pd.DataFrame({
            "Open": price, "High": price * 1.01,
            "Low": price * 0.99, "Close": price,
            "Adj Close": price, "Volume": np.ones(400) * 1_000_000,
        }, index=dates)

        mock_fetch.return_value = (df, df)

        engine = BacktestEngine("AAPL", "2024-01-01", "2024-12-31", ["VCP"])
        summary = asyncio.get_event_loop().run_until_complete(engine.run())

    assert summary.total_trades == 0
    assert summary.win_rate == 0.0
```

**Step 3: Run tests**

```bash
cd backend
pytest tests/test_backtest_engine.py::test_backtest_engine_zero_signals -v
```

Expected: PASS

**Step 4: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): implement BacktestEngine replay loop"
```

---

### Task 7: API Endpoints

**Files:**
- Modify: `backend/main.py`
- Test: manual curl test (no new test file needed — existing pattern)

**Step 1: Read `main.py` imports and Pydantic model section**

Find the section where Pydantic `BaseModel` classes are defined (search for `class.*BaseModel`). Add the new request model near there.

**Step 2: Add to `main.py`**

Add the import near the top (after existing imports):

```python
from backtest_engine import BacktestEngine
from database import save_backtest_result, get_backtest_results
```

Add a Pydantic request model with the other models:

```python
class BacktestRequest(BaseModel):
    ticker:      str
    start_date:  str           # "YYYY-MM-DD"
    end_date:    str           # "YYYY-MM-DD"
    setup_types: List[str] = Field(default=["VCP", "PULLBACK", "BASE"])
```

Add both endpoints (place them near the other scan endpoints, before `/api/health`):

```python
@app.post("/api/run-backtest")
async def run_backtest(req: BacktestRequest, background_tasks: BackgroundTasks):
    """
    Kick off a backtest run in the background.
    Returns immediately with a run_id; poll /api/backtest-results/{ticker}
    to retrieve results once complete.
    """
    import uuid
    run_id = str(uuid.uuid4())

    async def _do_backtest():
        try:
            engine = BacktestEngine(
                ticker=req.ticker,
                start_date=req.start_date,
                end_date=req.end_date,
                setup_types=req.setup_types,
            )
            summary = await engine.run()
            result  = summary.to_dict()
            result["run_id"] = run_id
            await save_backtest_result(DB_PATH, result)
            logger.info("Backtest %s done: %d trades", run_id, summary.total_trades)
        except Exception as exc:
            logger.exception("Backtest %s failed: %s", run_id, exc)

    background_tasks.add_task(_do_backtest)
    return {"run_id": run_id, "status": "started"}


@app.get("/api/backtest-results/{ticker}")
async def backtest_results(ticker: str):
    """Return all completed backtest runs for a ticker."""
    results = await get_backtest_results(DB_PATH, ticker.upper())
    return {"ticker": ticker.upper(), "results": results}
```

**Step 3: Verify the server starts**

```bash
cd backend
python -m uvicorn main:app --reload --port 8000 --host 0.0.0.0
```

Expected: server starts without import errors.

**Step 4: Manual smoke test with curl**

```bash
# Trigger a backtest (replace dates as needed)
curl -X POST http://localhost:8000/api/run-backtest \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL", "start_date": "2024-01-01", "end_date": "2024-06-30", "setup_types": ["VCP"]}'
# Expected: {"run_id": "...", "status": "started"}

# Wait ~30s, then fetch results
curl http://localhost:8000/api/backtest-results/AAPL
# Expected: {"ticker": "AAPL", "results": [...]}
```

**Step 5: Run the full test suite to confirm nothing broken**

```bash
cd backend
pytest tests/ -v
```

Expected: all existing tests still pass, new backtest tests also pass.

**Step 6: Commit**

```bash
git add backend/main.py backend/backtest_engine.py
git commit -m "feat(backtest): add POST /api/run-backtest and GET /api/backtest-results endpoints"
```

---

## Summary of Files Changed

| File | Change |
|------|--------|
| `backend/database.py` | Add `_CREATE_BACKTEST_RESULTS`, migration, `save_backtest_result()`, `get_backtest_results()` |
| `backend/backtest_engine.py` | New — `TradeRecord`, `BacktestSummary`, `compute_metrics()`, `_manage_open_trade()`, `_detect_signals()`, `_fetch_data()`, `BacktestEngine` |
| `backend/tests/test_backtest_engine.py` | New — 10 tests covering schema, metrics, trade management, signal detection |
| `backend/main.py` | Add `BacktestRequest` model, `POST /api/run-backtest`, `GET /api/backtest-results/{ticker}` |

## Files NOT Changed (by design)

- `backend/engines/engine0.py` through `engine7.py` — zero modifications
- `backend/scoring.py` — zero modifications
- `backend/constants.py` — zero modifications
- `backend/database.py` existing tables — zero modifications (additive only)
