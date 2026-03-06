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
from constants import EMA_LONG
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
    exit_reason:   str    # "TARGET" | "STOP" | "EOD"
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
    avg_rr:           float   # mean R across ALL trades (expectancy)
    profit_factor:    float   # gross_profit / abs(gross_loss); inf if no losses
    max_drawdown_pct: float   # peak-to-trough of compound equity curve %
    avg_holding_days: float
    gross_profit:     float   # sum of winning pnl_pct
    gross_loss:       float   # sum of losing pnl_pct (negative number)
    avg_win_r:        float = 0.0  # mean R of winning trades only
    avg_loss_r:       float = 0.0  # mean R of losing trades only
    peak_equity:      float = 0.0  # peak compound equity as % gain (e.g. 15.3 = +15.3%)
    net_profit_pct:   float = 0.0  # gross_profit + gross_loss
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
            "avg_win_r":        self.avg_win_r,
            "avg_loss_r":       self.avg_loss_r,
            "peak_equity":      self.peak_equity,
            "profit_factor":    self.profit_factor,
            "max_drawdown_pct": self.max_drawdown_pct,
            "avg_holding_days": self.avg_holding_days,
            "gross_profit":     self.gross_profit,
            "gross_loss":       self.gross_loss,
            "net_profit_pct":   self.net_profit_pct,
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
            win_rate=0.0, avg_rr=0.0, avg_win_r=0.0, avg_loss_r=0.0,
            profit_factor=0.0,
            max_drawdown_pct=0.0, peak_equity=0.0, avg_holding_days=0.0,
            gross_profit=0.0, gross_loss=0.0, net_profit_pct=0.0, trades=[],
        )

    wins   = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]

    win_rate = round(len(wins) / len(trades) * 100, 2)

    # Avg R across ALL trades (= expectancy in R-multiples)
    avg_rr = round(float(np.mean([t.rr_achieved for t in trades])), 3)

    # Avg R for wins and losses separately
    avg_win_r  = round(float(np.mean([t.rr_achieved for t in wins])),   3) if wins   else 0.0
    avg_loss_r = round(float(np.mean([t.rr_achieved for t in losses])), 3) if losses else 0.0

    gross_profit = sum(t.pnl_pct for t in wins)
    gross_loss   = sum(t.pnl_pct for t in losses)  # negative number
    net_profit_pct = round(gross_profit + gross_loss, 3)

    if gross_loss == 0:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    else:
        profit_factor = round(gross_profit / abs(gross_loss), 3)

    avg_holding_days = round(float(np.mean([t.holding_days for t in trades])), 1)

    # Compound equity curve starting at $1 (normalized)
    equity   = 1.0
    peak     = 1.0
    max_dd   = 0.0
    for t in trades:
        equity *= (1.0 + t.pnl_pct / 100.0)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
    max_drawdown_pct = round(max_dd, 2)
    peak_equity      = round((peak - 1.0) * 100.0, 2)   # % gain at peak

    return BacktestSummary(
        run_id=run_id, ticker=ticker, setup_type=setup_type,
        start_date=start_date, end_date=end_date,
        total_trades=len(trades),
        win_count=len(wins),
        loss_count=len(losses),
        win_rate=win_rate,
        avg_rr=avg_rr,
        avg_win_r=avg_win_r,
        avg_loss_r=avg_loss_r,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct,
        peak_equity=peak_equity,
        avg_holding_days=avg_holding_days,
        gross_profit=round(gross_profit, 3),
        gross_loss=round(gross_loss, 3),
        net_profit_pct=net_profit_pct,
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


# ─────────────────────────────────────────────────────────────────────────────
# Signal detection (lookahead-safe)
# ─────────────────────────────────────────────────────────────────────────────

def _detect_signals(
    ticker: str,
    df_slice: pd.DataFrame,
    spy_slice: pd.DataFrame,
    setup_types: List[str],
) -> Optional[Dict]:
    """
    Run the appropriate signal engine(s) on a lookahead-safe slice.

    IMPORTANT: df_slice must be df.iloc[:T+1] — only data up to day T.
    This function never looks beyond the last row of df_slice.

    Parameters
    ----------
    ticker : str
    df_slice : DataFrame — data up to and including day T (df.iloc[:T+1])
    spy_slice : DataFrame — SPY data up to day T
    setup_types : list of "VCP" | "PULLBACK" | "BASE" | "RES_BREAKOUT"

    Returns
    -------
    First matching setup dict, or None.
    Each type is tried in order; first match wins.
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

        # Compute KDE zones (lookahead-safe: only uses df_slice)
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
                # trendline not computed during replay — ascending-TDL pullbacks will not fire
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

            elif stype == "RES_BREAKOUT":
                from engines.engine6 import scan_resistance_breakout
                setup = scan_resistance_breakout(ticker, df_slice, sr_zones)

            if setup is not None:
                return setup

    except Exception as exc:
        logger.debug("_detect_signals %s: %s", ticker, exc)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_data(ticker: str, start_date: str) -> tuple:
    """
    Fetch full ticker + SPY history needed for the backtest.

    Fetches from (start_date - WARMUP_BARS trading days) back in calendar time.
    Returns (ticker_df, spy_df). Either may be None on failure.
    """
    loop = asyncio.get_running_loop()

    start = date.fromisoformat(start_date)
    # 1.5x calendar days to ensure enough trading days (accounts for weekends/holidays)
    fetch_from = start - timedelta(days=int(WARMUP_BARS * 1.5))
    fetch_from_str = fetch_from.isoformat()

    def _download(sym: str) -> Optional[pd.DataFrame]:
        try:
            hist = yf.Ticker(sym).history(start=fetch_from_str, auto_adjust=False)
            if hist is None or hist.empty:
                return None
            hist.index = pd.to_datetime(hist.index).tz_localize(None)
            return hist
        except Exception as exc:
            logger.warning("_fetch_data: download failed for %s: %s", sym, exc)
            return None

    try:
        ticker_df, spy_df = await asyncio.gather(
            loop.run_in_executor(None, _download, ticker),
            loop.run_in_executor(None, _download, "SPY"),
        )
        return ticker_df, spy_df
    except Exception as exc:
        logger.warning("_fetch_data: gather failed for %s: %s", ticker, exc)
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Main engine
# ─────────────────────────────────────────────────────────────────────────────

class BacktestEngine:
    """
    Day-by-day historical replay backtester.

    Prevents lookahead bias by slicing the DataFrame at each step T so that
    signal engines only ever see data available up to and including day T.

    Trade lifecycle
    ---------------
    Signal on day T → entry executes at T+1 open price.
    Open trade managed daily: stop loss, take profit, trailing stop ratchet.
    Any trade still open at end_date is closed at that day's close price.
    """

    def __init__(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        setup_types: Optional[List[str]] = None,
        run_id: Optional[str] = None,
    ):
        self.ticker      = ticker.upper()
        self.start_date  = start_date
        self.end_date    = end_date
        self.setup_types = setup_types or ["VCP", "PULLBACK", "BASE"]
        self.run_id      = run_id or str(uuid.uuid4())

    async def run(self) -> BacktestSummary:
        """Execute the backtest. Returns a BacktestSummary with all closed trades."""
        run_id = self.run_id
        logger.info(
            "Backtest [%s] %s %s→%s starting",
            run_id, self.ticker, self.start_date, self.end_date,
        )

        # ── 1. Fetch data ─────────────────────────────────────────────────
        ticker_df, spy_df = await _fetch_data(self.ticker, self.start_date)
        if ticker_df is None or spy_df is None:
            logger.warning("Backtest: data fetch failed for %s", self.ticker)
            return compute_metrics(
                self.ticker, "+".join(self.setup_types),
                self.start_date, self.end_date, [], run_id,
            )

        # ── 2. Identify replay window ─────────────────────────────────────
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

        # ── 3. Pre-compute EMA20 series for trailing stop management ──────
        adj_col    = "Adj Close" if "Adj Close" in ticker_df.columns else "Close"
        ema20_full = _ema(ticker_df[adj_col], EMA_LONG)

        # ── 4. Replay loop ────────────────────────────────────────────────
        completed_trades: List[TradeRecord] = []
        open_trade: Optional[Dict]          = None   # in-flight trade state

        for T_date in replay_dates:
            full_idx = all_dates.get_loc(T_date)

            # ── 4a. Manage open trade ─────────────────────────────────────
            if open_trade is not None:
                ema20_T = float(ema20_full.iloc[full_idx])
                bar = {
                    "date":  T_date.strftime("%Y-%m-%d"),
                    "open":  float(ticker_df["Open"].iloc[full_idx]),
                    "high":  float(ticker_df["High"].iloc[full_idx]),
                    "low":   float(ticker_df["Low"].iloc[full_idx]),
                    "close": float(ticker_df[adj_col].iloc[full_idx]),
                    "ema20": ema20_T if not np.isnan(ema20_T) else open_trade["trailing_stop"],
                }
                closed, exit_price, exit_reason = _manage_open_trade(open_trade, bar)

                if closed:
                    entry_dt     = pd.Timestamp(open_trade["entry_date"])
                    holding_days = max(1, (T_date - entry_dt).days)
                    completed_trades.append(TradeRecord(
                        ticker=self.ticker,
                        setup_type=open_trade["setup_type"],
                        signal_date=open_trade["signal_date"],
                        entry_date=open_trade["entry_date"],
                        entry_price=open_trade["entry_price"],
                        initial_stop=open_trade["initial_stop"],
                        take_profit=open_trade["take_profit"],
                        exit_date=T_date.strftime("%Y-%m-%d"),
                        exit_price=exit_price,
                        exit_reason=exit_reason,
                        holding_days=holding_days,
                    ))
                    open_trade = None

                # Skip signal detection while a trade is open
                continue

            # ── 4b. Signal detection on lookahead-safe slice ──────────────
            df_slice  = ticker_df.iloc[:full_idx + 1]
            spy_slice = spy_df.loc[spy_df.index <= T_date]

            signal = _detect_signals(self.ticker, df_slice, spy_slice, self.setup_types)
            if signal is None:
                continue

            # ── 4c. Schedule entry on T+1 ─────────────────────────────────
            next_idx = full_idx + 1
            if next_idx >= len(all_dates):
                continue  # no next bar available — end of data

            next_date   = all_dates[next_idx]
            entry_price = float(ticker_df["Open"].iloc[next_idx])  # T+1 open

            stop_loss   = signal.get("stop_loss", 0.0)
            take_profit = signal.get("take_profit", 0.0)

            # Guard: entry must be above stop, and target must be above entry
            if stop_loss <= 0 or stop_loss >= entry_price:
                continue
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
            last_date    = replay_dates[-1]
            last_full_idx = all_dates.get_loc(last_date)
            exit_price   = float(ticker_df[adj_col].iloc[last_full_idx])
            entry_dt     = pd.Timestamp(open_trade["entry_date"])
            holding_days = max(1, (last_date - entry_dt).days)
            completed_trades.append(TradeRecord(
                ticker=self.ticker,
                setup_type=open_trade["setup_type"],
                signal_date=open_trade["signal_date"],
                entry_date=open_trade["entry_date"],
                entry_price=open_trade["entry_price"],
                initial_stop=open_trade["initial_stop"],
                take_profit=open_trade["take_profit"],
                exit_date=last_date.strftime("%Y-%m-%d"),
                exit_price=exit_price,
                exit_reason="EOD",
                holding_days=holding_days,
            ))

        # ── 6. Compute and return metrics ─────────────────────────────────
        setup_label = "+".join(self.setup_types)
        logger.info(
            "Backtest [%s] done: %d trades, win rate %.1f%%",
            run_id, len(completed_trades),
            (sum(1 for t in completed_trades if t.is_win) / len(completed_trades) * 100)
            if completed_trades else 0.0,
        )
        return compute_metrics(
            self.ticker, setup_label, self.start_date, self.end_date,
            completed_trades, run_id,
        )
