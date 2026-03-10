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
        setup_types=["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"],
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
from constants import (
    RS_BLUE_DOT_TOLERANCE_PCT,
    RISK_PER_TRADE_PCT,
    MAX_POSITION_SIZE_PCT,
    MAX_OPEN_POSITIONS,
)
import constants as _constants  # used by _manage_open_trade for TRAIL_ATR_MULT (patchable)

# V5: per-setup ATR trail multipliers.
# Task 3 will apply the same logic to _enrich_trade() in main.py (live portfolio).
_TRAIL_ATR_BY_SETUP = {
    "VCP":          lambda: _constants.VCP_TRAIL_ATR_MULT,
    "PULLBACK":     lambda: _constants.PULLBACK_TRAIL_ATR_MULT,
    "RES_BREAKOUT": lambda: _constants.RES_BREAKOUT_TRAIL_ATR_MULT,
    "BASE":         lambda: _constants.BASE_TRAIL_ATR_MULT,
}

from filters import compute_regime_series, passes_liquidity, in_earnings_blackout
from indicators import ema as _ema, sma as _sma, atr as _atr, cci as _cci

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
    rr_achieved:       float = field(init=False)
    pnl_pct:           float = field(init=False)
    portfolio_pnl_pct: float = field(init=False)  # position-sized portfolio impact (1% risk model)
    is_win:            bool  = field(init=False)

    def __post_init__(self):
        risk = self.entry_price - self.initial_stop
        if risk > 0:
            self.rr_achieved = round((self.exit_price - self.entry_price) / risk, 3)
        else:
            self.rr_achieved = 0.0
        self.pnl_pct = round((self.exit_price - self.entry_price) / self.entry_price * 100, 3)
        self.is_win  = self.exit_price > self.entry_price

        # Position sizing: risk RISK_PER_TRADE_PCT% of equity, sized by stop distance.
        # position_size = risk_pct / stop_distance_pct, capped at MAX_POSITION_SIZE_PCT.
        # portfolio_pnl_pct = pnl_pct × position_size / 100
        stop_dist_pct = (self.entry_price - self.initial_stop) / self.entry_price
        if stop_dist_pct > 0:
            raw_pos = RISK_PER_TRADE_PCT / stop_dist_pct
            position_size_pct = min(raw_pos, MAX_POSITION_SIZE_PCT)
            self.portfolio_pnl_pct = round(self.pnl_pct * position_size_pct / 100.0, 4)
        else:
            self.portfolio_pnl_pct = 0.0

    def to_dict(self) -> Dict:
        return {
            "ticker":            self.ticker,
            "setup_type":        self.setup_type,
            "signal_date":       self.signal_date,
            "entry_date":        self.entry_date,
            "entry_price":       self.entry_price,
            "initial_stop":      self.initial_stop,
            "take_profit":       self.take_profit,
            "exit_date":         self.exit_date,
            "exit_price":        self.exit_price,
            "exit_reason":       self.exit_reason,
            "holding_days":      self.holding_days,
            "rr_achieved":       self.rr_achieved,
            "pnl_pct":           self.pnl_pct,
            "portfolio_pnl_pct": self.portfolio_pnl_pct,
            "is_win":            self.is_win,
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

    # Use portfolio_pnl_pct (position-sized) for all portfolio metrics.
    # pnl_pct (raw price return) is preserved on TradeRecord for reference only.
    gross_profit   = sum(t.portfolio_pnl_pct for t in wins)
    gross_loss     = sum(t.portfolio_pnl_pct for t in losses)  # negative number
    net_profit_pct = round(gross_profit + gross_loss, 3)

    if gross_loss == 0:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    else:
        profit_factor = round(gross_profit / abs(gross_loss), 3)

    avg_holding_days = round(float(np.mean([t.holding_days for t in trades])), 1)

    # Compound equity curve using portfolio_pnl_pct (position-sized returns).
    # Each trade risks at most RISK_PER_TRADE_PCT% of equity, so the equity
    # curve reflects realistic portfolio drawdown rather than raw price swings.
    equity   = 1.0
    peak     = 1.0
    max_dd   = 0.0
    for t in trades:
        equity *= (1.0 + t.portfolio_pnl_pct / 100.0)
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
        entry_price, trailing_stop, take_profit, entry_date,
        setup_type (optional) — used to select the ATR trail multiplier;
        defaults to TRAIL_ATR_MULT fallback if absent or unrecognised
    bar : dict with keys:
        date, open, high, low, close, ema20, atr14

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

    # 3. Update trailing stop: ratchet to max(EMA20, ATR-based trail) when in profit
    if close > entry:
        atr14 = bar.get("atr14", 0.0)
        setup_type = state.get("setup_type", "")
        mult_fn = _TRAIL_ATR_BY_SETUP.get(setup_type)
        mult = mult_fn() if mult_fn else _constants.TRAIL_ATR_MULT
        atr_trail = (close - mult * atr14) if atr14 > 0 else ema20
        new_trail = max(ema20, atr_trail)
        if new_trail > stop:
            state["trailing_stop"] = new_trail

    return False, None, None


# ─────────────────────────────────────────────────────────────────────────────
# Signal detection (lookahead-safe)
# ─────────────────────────────────────────────────────────────────────────────

def _detect_signals(
    ticker: str,
    df_slice: pd.DataFrame,
    spy_slice: pd.DataFrame,
    setup_types: List[str],
    sr_zones: Optional[List] = None,
    precomputed_rs: Optional[Dict] = None,
) -> Optional[Dict]:
    """
    Run the appropriate signal engine(s) on a lookahead-safe slice.

    IMPORTANT: df_slice must be df.iloc[:T+1] — only data up to day T.
    This function never looks beyond the last row of df_slice.

    Parameters
    ----------
    ticker : str
    df_slice : DataFrame — data up to and including day T (df.iloc[:T+1]).
               May contain pre-computed indicator columns (_EMA8, _EMA20,
               _SMA50, _SMA200, _ATR14, _CCI20, _VOLSMA50) that engines will
               use instead of recomputing from scratch.
    spy_slice : DataFrame — SPY data up to day T
    setup_types : list of "VCP" | "PULLBACK" | "BASE" | "RES_BREAKOUT" | "HTF" | "LCE"
    sr_zones : pre-computed KDE zones (optional). If None, zones are computed
               from df_slice on every call (expensive — avoid in tight loops).
    precomputed_rs : dict with keys rs_ratio, rs_52w_high, rs_blue_dot,
                     rs_score, spy_3m — pre-computed once per BacktestEngine run.
                     When supplied, skips compute_indicators entirely.

    Returns
    -------
    First matching setup dict, or None.
    Each type is tried in order; first match wins.
    """
    if len(df_slice) < MIN_BARS_FOR_SIGNAL:
        return None

    try:
        # ── RS scalars: use pre-computed rolling values when available ────
        if precomputed_rs is not None:
            rs_ratio    = precomputed_rs["rs_ratio"]
            rs_52w_high = precomputed_rs["rs_52w_high"]
            rs_blue_dot = precomputed_rs["rs_blue_dot"]
            rs_score    = precomputed_rs["rs_score"]
            spy_3m_return = precomputed_rs["spy_3m"]
        else:
            from indicators.indicator_engine import compute_indicators
            inds = compute_indicators(df_slice, spy_slice)
            if inds is None:
                return None
            rs_ratio    = inds.rs_ratio
            rs_52w_high = inds.rs_52w_high
            rs_blue_dot = inds.rs_blue_dot
            rs_score    = inds.rs_score

            spy_adj = "Adj Close" if "Adj Close" in spy_slice.columns else "Close"
            n_spy = len(spy_slice)
            spy_3m_return = 0.0
            if n_spy > 63:
                spy_vals = spy_slice[spy_adj].values
                spy_3m_return = float(spy_vals[-1] / spy_vals[-64] - 1.0)

        # KDE zones: use caller-supplied cache when available (avoids per-bar KDE cost)
        if sr_zones is None:
            from engines.engine1 import calculate_sr_zones
            sr_zones = calculate_sr_zones(ticker, df_slice)

        for stype in setup_types:
            setup = None

            if stype == "VCP":
                from engines.engine2 import scan_vcp
                setup = scan_vcp(
                    ticker, df_slice, sr_zones,
                    spy_3m_return=spy_3m_return,
                    rs_ratio=rs_ratio,
                    rs_52w_high=rs_52w_high,
                    rs_blue_dot=rs_blue_dot,
                    rs_score=rs_score,
                )

            elif stype == "PULLBACK":
                from engines.engine3 import scan_pullback, scan_relaxed_pullback
                # trendline not computed during replay — ascending-TDL pullbacks will not fire
                setup = scan_pullback(ticker, df_slice, sr_zones, rs_score=rs_score)
                if setup is None:
                    setup = scan_relaxed_pullback(ticker, df_slice, sr_zones, rs_score=rs_score)

            elif stype == "BASE":
                from engines.engine5 import scan_base_pattern
                setup = scan_base_pattern(
                    ticker, df_slice,
                    spy_3m_return=spy_3m_return,
                    rs_ratio=rs_ratio,
                    rs_52w_high=rs_52w_high,
                    rs_blue_dot=rs_blue_dot,
                    rs_score=rs_score,
                    sr_zones=sr_zones,
                )

            elif stype == "RES_BREAKOUT":
                from engines.engine6 import scan_resistance_breakout
                setup = scan_resistance_breakout(ticker, df_slice, sr_zones)

            elif stype == "HTF":
                from engines.engine8_htf import scan_htf
                setup = scan_htf(ticker, df_slice, sr_zones)

            elif stype == "LCE":
                from engines.engine9_low_cheat import scan_lce
                setup = scan_lce(ticker, df_slice, sr_zones)

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
        ticker_df: Optional[pd.DataFrame] = None,
        spy_df: Optional[pd.DataFrame] = None,
        earnings_dates: Optional[Dict[str, List[str]]] = None,
    ):
        self.ticker      = ticker.upper()
        self.start_date  = start_date
        self.end_date    = end_date
        self.setup_types = setup_types or ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"]
        self.run_id      = run_id or str(uuid.uuid4())
        self.ticker_df   = ticker_df
        self.spy_df      = spy_df
        self.earnings_dates: Dict[str, List[str]] = earnings_dates or {}

    async def run(self) -> BacktestSummary:
        """Execute the backtest. Returns a BacktestSummary with all closed trades."""
        run_id = self.run_id
        logger.info(
            "Backtest [%s] %s %s→%s starting",
            run_id, self.ticker, self.start_date, self.end_date,
        )

        # ── 1. Fetch data (or use preloaded df for WFO) ───────────────────
        if self.ticker_df is not None and self.spy_df is not None:
            ticker_df = self.ticker_df
            spy_df    = self.spy_df
        else:
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

        # ── 3. Price column identification ─────────────────────────────────
        adj_col = "Adj Close" if "Adj Close" in ticker_df.columns else "Close"

        # ── 3b. Pre-compute SR zones ONCE for the entire window ───────────
        # NOTE: This uses the full ticker_df (all bars in the IS/OOS slice),
        # not a per-bar df_slice. This is an intentional performance trade-off:
        # zones are structural price levels derived from the full window.
        # In live scanning the optimizer also sees future structure — this
        # matches the real deployment context. The bias is accepted consciously
        # to make WFO optimization computationally feasible.
        from engines.engine1 import calculate_sr_zones as _calc_sr_zones
        _sr_zones_cache: Optional[List] = _calc_sr_zones(self.ticker, ticker_df)

        # ── 3c. Pre-compute indicator columns on ticker_df ────────────────
        # When called from WFO, wfo_engine.py pre-computes these on the full
        # DF; slices inherit the columns, so we skip the copy+compute here.
        # For standalone backtests, compute now on a copy to avoid mutation.
        if "_EMA8" not in ticker_df.columns:
            ticker_df = ticker_df.copy()   # don't mutate caller's DF
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

        _close_s  = ticker_df[adj_col]
        ema20_full = ticker_df["_EMA20"]   # reuse pre-computed column

        # ── 3d. Pre-compute RS rolling series (O(1) per-bar lookup) ──────
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

        # SPY 63-day return series (used by VCP RS gate)
        _spy_3m_s = (_spy_aligned / _spy_aligned.shift(63) - 1.0).fillna(0.0)

        # ── 4. Replay loop ────────────────────────────────────────────────
        completed_trades: List[TradeRecord] = []
        open_trades: List[Dict]             = []   # up to MAX_OPEN_POSITIONS concurrent

        # Pre-compute regime series from SPY data (empty Series if no spy_df)
        _regime_series: pd.Series = pd.Series(dtype=bool)
        if self.spy_df is not None and len(self.spy_df) > 0:
            _regime_series = compute_regime_series(self.spy_df)

        for T_date in replay_dates:
            full_idx = all_dates.get_loc(T_date)

            # ── 4a. Manage all open trades ────────────────────────────────
            if open_trades:
                ema20_T = float(ema20_full.iloc[full_idx])
                atr14_T = float(ticker_df["_ATR14"].iloc[full_idx]) \
                    if "_ATR14" in ticker_df.columns else 0.0
                bar = {
                    "date":  T_date.strftime("%Y-%m-%d"),
                    "open":  float(ticker_df["Open"].iloc[full_idx]),
                    "high":  float(ticker_df["High"].iloc[full_idx]),
                    "low":   float(ticker_df["Low"].iloc[full_idx]),
                    "close": float(ticker_df[adj_col].iloc[full_idx]),
                    "ema20": ema20_T if not np.isnan(ema20_T) else 0.0,
                    "atr14": atr14_T if not np.isnan(atr14_T) else 0.0,
                }
                still_open: List[Dict] = []
                for trade_state in open_trades:
                    closed, exit_price, exit_reason = _manage_open_trade(trade_state, bar)
                    if closed:
                        entry_dt     = pd.Timestamp(trade_state["entry_date"])
                        holding_days = max(1, (T_date - entry_dt).days)
                        completed_trades.append(TradeRecord(
                            ticker=self.ticker,
                            setup_type=trade_state["setup_type"],
                            signal_date=trade_state["signal_date"],
                            entry_date=trade_state["entry_date"],
                            entry_price=trade_state["entry_price"],
                            initial_stop=trade_state["initial_stop"],
                            take_profit=trade_state["take_profit"],
                            exit_date=T_date.strftime("%Y-%m-%d"),
                            exit_price=exit_price,
                            exit_reason=exit_reason,
                            holding_days=holding_days,
                        ))
                    else:
                        still_open.append(trade_state)
                open_trades = still_open

            # ── 4b. Signal detection — skip when at max concurrent positions
            if len(open_trades) >= MAX_OPEN_POSITIONS:
                continue

            # Regime gate: skip new signals if SPY is in a defensive regime
            if len(_regime_series) > 0:
                spy_dates_before = _regime_series.index[_regime_series.index <= T_date]
                if len(spy_dates_before) > 0:
                    is_bullish_bar = bool(_regime_series.loc[spy_dates_before[-1]])
                else:
                    is_bullish_bar = False
                if not is_bullish_bar:
                    continue

            df_slice  = ticker_df.iloc[:full_idx + 1]   # pre-computed cols included

            # Liquidity gate: skip signals when ticker lacks trading volume
            if not passes_liquidity(df_slice):
                continue

            # Earnings blackout gate: skip signals near earnings dates (optional)
            if self.earnings_dates:
                ticker_earnings = self.earnings_dates.get(self.ticker, [])
                bar_date_str = T_date.strftime("%Y-%m-%d")
                if in_earnings_blackout(bar_date_str, ticker_earnings):
                    continue

            spy_slice = spy_df.loc[spy_df.index <= T_date]

            # RS scalars for bar T — O(1) array index into pre-computed series
            _rs_t = {
                "rs_ratio":    float(_rs_ratio_s.iloc[full_idx]),
                "rs_52w_high": float(_rs_52wh_s.iloc[full_idx]),
                "rs_blue_dot": bool(_rs_ratio_s.iloc[full_idx] >= _rs_52wh_s.iloc[full_idx]
                                    * (1.0 - RS_BLUE_DOT_TOLERANCE_PCT)),
                "rs_score":    float(_rs_score_s.iloc[full_idx]),
                "spy_3m":      float(_spy_3m_s.iloc[full_idx]),
            }

            signal = _detect_signals(
                self.ticker, df_slice, spy_slice, self.setup_types,
                sr_zones=_sr_zones_cache,
                precomputed_rs=_rs_t,
            )
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

            open_trades.append({
                "setup_type":    signal.get("setup_type", self.setup_types[0]),
                "signal_date":   T_date.strftime("%Y-%m-%d"),
                "entry_date":    next_date.strftime("%Y-%m-%d"),
                "entry_price":   entry_price,
                "initial_stop":  stop_loss,
                "trailing_stop": stop_loss,
                "take_profit":   take_profit,
            })

        # ── 5. Close any still-open trades at end of period ───────────────
        if open_trades:
            last_date     = replay_dates[-1]
            last_full_idx = all_dates.get_loc(last_date)
            exit_price    = float(ticker_df[adj_col].iloc[last_full_idx])
            for trade_state in open_trades:
                entry_dt     = pd.Timestamp(trade_state["entry_date"])
                holding_days = max(1, (last_date - entry_dt).days)
                completed_trades.append(TradeRecord(
                    ticker=self.ticker,
                    setup_type=trade_state["setup_type"],
                    signal_date=trade_state["signal_date"],
                    entry_date=trade_state["entry_date"],
                    entry_price=trade_state["entry_price"],
                    initial_stop=trade_state["initial_stop"],
                    take_profit=trade_state["take_profit"],
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
