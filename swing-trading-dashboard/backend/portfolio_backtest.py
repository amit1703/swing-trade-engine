"""
Portfolio-coordinated backtest — live-scanner parity mode.

Replaces the per-ticker independent run_backtest_universe() with a global
portfolio cap: at most BacktestConfig.max_positions trades open at any time.
When a slot opens, the highest-scoring available signal fills it.

Signal quality gates mirror the live scanner exactly:
  1. RS rank gate          — cross-sectional O'Neil RS percentile ≥ RS_RANK_MIN_PERCENTILE
  2. Full 7-factor regime  — f1–f7 including breadth (from loaded tickers) and VIX
  3. compute_setup_score() — same 0-100 scoring function as the live scanner
  4. config.min_score gate — same 0-100 scale as MIN_SETUP_SCORE in live scanner

Public API
----------
run_portfolio_backtest_universe(tickers, config, params, progress_cb, sectors)
    -> List[dict]   (same TradeRecord.to_dict() format as run_backtest_universe)
"""
from __future__ import annotations

import asyncio
import bisect
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import constants as _constants
from constants import (
    CONCURRENCY_LIMIT,
    RS_BLUE_DOT_TOLERANCE_PCT,
    RS_RANK_MIN_PERCENTILE,
    SELECTIVE_SETUP_WEIGHTS,
    SELECTIVE_HARD_FILTER,
    REGIME_WEIGHT_BREADTH,
    REGIME_WEIGHT_HL,
    REGIME_WEIGHT_VIX,
    REGIME_AGGRESSIVE_THRESHOLD,
    REGIME_SELECTIVE_THRESHOLD,
    TOP_SECTORS_N,
)
import filters as _filters
from filters import (
    compute_regime_label_series,
    compute_regime_score_series,
    passes_liquidity,
)

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
    min_score:     float         = 0.0       # 0–100, same scale as live scanner MIN_SETUP_SCORE
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
    # ── Pre-computed caches (set once in _prepare_one / post-Phase-1, never mutated) ─
    date_to_idx:     dict           = field(default_factory=dict)   # Timestamp -> int (O(1) bar lookup)
    liquidity_ok:    Optional[pd.Series] = None                     # bool Series (vectorized liquidity)
    rs_rank_cache:   dict           = field(default_factory=dict)   # Timestamp -> float 0-100 (cross-sectional RS percentile)


# ─────────────────────────────────────────────────────────────────────────────
# Signal detection helper
# ─────────────────────────────────────────────────────────────────────────────

