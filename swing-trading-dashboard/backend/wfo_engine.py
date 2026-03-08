"""
wfo_engine.py — Walk-Forward Optimization engine.

Rolls IS/OOS windows over cached price data, runs BacktestEngine for each
window/ticker combination, and aggregates trade-level metrics.

Entry point: run_wfo(tickers, setup_types, is_months, oos_months, ...)

Performance design:
  - Price data loaded once from Parquet cache per run (not per window).
  - Each BacktestEngine call receives a pre-sliced DF bounded to
    [warmup_bars before window_start : window_end] — not the full 10-year DF.
    This caps df_slice growth to ~700 bars vs 2500+ for later windows.
  - All ticker+period pairs per window run in parallel via ThreadPoolExecutor,
    bypassing the GIL for pandas/numpy-heavy BacktestEngine replay loops.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from backtest_engine import BacktestEngine, TradeRecord, WARMUP_BARS
from wfo_cache import load_ticker, cache_exists
from indicators import ema as _ema, sma as _sma, atr as _atr, cci as _cci

logger = logging.getLogger(__name__)

# Max concurrent BacktestEngine threads per window (IS + OOS pairs).
# Each thread is CPU-bound; match to logical core count - 1.
_WFO_MAX_WORKERS = min(12, (os.cpu_count() or 4))


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WFOMetrics:
    """Aggregate metrics for one IS or OOS period."""
    trades:         int
    win_rate:       float   # %
    avg_r:          float   # mean R-multiple
    median_r:       float   # median R-multiple
    expectancy:     float   # (wr × avg_win_r) − (lr × avg_loss_r_abs)
    profit_factor:  float   # gross_profit / abs(gross_loss); inf if no losses
    net_profit_pct: float   # sum of pnl_pct across all trades
    reliable:       bool    # True when trades >= min_trades

    def to_dict(self) -> dict:
        return {
            "trades":         self.trades,
            "win_rate":       round(self.win_rate, 2),
            "avg_r":          round(self.avg_r, 3),
            "median_r":       round(self.median_r, 3),
            "expectancy":     round(self.expectancy, 3),
            "profit_factor":  round(min(self.profit_factor, 9999.0), 3),
            "net_profit_pct": round(self.net_profit_pct, 2),
            "reliable":       self.reliable,
        }


@dataclass
class WFOWindowResult:
    """Results for one rolling window."""
    window_num:      int
    is_start:        str
    is_end:          str
    oos_start:       str
    oos_end:         str
    is_metrics:      WFOMetrics
    oos_metrics:     WFOMetrics
    stability_score: float               # OOS_expectancy / IS_expectancy
    per_setup:       Dict[str, dict]     # {setup_type: {"is": dict, "oos": dict}}
    is_trades:       List[dict]          # raw trade records (IS)
    oos_trades:      List[dict]          # raw trade records (OOS)

    def to_dict(self) -> dict:
        return {
            "window_num":      self.window_num,
            "is_start":        self.is_start,
            "is_end":          self.is_end,
            "oos_start":       self.oos_start,
            "oos_end":         self.oos_end,
            "is_metrics":      self.is_metrics.to_dict(),
            "oos_metrics":     self.oos_metrics.to_dict(),
            "stability_score": round(self.stability_score, 3),
            "per_setup":       self.per_setup,
            "is_trades":       self.is_trades,
            "oos_trades":      self.oos_trades,
        }


@dataclass
class WFOResult:
    """Full walk-forward result for one run."""
    run_id:      str
    tickers:     List[str]
    setup_types: List[str]
    is_months:   int
    oos_months:  int
    step_months: int
    min_trades:  int
    created_at:  str
    windows:     List[WFOWindowResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id":      self.run_id,
            "tickers":     self.tickers,
            "setup_types": self.setup_types,
            "is_months":   self.is_months,
            "oos_months":  self.oos_months,
            "step_months": self.step_months,
            "min_trades":  self.min_trades,
            "created_at":  self.created_at,
            "windows":     [w.to_dict() for w in self.windows],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Window generation
# ─────────────────────────────────────────────────────────────────────────────

def _generate_windows(
    start: pd.Timestamp,
    end:   pd.Timestamp,
    is_months:   int,
    oos_months:  int,
    step_months: int,
) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """
    Generate rolling (is_start, is_end, oos_start, oos_end) window tuples.

    IS and OOS windows are non-overlapping. Steps forward by step_months each
    iteration. Stops when oos_end would exceed the available data end date.
    """
    windows = []
    is_start = start
    while True:
        is_end    = is_start + pd.DateOffset(months=is_months)
        oos_start = is_end
        oos_end   = oos_start + pd.DateOffset(months=oos_months)
        if oos_end > end:
            break
        windows.append((is_start, is_end, oos_start, oos_end))
        is_start = is_start + pd.DateOffset(months=step_months)
    return windows


# ─────────────────────────────────────────────────────────────────────────────
# DF slicing helper
# ─────────────────────────────────────────────────────────────────────────────

def _slice_df_for_window(
    df:           pd.DataFrame,
    window_start: pd.Timestamp,
    window_end:   pd.Timestamp,
    warmup_bars:  int = WARMUP_BARS,
) -> pd.DataFrame:
    """
    Return a bounded slice of df covering warmup_bars before window_start
    through window_end.

    This keeps BacktestEngine's df_slice growth bounded to
    warmup_bars + window_bars instead of growing across the full 10-year DF.
    Critically, this limits the dataset fed into KDE and indicator functions
    on each replay bar.
    """
    start_pos  = df.index.searchsorted(window_start)
    slice_from = max(0, start_pos - warmup_bars)
    end_pos    = df.index.searchsorted(window_end, side="right")
    return df.iloc[slice_from:end_pos]


# ─────────────────────────────────────────────────────────────────────────────
# Sync wrapper for thread executor
# ─────────────────────────────────────────────────────────────────────────────

def _run_backtest_sync(
    ticker:      str,
    start_date:  str,
    end_date:    str,
    setup_types: List[str],
    ticker_df:   pd.DataFrame,
    spy_df:      pd.DataFrame,
) -> object:
    """
    Synchronous wrapper around BacktestEngine for ThreadPoolExecutor use.

    BacktestEngine.run() is async but contains no real await-yield points
    in its replay loop. Running it in a dedicated thread event loop allows
    multiple tickers to execute truly concurrently (pandas/numpy release
    the GIL during many operations).
    """
    loop = asyncio.new_event_loop()
    try:
        engine = BacktestEngine(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            setup_types=setup_types,
            ticker_df=ticker_df,
            spy_df=spy_df,
        )
        return loop.run_until_complete(engine.run())
    finally:
        loop.close()


# ─────────────────────────────────────────────────────────────────────────────
# Metrics computation
# ─────────────────────────────────────────────────────────────────────────────

def _compute_wfo_metrics(trades: List[TradeRecord], min_trades: int) -> WFOMetrics:
    """
    Compute WFO-specific aggregate metrics from a list of TradeRecord objects.

    Expectancy = (win_rate_frac × avg_win_r) − (loss_rate_frac × avg_loss_r_abs)
    where avg_loss_r_abs is the magnitude of average loss R.
    """
    n = len(trades)
    if n == 0:
        return WFOMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, False)

    wins   = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]

    win_rate  = len(wins) / n * 100

    all_r    = [t.rr_achieved for t in trades]
    avg_r    = float(np.mean(all_r))
    median_r = float(np.median(all_r))

    avg_win_r      = float(np.mean([t.rr_achieved for t in wins]))          if wins   else 0.0
    avg_loss_r_abs = float(np.mean([abs(t.rr_achieved) for t in losses]))  if losses else 0.0

    win_rate_frac  = len(wins)   / n
    loss_rate_frac = len(losses) / n
    expectancy = (win_rate_frac * avg_win_r) - (loss_rate_frac * avg_loss_r_abs)

    gross_profit   = sum(t.pnl_pct for t in wins)
    gross_loss     = abs(sum(t.pnl_pct for t in losses))
    profit_factor  = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    net_profit_pct = sum(t.pnl_pct for t in trades)

    return WFOMetrics(
        trades=n,
        win_rate=win_rate,
        avg_r=avg_r,
        median_r=median_r,
        expectancy=expectancy,
        profit_factor=profit_factor,
        net_profit_pct=net_profit_pct,
        reliable=n >= min_trades,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

async def run_wfo(
    tickers:     List[str],
    setup_types: List[str],
    is_months:   int  = 24,
    oos_months:  int  = 3,
    step_months: int  = 3,
    min_trades:  int  = 20,
    run_id:      Optional[str]  = None,
    progress:    Optional[dict] = None,
) -> WFOResult:
    """
    Run walk-forward optimization across rolling IS/OOS windows.

    Parameters
    ----------
    tickers     : list of ticker symbols (must be cached — see wfo_cache.py)
    setup_types : list of setup type strings (VCP, PULLBACK, etc.)
    is_months   : in-sample window length in months
    oos_months  : out-of-sample window length in months
    step_months : step size between windows in months
    min_trades  : minimum trades for a window to be marked reliable
    run_id      : optional run identifier (auto-generated if None)
    progress    : optional mutable dict for status polling:
                    {"windows_completed": 0, "total_windows": N}

    Returns
    -------
    WFOResult with all windows populated.
    """
    run_id     = run_id or str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()

    # ── 1. Load all cached DataFrames ONCE upfront ────────────────────────────
    loaded_dfs: Dict[str, pd.DataFrame] = {}
    spy_df: Optional[pd.DataFrame] = None

    for ticker in tickers:
        if not cache_exists(ticker):
            logger.warning("wfo: no cache for %s — skipping", ticker)
            continue
        df = load_ticker(ticker)
        if df is None:
            continue
        if ticker == "SPY":
            spy_df = df
        loaded_dfs[ticker] = df

    if spy_df is None and "SPY" in loaded_dfs:
        spy_df = loaded_dfs["SPY"]

    # ── 1b. Pre-compute indicator columns on each full DF (once per ticker) ──
    # BacktestEngine.run() checks for _EMA8 and skips recomputation when found.
    # Slices from _slice_df_for_window inherit these columns, so all 31 windows
    # share the same pre-computed series rather than recomputing per window.
    for ticker, df in loaded_dfs.items():
        if ticker == "SPY" or "_EMA8" in df.columns:
            continue
        _adj = "Adj Close" if "Adj Close" in df.columns else "Close"
        _c = df[_adj]
        _h = df["High"]
        _l = df["Low"]
        df["_EMA8"]    = _ema(_c, 8)
        df["_EMA20"]   = _ema(_c, 20)
        df["_SMA50"]   = _sma(_c, 50)
        df["_SMA200"]  = _sma(_c, 200)
        df["_ATR14"]   = _atr(_h, _l, _c, 14)
        df["_CCI20"]   = _cci(_h, _l, _c, 20)
        if "Volume" in df.columns:
            df["_VOLSMA50"] = df["Volume"].rolling(50, min_periods=10).mean()

    if spy_df is None:
        logger.warning("wfo: SPY cache missing — RS signals will be degraded")
        if loaded_dfs:
            spy_df = next(iter(loaded_dfs.values())).copy()
        else:
            return WFOResult(
                run_id=run_id, tickers=tickers, setup_types=setup_types,
                is_months=is_months, oos_months=oos_months, step_months=step_months,
                min_trades=min_trades, created_at=created_at, windows=[],
            )

    # ── 2. Determine date range from available data ────────────────────────────
    non_spy = {t: df for t, df in loaded_dfs.items() if t != "SPY"}
    if not non_spy:
        return WFOResult(
            run_id=run_id, tickers=tickers, setup_types=setup_types,
            is_months=is_months, oos_months=oos_months, step_months=step_months,
            min_trades=min_trades, created_at=created_at, windows=[],
        )

    data_start = max(df.index.min() for df in non_spy.values())
    data_end   = min(df.index.max() for df in non_spy.values())

    windows = _generate_windows(data_start, data_end, is_months, oos_months, step_months)

    if progress is not None:
        progress["total_windows"]     = len(windows)
        progress["windows_completed"] = 0

    logger.info(
        "wfo [%s]: %d tickers, %d windows, %d max workers",
        run_id, len(non_spy), len(windows), _WFO_MAX_WORKERS,
    )

    # ── 3. Per-window loop (tickers run in parallel per window) ───────────────
    result_windows: List[WFOWindowResult] = []
    loop = asyncio.get_event_loop()

    with ThreadPoolExecutor(max_workers=_WFO_MAX_WORKERS) as executor:
        for window_num, (is_start, is_end, oos_start, oos_end) in enumerate(windows, 1):
            is_start_str  = is_start.strftime("%Y-%m-%d")
            is_end_str    = is_end.strftime("%Y-%m-%d")
            oos_start_str = oos_start.strftime("%Y-%m-%d")
            oos_end_str   = oos_end.strftime("%Y-%m-%d")

            # Build all IS+OOS tasks for this window — each ticker gets a
            # pre-sliced DF bounded to warmup + window, NOT the full 10-year DF.
            tasks_meta = []  # (ticker, "IS"|"OOS") for result mapping
            futures    = []

            for ticker, ticker_df in non_spy.items():
                # IS period slice: warmup_bars before is_start → is_end
                tdf_is  = _slice_df_for_window(ticker_df, is_start, is_end)
                sdf_is  = _slice_df_for_window(spy_df,    is_start, is_end)

                # OOS period slice: warmup_bars before oos_start → oos_end
                tdf_oos = _slice_df_for_window(ticker_df, oos_start, oos_end)
                sdf_oos = _slice_df_for_window(spy_df,    oos_start, oos_end)

                futures.append(loop.run_in_executor(
                    executor, _run_backtest_sync,
                    ticker, is_start_str, is_end_str, setup_types, tdf_is, sdf_is,
                ))
                tasks_meta.append((ticker, "IS"))

                futures.append(loop.run_in_executor(
                    executor, _run_backtest_sync,
                    ticker, oos_start_str, oos_end_str, setup_types, tdf_oos, sdf_oos,
                ))
                tasks_meta.append((ticker, "OOS"))

            summaries = await asyncio.gather(*futures)

            # Collect trades from all parallel results
            is_trades_all:  List[TradeRecord] = []
            oos_trades_all: List[TradeRecord] = []

            for (ticker, period), summary in zip(tasks_meta, summaries):
                if period == "IS":
                    is_trades_all.extend(summary.trades)
                else:
                    oos_trades_all.extend(summary.trades)

            # ── Compute aggregate metrics ──────────────────────────────────
            is_metrics  = _compute_wfo_metrics(is_trades_all,  min_trades)
            oos_metrics = _compute_wfo_metrics(oos_trades_all, min_trades)

            is_exp  = is_metrics.expectancy
            oos_exp = oos_metrics.expectancy
            stability_score = round(oos_exp / is_exp, 3) if is_exp > 0 else 0.0

            # ── Per-setup breakdown ────────────────────────────────────────
            per_setup: Dict[str, dict] = {}
            for stype in setup_types:
                is_st  = [t for t in is_trades_all  if t.setup_type == stype]
                oos_st = [t for t in oos_trades_all if t.setup_type == stype]
                per_setup[stype] = {
                    "is":  _compute_wfo_metrics(is_st,  min_trades).to_dict(),
                    "oos": _compute_wfo_metrics(oos_st, min_trades).to_dict(),
                }

            result_windows.append(WFOWindowResult(
                window_num=window_num,
                is_start=is_start_str,
                is_end=is_end_str,
                oos_start=oos_start_str,
                oos_end=oos_end_str,
                is_metrics=is_metrics,
                oos_metrics=oos_metrics,
                stability_score=stability_score,
                per_setup=per_setup,
                is_trades=[t.to_dict() for t in is_trades_all],
                oos_trades=[t.to_dict() for t in oos_trades_all],
            ))

            if progress is not None:
                progress["windows_completed"] = window_num

            logger.info(
                "wfo [%s] window %d/%d: IS %d trades, OOS %d trades, stability=%.2f",
                run_id, window_num, len(windows),
                len(is_trades_all), len(oos_trades_all), stability_score,
            )

    return WFOResult(
        run_id=run_id,
        tickers=tickers,
        setup_types=setup_types,
        is_months=is_months,
        oos_months=oos_months,
        step_months=step_months,
        min_trades=min_trades,
        created_at=created_at,
        windows=result_windows,
    )
