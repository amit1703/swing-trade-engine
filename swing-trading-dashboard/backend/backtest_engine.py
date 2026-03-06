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
import os
import sys
import uuid
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

WARMUP_BARS         = 252   # bars before start_date needed for indicator warmup
ZONE_RECOMPUTE_N    = 5     # recompute KDE zones every N trading days (performance)
MIN_BARS_FOR_SIGNAL = 60    # minimum bars before signal detection starts


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


# ─────────────────────────────────────────────────────────────────────────────
# Metrics aggregation
# ─────────────────────────────────────────────────────────────────────────────

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
    cumulative   = np.cumsum([t.pnl_pct for t in trades])
    running_max  = np.maximum.accumulate(cumulative)
    drawdowns    = running_max - cumulative
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


# ─────────────────────────────────────────────────────────────────────────────
# Trade management
# ─────────────────────────────────────────────────────────────────────────────

def _manage_open_trade(
    state: Dict,
    bar: Dict,
) -> tuple:
    """
    Advance one trading day for an open position.

    Stop is checked FIRST (conservative — protects against gap-downs).
    Then target. Then trailing stop is updated if we're still open.

    Modifies `state` in-place: trailing_stop may ratchet upward.

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
    low    = bar["low"]
    high   = bar["high"]
    close  = bar["close"]
    ema20  = bar["ema20"]
    stop   = state["trailing_stop"]
    target = state["take_profit"]
    entry  = state["entry_price"]

    # 1. Stop hit first (low ≤ stop → filled at stop price)
    if low <= stop:
        return True, stop, "STOP"

    # 2. Target hit (high ≥ target → filled at target)
    if high >= target:
        return True, target, "TARGET"

    # 3. Update trailing stop: ratchet to EMA20 only when in profit
    if close > entry and ema20 > stop:
        state["trailing_stop"] = ema20

    return False, None, None
