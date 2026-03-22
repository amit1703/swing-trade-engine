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
import filters as _filters
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
# Portfolio runner — full implementation
# ─────────────────────────────────────────────────────────────────────────────

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
    # Soft failure: if SPY is unavailable, pass None to prepare() and build
    # regime series from whichever spy_df is embedded in the first TickerSimState.
    try:
        _, spy_df = await _fetch_data("SPY", config.start_date)
    except Exception as exc:
        logger.warning("run_portfolio_backtest_universe: SPY fetch error: %s", exc)
        spy_df = None

    # ── Phase 1b: Prepare all tickers concurrently ────────────────────────
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

    # ── Phase 1c: Regime label series from SPY ────────────────────────────
    # If the direct SPY fetch succeeded, use it. Otherwise fall back to the
    # spy_df embedded in the first TickerSimState (always present after prepare()).
    # Use _filters module reference so tests can monkeypatch filters.compute_regime_label_series.
    _spy_for_regime = spy_df if spy_df is not None else ticker_states[0].spy_df
    regime_label_s: pd.Series = (
        _filters.compute_regime_label_series(_spy_for_regime)
        if _spy_for_regime is not None and len(_spy_for_regime) > 0
        else pd.Series(dtype=object)
    )

    # ── Phase 2: Reset mutable state ──────────────────────────────────────
    for ts in ticker_states:
        ts.is_in_trade     = False
        ts.last_close_date = None

    # ── Phase 2: Build union trading calendar ─────────────────────────────
    start_ts = pd.Timestamp(config.start_date)
    end_ts   = pd.Timestamp(config.end_date)
    all_union = sorted(set().union(*[set(ts.ticker_dates) for ts in ticker_states]))
    replay_dates = [d for d in all_union if start_ts <= d <= end_ts]
    total_dates  = len(replay_dates)

    # Signal start of Phase 2 so callers can update progress displays
    if progress_cb is not None:
        await progress_cb(0, total_dates)

    open_positions: List[dict]   = []
    completed_trades: List[dict] = []

    for _day_idx, T_date in enumerate(replay_dates):
        # Yield to event loop every 50 dates so the server stays responsive
        if _day_idx % 50 == 0:
            await asyncio.sleep(0)
            if progress_cb is not None:
                await progress_cb(_day_idx, total_dates)

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
                # Apply SELECTIVE hard filter in legacy mode too
                if current_regime == "SELECTIVE" and SELECTIVE_HARD_FILTER and SELECTIVE_SETUP_WEIGHTS:
                    setup_type_sig = signal.get("setup_type", "")
                    if SELECTIVE_SETUP_WEIGHTS.get(setup_type_sig, 1.0) == 0.0:
                        continue

            score = signal.get("_final_score", 0.0)
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
