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
    SELECTIVE_SETUP_WEIGHTS,
    SELECTIVE_HARD_FILTER,
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

    Note: The SELECTIVE regime filter is NOT applied here — it is the caller's
    (run_portfolio_backtest_universe) responsibility.
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
            # PULLBACK present but no setup found — fall through to non-PB types
            non_pb = [s for s in setup_types if s not in ("PULLBACK", "VCP")]
            return _detect_signals(
                ts.ticker, df_slice, spy_slice, non_pb,
                sr_zones=ts.sr_zones_cache,
                precomputed_rs=rs_t,
                params=ts.params,
            ) if non_pb else None
        else:
            # Scored mode, no PULLBACK in setup_types
            non_vcp = [s for s in setup_types if s != "VCP"]
            return _detect_signals(
                ts.ticker, df_slice, spy_slice, non_vcp,
                sr_zones=ts.sr_zones_cache,
                precomputed_rs=rs_t,
                params=ts.params,
            ) if non_vcp else None
    else:
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
    Build the open-position dict used by the portfolio coordinator.

    Returns a position dict with two keys:
      - "ticker_state": the TickerSimState (used by advance/close logic in coordinator)
      - "trade_state": the flat state dict that _manage_open_trade() reads/mutates

    Callers must pass pos["trade_state"] to _manage_open_trade(), not pos.

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
