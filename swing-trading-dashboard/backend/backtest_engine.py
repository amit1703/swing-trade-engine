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