def _detect_signals_for_date(
    ts: TickerSimState,
    T_date: pd.Timestamp,
    full_idx: int,
    setup_types: List[str],
    regime: str = "",
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
                regime=regime,
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
            "_final_score":        signal.get("setup_score", signal.get("_final_score")),
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
# Live-scanner parity helpers (post-Phase-1 computation)
# ─────────────────────────────────────────────────────────────────────────────

def _build_adj_close_matrix(
    ticker_states: List[TickerSimState],
    spy_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    Build a (date × ticker) DataFrame of adj-close prices, aligned to spy_index.
    Missing values are forward-filled then left as NaN at the start.
    """
    close_dict: Dict[str, pd.Series] = {}
    for ts in ticker_states:
        col = ts.adj_col if ts.adj_col in ts.ticker_df.columns else "Close"
        close_dict[ts.ticker] = ts.ticker_df[col]
    df = pd.DataFrame(close_dict)
    return df.reindex(spy_index).ffill()


def _compute_rs_ranks_and_assign(
    ticker_states: List[TickerSimState],
    spy_df: pd.DataFrame,
) -> None:
    """
    Vectorized cross-sectional O'Neil RS rank computation.

    For each trading day, computes each ticker's O'Neil RS score relative to SPY,
    then cross-sectionally ranks all tickers (0-100 percentile).  Assigns
    ts.rs_rank_cache = {Timestamp: percentile} for every TickerSimState.

    Tickers with insufficient history for a period contribute 0 to that period's
    weight (handled by ffill + pct_change returning NaN for short histories).
    """
    spy_col = "Adj Close" if "Adj Close" in spy_df.columns else "Close"
    spy_close = spy_df[spy_col].dropna()
    if len(spy_close) < 63 or not ticker_states:
        return

    close_df = _build_adj_close_matrix(ticker_states, spy_close.index)

    # O'Neil RS score matrix: weighted sum of excess returns over SPY
    rs_matrix = pd.DataFrame(0.0, index=close_df.index, columns=close_df.columns)
    for period, weight in zip((63, 126, 189, 252), (0.40, 0.20, 0.20, 0.20)):
        tk_ret  = close_df.pct_change(period)
        spy_ret = spy_close.pct_change(period)
        excess  = tk_ret.sub(spy_ret, axis=0).fillna(0.0)
        rs_matrix += excess * weight

    # Cross-sectional percentile rank per date: rank(axis=1) gives a rank per row
    # pct=True normalises to [0, 1]; multiply by 100 → [0, 100]
    rs_rank_matrix = rs_matrix.rank(axis=1, pct=True, na_option="keep") * 100.0

    for ts in ticker_states:
        if ts.ticker in rs_rank_matrix.columns:
            series = rs_rank_matrix[ts.ticker].dropna()
            ts.rs_rank_cache = series.to_dict()


def _compute_full_regime_dicts(
    spy_df: pd.DataFrame,
    vix_df: Optional[pd.DataFrame],
    ticker_states: List[TickerSimState],
) -> Tuple[Dict, Dict]:
    """
    Compute full 7-factor regime score and label for each SPY trading day.

    f1–f4: SPY-only (EMA20, SMA50, MA stack, EMA slope) — via filters.py
    f5:    breadth (% of loaded tickers with close > 50-SMA)
    f6:    H/L ratio (52-week highs / (highs + lows + 1))
    f7:    VIX < VIX SMA20

    Total: 0–100.  Thresholds: AGGRESSIVE ≥ 70, SELECTIVE ≥ 40, DEFENSIVE < 40.

    Returns
    -------
    score_dict : {Timestamp: int}   regime score 0-100
    label_dict : {Timestamp: str}   "AGGRESSIVE" | "SELECTIVE" | "DEFENSIVE"
    """
    if spy_df is None or len(spy_df) < 200 or not ticker_states:
        return {}, {}

    # F1–F4 from filters.py (0-60 scale)
    base_score = compute_regime_score_series(spy_df)  # pd.Series[int]

    # Build close matrix aligned to SPY for f5 / f6
    close_matrix = _build_adj_close_matrix(ticker_states, spy_df.index)

    # F5: breadth — fraction of tickers with close > 50-day SMA
    sma50_matrix = close_matrix.rolling(50, min_periods=10).mean()
    breadth      = (close_matrix > sma50_matrix).mean(axis=1).fillna(0.5)
    f5           = (breadth.clip(0.0, 1.0) * REGIME_WEIGHT_BREADTH).astype(int)

    # F6: 52-week H/L ratio
    high_252 = close_matrix.rolling(252, min_periods=63).max()
    low_252  = close_matrix.rolling(252, min_periods=63).min()
    n_high   = (close_matrix >= high_252 * 0.99).sum(axis=1)
    n_low    = (close_matrix <= low_252  * 1.01).sum(axis=1)
    hl_ratio = n_high / (n_high + n_low + 1)
    f6       = (hl_ratio.clip(0.0, 1.0) * REGIME_WEIGHT_HL).astype(int)

    # F7: VIX < VIX SMA20
    f7 = pd.Series(0, index=spy_df.index, dtype=int)
    if vix_df is not None and not vix_df.empty:
        try:
            _vix = vix_df.copy()
            if isinstance(_vix.columns, pd.MultiIndex):
                _vix.columns = _vix.columns.get_level_values(0)
            vcol = "Close" if "Close" in _vix.columns else _vix.columns[0]
            vc   = _vix[vcol].dropna()
            if len(vc) >= 20:
                vix_sma20  = vc.rolling(20).mean()
                is_low_vix = (vc < vix_sma20).reindex(spy_df.index).fillna(False)
                f7         = (is_low_vix.astype(int) * REGIME_WEIGHT_VIX)
        except Exception:
            pass  # VIX failure is non-fatal — f7 stays 0

    full_score = (base_score + f5 + f6 + f7).clip(0, 100).astype(int)

    labels = pd.Series(
        np.select(
            [full_score >= REGIME_AGGRESSIVE_THRESHOLD,
             full_score >= REGIME_SELECTIVE_THRESHOLD],
            ["AGGRESSIVE", "SELECTIVE"],
            default="DEFENSIVE",
        ),
        index=spy_df.index,
        dtype=object,
    )

    return full_score.to_dict(), labels.to_dict()


def _compute_monthly_top_sectors(
    ticker_states: List[TickerSimState],
    spy_df: pd.DataFrame,
    sectors: Dict[str, str],
    top_n: int = TOP_SECTORS_N,
) -> List[Tuple[pd.Timestamp, List[str]]]:
    """
    Compute top-N sectors by average O'Neil RS for the first trading day of
    each calendar month.  Returns a list of (Timestamp, [sector names]) sorted
    ascending by date, for use with _get_top_sectors_for_date().
    """
    spy_col   = "Adj Close" if "Adj Close" in spy_df.columns else "Close"
    spy_close = spy_df[spy_col].dropna()
    if len(spy_close) < 63 or not sectors or not ticker_states:
        return []

    close_df  = _build_adj_close_matrix(ticker_states, spy_close.index)
    rs_matrix = pd.DataFrame(0.0, index=close_df.index, columns=close_df.columns)
    for period, weight in zip((63, 126, 189, 252), (0.40, 0.20, 0.20, 0.20)):
        tk_ret  = close_df.pct_change(period)
        spy_ret = spy_close.pct_change(period)
        rs_matrix += tk_ret.sub(spy_ret, axis=0).fillna(0.0) * weight

    # Identify first available trading day of each month
    seen_months: set = set()
    monthly_dates: List[pd.Timestamp] = []
    for d in sorted(spy_close.index):
        ym = (d.year, d.month)
        if ym not in seen_months:
            seen_months.add(ym)
            monthly_dates.append(d)

    result: List[Tuple[pd.Timestamp, List[str]]] = []
    for mdate in monthly_dates:
        if mdate not in rs_matrix.index:
            continue
        row = rs_matrix.loc[mdate]
        sector_scores: Dict[str, List[float]] = {}
        for ticker in row.index:
            sector = sectors.get(ticker, "Unknown")
            if sector == "Unknown":
                continue
            val = row[ticker]
            if pd.notna(val):
                sector_scores.setdefault(sector, []).append(float(val))
        if not sector_scores:
            continue
        sector_avg = {s: sum(v) / len(v) for s, v in sector_scores.items()}
        top        = sorted(sector_avg, key=sector_avg.__getitem__, reverse=True)[:top_n]
        result.append((mdate, top))

    return result  # already sorted by date


def _get_top_sectors_for_date(
    monthly_sectors: List[Tuple[pd.Timestamp, List[str]]],
    T_date: pd.Timestamp,
) -> List[str]:
    """Return the most-recent monthly top-sectors entry whose date ≤ T_date."""
    if not monthly_sectors:
        return []
    # monthly_sectors is sorted ascending — find last entry <= T_date
    dates = [entry[0] for entry in monthly_sectors]
    pos   = bisect.bisect_right(dates, T_date) - 1
    return monthly_sectors[pos][1] if pos >= 0 else []


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio runner — full implementation
# ─────────────────────────────────────────────────────────────────────────────

async def run_portfolio_backtest_universe(
    tickers: List[str],
    config: BacktestConfig,
    params=None,
    progress_cb=None,
    sectors: Optional[Dict[str, str]] = None,
) -> List[dict]:
    """
    Portfolio-coordinated backtest over all tickers, matching live-scanner
    signal quality gates:
      - Cross-sectional RS rank ≥ RS_RANK_MIN_PERCENTILE
      - Full 7-factor regime (including breadth + VIX)
      - compute_setup_score() → 0-100 (same function as live scanner)
      - config.min_score compared on 0-100 scale

    Phase 1: Prepare all tickers concurrently (fetch + indicator compute).
             Then post-process: RS ranks, regime, top sectors.
    Phase 2: Single day-by-day replay with global position cap.

    Returns flat list of TradeRecord.to_dict() dicts.
    """
    from backtest_engine import (
        BacktestEngine, _manage_open_trade,
        _SIGNAL_BASE_SCORES, _SIGNAL_BASE_SCORE_DEFAULT,
        _fetch_data,
    )
    from scoring import compute_setup_score as _score_setup

    if not tickers:
        return []

    _sectors = sectors or {}

    # ── Phase 1a: Fetch SPY and VIX once (shared across all tickers) ─────
    try:
        _, spy_df = await _fetch_data("SPY", config.start_date)
    except Exception as exc:
        logger.warning("run_portfolio_backtest_universe: SPY fetch error: %s", exc)
        spy_df = None

    vix_df: Optional[pd.DataFrame] = None
    try:
        import yfinance as yf
        vix_df = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: yf.download(
                "^VIX",
                start=config.start_date,
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            ),
        )
        if vix_df is not None and vix_df.empty:
            vix_df = None
    except Exception as exc:
        logger.warning("run_portfolio_backtest_universe: VIX fetch error: %s", exc)
        vix_df = None

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
                    # O(1) bar lookup dict
                    state.date_to_idx = {d: i for i, d in enumerate(state.ticker_dates)}

                    # Vectorised liquidity (replaces 1 rolling-median per day in Phase 2)
                    _vol = state.ticker_df.get("Volume") if "Volume" in state.ticker_df.columns else None
                    if _vol is not None:
                        _vol50 = _vol.rolling(50, min_periods=10).median()
                        _dv    = state.ticker_df["Close"] * _vol50
                        state.liquidity_ok = (
                            (_vol50 >= _constants.LIQUIDITY_MIN_AVG_VOLUME) &
                            (_dv    >= _constants.LIQUIDITY_MIN_DOLLAR_VOLUME)
                        )
                    else:
                        state.liquidity_ok = pd.Series(False, index=state.ticker_dates)

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

    # ── Phase 1c: Cross-sectional RS rank time series ─────────────────────
    _spy_for_regime = spy_df if spy_df is not None else ticker_states[0].spy_df
    if _spy_for_regime is not None and len(_spy_for_regime) > 0:
        _compute_rs_ranks_and_assign(ticker_states, _spy_for_regime)
        logger.info("RS rank cache built for %d tickers", len(ticker_states))

    # ── Phase 1d: Full 7-factor regime score series ───────────────────────
    regime_score_dict: Dict = {}
    regime_label_dict: Dict = {}
    if _spy_for_regime is not None and len(_spy_for_regime) > 0:
        regime_score_dict, regime_label_dict = _compute_full_regime_dicts(
            _spy_for_regime, vix_df, ticker_states
        )
        logger.info(
            "Full 7-factor regime computed: %d trading days", len(regime_score_dict)
        )

    # Fallback: use simple 4-factor labels if full regime computation failed
    if not regime_label_dict and _spy_for_regime is not None and len(_spy_for_regime) > 0:
        _fallback = _filters.compute_regime_label_series(_spy_for_regime)
        regime_label_dict = _fallback.to_dict()
        regime_score_dict = {d: (70 if v == "AGGRESSIVE" else 40 if v == "SELECTIVE" else 0)
                             for d, v in regime_label_dict.items()}

    # Sorted SPY date list for O(log n) bisect lookup in Phase 2
    _spy_dates_sorted = sorted(regime_score_dict.keys())

    # ── Phase 1e: Monthly top sectors ────────────────────────────────────
    monthly_top_sectors: List = []
    if _spy_for_regime is not None and _sectors:
        monthly_top_sectors = _compute_monthly_top_sectors(
            ticker_states, _spy_for_regime, _sectors, top_n=TOP_SECTORS_N
        )
        logger.info("Monthly top sectors: %d months computed", len(monthly_top_sectors))

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
            full_idx = ts.date_to_idx.get(T_date)
            if full_idx is None:
                still_open.append(pos)
                continue
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

        # ── Step 3: Resolve regime via bisect (O(log n)) ──────────────────
        _pos = bisect.bisect_right(_spy_dates_sorted, T_date) - 1
        if _pos < 0:
            continue
        _spy_date      = _spy_dates_sorted[_pos]
        current_regime = regime_label_dict.get(_spy_date, "DEFENSIVE")
        regime_score   = int(regime_score_dict.get(_spy_date, 0))

        if current_regime == "DEFENSIVE":
            continue

        # Top sectors for this date (from monthly pre-computation)
        top_sectors = _get_top_sectors_for_date(monthly_top_sectors, T_date)

        # ── Step 4: Collect signals from all free tickers ─────────────────
        candidates = []
        for ts in ticker_states:
            if ts.is_in_trade:
                continue

            # O(1) date lookup
            full_idx = ts.date_to_idx.get(T_date)
            if full_idx is None:
                continue
            if full_idx + 1 >= len(ts.ticker_dates):
                continue

            # Cooldown gate
            if ts.last_close_date is not None and ts.params is not None:
                days_since = (T_date.date() - ts.last_close_date).days
                if days_since < ts.params.cooldown_days:
                    continue

            # ── RS rank gate (live-scanner parity) ────────────────────────
            rs_rank = ts.rs_rank_cache.get(T_date)
            if rs_rank is None or rs_rank < _constants.RS_RANK_MIN_PERCENTILE:
                continue

            # Liquidity gate (O(1) — pre-computed boolean Series)
            if ts.liquidity_ok is None or not ts.liquidity_ok.iloc[full_idx]:
                continue

            # Signal detection
            signal = _detect_signals_for_date(ts, T_date, full_idx, config.setup_types, regime=current_regime)
            if signal is None:
                continue

            # ── Internal BacktestParams scoring (mechanism quality gate) ──
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

                # Internal mechanism quality gate
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
                if current_regime == "SELECTIVE" and SELECTIVE_HARD_FILTER and SELECTIVE_SETUP_WEIGHTS:
                    setup_type_sig = signal.get("setup_type", "")
                    if SELECTIVE_SETUP_WEIGHTS.get(setup_type_sig, 1.0) == 0.0:
                        continue

            # ── Live-scanner quality score (compute_setup_score) ──────────
            # Inject sector (required by scoring.py sector component)
            signal["sector"] = _sectors.get(ts.ticker, "Unknown")

            # Estimate R:R for the score's RR component
            _close = float(ts.ticker_df["Close"].iloc[full_idx])
            _stop  = signal.get("stop_loss", 0.0)
            if ts.params is not None and _close > 0 and _stop > 0 and _stop < _close:
                _risk = _close - _stop
                if _risk > 0:
                    signal["rr"] = ts.params.tp_multiple  # rr = tp_mult when risk=1R
            elif "take_profit" in signal and _close > 0 and _stop > 0 and _stop < _close:
                _tp = signal["take_profit"]
                if _tp > _close:
                    signal["rr"] = (_tp - _close) / (_close - _stop)

            # Compute true 0-100 setup score
            setup_score = _score_setup(signal, rs_rank, regime_score, current_regime, top_sectors)
            signal["setup_score"] = setup_score

            # ── Market quality gate ────────────────────────────────────────
            if setup_score < config.min_score:
                continue

            candidates.append((setup_score, signal, ts, full_idx))

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
