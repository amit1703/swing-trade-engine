"""
Swing Trading Dashboard — FastAPI Backend
==========================================
Endpoints
─────────
  POST /api/run-scan          Trigger full background scan (non-blocking)
  GET  /api/scan-status       Poll scan progress
  GET  /api/regime            Latest SPY regime from DB
  GET  /api/setups            All setups (VCP + Pullback)
  GET  /api/setups/vcp        VCP setups only
  GET  /api/setups/pullback   Pullback setups only
  GET  /api/setups/base       Cup & Handle + Flat Base setups only
  GET  /api/sr-zones/{ticker} S/R zones for one ticker (from last scan)
  GET  /api/chart/{ticker}    OHLCV + EMA8/20 + SMA50 + CCI20 (fresh fetch)
  GET  /api/watchlist                 WATCHLIST setups from last scan
  GET  /api/setups/options-catalyst  OPTIONS_CATALYST setups from last scan
  GET  /api/prices                   Live prices for comma-separated tickers (60s cache)
  GET  /api/debug/{ticker}           Dev mode: per-engine pass/fail for one ticker (fresh fetch)
  GET  /api/health                   Health-check

Architecture
────────────
  • yfinance calls run in a ThreadPoolExecutor (blocking I/O).
  • asyncio.Semaphore(5) caps concurrent yfinance requests.
  • Heavy maths (KDE, curve_fit) also run in executor threads.
  • All scan results are persisted to SQLite via aiosqlite.
  • Frontend reads only from the DB — no on-the-fly computation.

Run
───
  cd backend
  uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

import asyncio
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
import math
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

import aiosqlite
import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()


def _json_safe(obj):
    """Convert numpy scalar types to native Python for json.dumps."""
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

from apscheduler.schedulers.background import BackgroundScheduler

from filters import in_earnings_blackout as _in_earnings_blackout
from indicators import ema as _ema, sma as _sma, cci as _cci, atr as _atr
from indicators.indicator_engine import compute_indicators, TickerIndicators
from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from constants import (
    BULK_DOWNLOAD_BATCH_SIZE,
    CACHE_TTL_FAILURE,
    CACHE_TTL_SUCCESS,
    CONCURRENCY_LIMIT,
    DATA_FETCH_PERIOD,
    DAYS_3_MONTHS,
    DB_PATH,
    EARNINGS_BLACKOUT_DAYS,
    EARNINGS_CACHE_FILE,
    EARNINGS_CACHE_TTL_HOURS,
    FETCH_BACKOFF_BASE,
    FETCH_MAX_RETRIES,
    LIQUIDITY_MIN_AVG_VOLUME,
    LIQUIDITY_MIN_DOLLAR_VOLUME,
    MAX_TICKERS_PER_SCAN,
    MIN_ATR_PCT,
    MIN_CANDLES_FOR_ANALYSIS,
    MIN_CANDLES_FOR_RS,
    RS_BLUE_DOT_TOLERANCE_PCT,
    REGIME_SELECTIVE_THRESHOLD,
    TRADING_DAYS_IN_YEAR,
    RS_RANK_MIN_PERCENTILE,
    MIN_SETUP_SCORE,
    MIN_SETUP_SCORE_DEFENSIVE,
    TOP_SECTORS_N,
    # Universe loader aging thresholds
    UNIVERSE_MAX_AGE_DAYS,
    UNIVERSE_WARN_AGE_DAYS,
    UNIVERSE_MIN_SIZE,
    UNIVERSE_MAX_SIZE,
    # Discovery layer constants
    DISCOVERY_RS_MIN,
    DISCOVERY_RS_MAX,
    DISCOVERY_52WK_HIGH_PCT,
    DISCOVERY_VOL_RATIO,
    DISCOVERY_MAX_PCT,
    # Backtest diagnostics
    BACKTEST_DIAG_START_DATE,
    BACKTEST_DIAG_END_DATE,
    BACKTEST_V4_TRAIL_MULT,
    BACKTEST_DIAG_CACHE_FILE,
    # Worker queue sizing
    SCAN_COMPUTE_WORKERS,
    SCAN_IO_WORKERS,
    SCAN_QUEUE_MULTIPLIER,
    # Pass 1 filter thresholds
    PASS1_MIN_PRICE,
    PASS1_MIN_AVG_VOLUME,
    PASS1_MIN_DOLLAR_VOLUME,
    PASS1_MIN_RS_RANK,
    PASS1_MIN_RS_RANK_WARM,
    PASS1_MIN_52W_HIGH_PCT,
    PASS1_BELOW_SMA50_MIN_52W_PCT,
    PASS1_BELOW_SMA50_VOL_RATIO,
    PASS1_BELOW_SMA50_MIN_RS,
    PASS1_BELOW_SMA50_VOL_PERCENTILE,
    PASS1_BELOW_SMA50_VOL_FLOOR,
    PASS1_BELOW_SMA50_VOL_CEIL,
    PASS1_BELOW_SMA50_PROX_PERCENTILE,
    PASS1_BELOW_SMA50_PROX_FLOOR,
    PASS1_BELOW_SMA50_PROX_CEIL,
    PASS1_BELOW_SMA50_MIN_SAMPLE,
    PASS1_MAX_SURVIVORS,
    SCAN_CACHE_DIR,
    RS_RANK_CACHE_REFRESH_THRESHOLD,
)
from database import (
    complete_scan_run,
    get_latest_regime,
    get_latest_scan_timestamp,
    get_latest_setups,
    get_sr_zones_for_ticker_from_db,
    get_regime_history,
    init_db,
    save_regime,
    save_scan_run,
    save_setup,
    batch_save_setups,
    batch_save_sr_zones,
    save_sr_zones,
    add_trade,
    get_trades,
    close_trade,
    get_closed_trades,
    save_backtest_result,
    get_backtest_results,
    create_wfo_run,
    update_wfo_progress,
    save_wfo_result,
    mark_wfo_error,
    get_wfo_run,
)
from wfo_cache import download_and_cache, cache_exists as wfo_cache_exists
from wfo_engine import run_wfo
from engines.engine0 import check_market_regime
from engines.engine1 import calculate_sr_zones
from engines.engine2 import scan_vcp, detect_trendline
from engines.engine3 import scan_pullback, scan_relaxed_pullback, scan_pullback_scored, scan_pullback_approaching
from engines.engine6 import scan_resistance_breakout, scan_res_breakout_near
from engines.engine4 import calculate_rs_line, detect_rs_blue_dot, get_rs_stats, calculate_rs_score, get_rs_signals
from engines.engine5 import scan_base_pattern
from engines.engine6 import scan_resistance_breakout
from engines.engine7 import scan_options_catalyst
from engines.engine8_htf import scan_htf
from engines.engine9_low_cheat import scan_lce
from tickers import SCAN_UNIVERSE
from validation import is_price_vital
from universe_builder import build_universe, load_universe, save_universe, UNIVERSE_FILE
from scoring import compute_rs_rank_map, compute_top_sectors, score_and_filter_setups
from analytics import (
    compute_live_diagnostics,
    compute_setup_breakdown,
    compute_ticker_distribution,
    compute_regime_performance,
    compute_regime_stability,
    compute_selective_breakdown,
)
from email_digest import send_digest
from services.macro_service import get_market_overview
from services.narrative import generate_narrative
from backtest_engine import BacktestEngine, BacktestParams, run_backtest_universe
from portfolio_backtest import run_portfolio_backtest_universe, BacktestConfig
from execution.trailing_engine import compute_live_trail as _compute_live_trail
from config.trailing_config import validate_trail_config
from execution.trailing_engine import log_trail_config as _log_trail_config

# Shared optimized params instance used by live scanner engines (engine6, etc.)
_LIVE_PARAMS = BacktestParams()


def _apply_tp_multiple(signal: dict, params) -> dict:
    """Override take_profit and rr using params.tp_multiple × risk.

    Mirrors backtest_engine.py scored-mode override:
        take_profit = entry + tp_multiple × (entry - stop_loss)

    Modifies signal in place and returns it. No-ops if entry/stop are invalid.
    """
    entry     = signal.get("entry", 0.0)
    stop_loss = signal.get("stop_loss", 0.0)
    if entry > 0 and stop_loss > 0 and entry > stop_loss:
        risk              = entry - stop_loss
        tp_mult           = getattr(params, "tp_multiple", 2.0)
        signal["take_profit"] = round(entry + tp_mult * risk, 2)
        signal["rr"]          = round(tp_mult, 3)  # reward/risk = tp_mult by construction
    return signal


# ────────────────────────────────────────────────────────────────────────────
# Configuration (imported from constants.py for centralized management)
# ────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("swing")

# ────────────────────────────────────────────────────────────────────────────
# Universe & Sector loading (active_universe.json with age-check + tickers.py fallback)
# ────────────────────────────────────────────────────────────────────────────

ACTIVE_UNIVERSE = SCAN_UNIVERSE  # default fallback
SECTORS = {}

def _load_hybrid_universe() -> None:
    """Load active_universe.json with age-check; fall back to SCAN_UNIVERSE on stale/missing file."""
    global ACTIVE_UNIVERSE, SECTORS

    # ── Attempt to open and parse the universe file directly ─────────────────
    _raw_data = None
    try:
        with open(UNIVERSE_FILE, "r", encoding="utf-8") as _fh:
            _raw_data = json.load(_fh)
    except FileNotFoundError:
        log.warning("No active_universe.json found — using SCAN_UNIVERSE (%d tickers)", len(SCAN_UNIVERSE))
    except Exception as _exc:
        log.warning("Could not read universe file %s: %s — using SCAN_UNIVERSE", UNIVERSE_FILE, _exc)

    if _raw_data is None:
        # No file: fall back to SCAN_UNIVERSE + try sectors.json
        try:
            with open("sectors.json", "r") as _f:
                SECTORS = json.load(_f)
            log.info("Loaded %d sectors from sectors.json (fallback)", len(SECTORS))
        except Exception as _e:
            log.warning("Could not load sectors.json: %s", _e)
        return

    # ── Age check via metadata["generated_at"] ───────────────────────────────
    _use_file = True
    try:
        _generated_at_str = _raw_data.get("metadata", {}).get("generated_at", "")
        if _generated_at_str:
            _generated_at = datetime.fromisoformat(_generated_at_str)
            _age_days = (datetime.utcnow() - _generated_at).total_seconds() / 86400.0
            if _age_days > UNIVERSE_MAX_AGE_DAYS:
                log.warning(
                    "Universe file is %.1f days old (> %d-day hard limit) — "
                    "falling back to SCAN_UNIVERSE (%d tickers)",
                    _age_days, UNIVERSE_MAX_AGE_DAYS, len(SCAN_UNIVERSE),
                )
                _use_file = False
            elif _age_days > UNIVERSE_WARN_AGE_DAYS:
                log.warning(
                    "Universe file is %.1f days old (> %d-day soft limit) — "
                    "consider rebuilding with POST /api/build-universe",
                    _age_days, UNIVERSE_WARN_AGE_DAYS,
                )
        else:
            log.warning("Universe file has no generated_at timestamp — age unknown, using file anyway")
    except Exception as _age_exc:
        log.warning("Could not parse universe age: %s — using file anyway", _age_exc)

    if not _use_file:
        # Stale: fall back to SCAN_UNIVERSE + try sectors.json
        try:
            with open("sectors.json", "r") as _f:
                SECTORS = json.load(_f)
            log.info("Loaded %d sectors from sectors.json (fallback)", len(SECTORS))
        except Exception as _e:
            log.warning("Could not load sectors.json: %s", _e)
        return

    # ── Load tickers and sectors from the file ────────────────────────────────
    try:
        _tickers = _raw_data["tickers"]
        _sectors = _raw_data.get("sectors", {})
    except (KeyError, TypeError) as _exc:
        log.warning("Universe file missing tickers key: %s — using SCAN_UNIVERSE", _exc)
        return

    # ── Size sanity checks ────────────────────────────────────────────────────
    if len(_tickers) < UNIVERSE_MIN_SIZE:
        log.warning(
            "Universe has only %d tickers (< %d minimum) — filter may be too tight",
            len(_tickers), UNIVERSE_MIN_SIZE,
        )
    elif len(_tickers) > UNIVERSE_MAX_SIZE:
        log.warning(
            "Universe has %d tickers (> %d maximum) — filter may be too loose",
            len(_tickers), UNIVERSE_MAX_SIZE,
        )

    # ── Cap to MAX_TICKERS_PER_SCAN ───────────────────────────────────────────
    if len(_tickers) > MAX_TICKERS_PER_SCAN:
        log.warning(
            "Universe has %d tickers, capping to %d",
            len(_tickers), MAX_TICKERS_PER_SCAN,
        )
        _tickers = _tickers[:MAX_TICKERS_PER_SCAN]

    ACTIVE_UNIVERSE = _tickers
    SECTORS = _sectors
    log.info("Loaded active universe: %d tickers from %s", len(ACTIVE_UNIVERSE), UNIVERSE_FILE)


_load_hybrid_universe()

# ────────────────────────────────────────────────────────────────────────────
# Discovery layer — RS 60-70 emerging leaders that bypass the RS >= 70 gate
# ────────────────────────────────────────────────────────────────────────────

def _build_discovery_tickers(
    tickers: List[str],
    rs_rank_map: Dict[str, float],
    ticker_cache: dict,
) -> set:
    """Return a set of tickers with RS rank in [DISCOVERY_RS_MIN, DISCOVERY_RS_MAX),
    close within DISCOVERY_52WK_HIGH_PCT of their 52-week high, AND 5-day average
    volume >= DISCOVERY_VOL_RATIO × 50-day average volume.

    The result is capped at int(len(tickers) * DISCOVERY_MAX_PCT) to prevent
    the discovery layer from flooding the pipeline.
    """
    candidates: List[str] = []

    for ticker in tickers:
        # ── RS rank filter: [DISCOVERY_RS_MIN, DISCOVERY_RS_MAX) ─────────────
        rs_rank = rs_rank_map.get(ticker)
        if rs_rank is None:
            continue
        if not (DISCOVERY_RS_MIN <= rs_rank < DISCOVERY_RS_MAX):
            continue

        # ── Pull cached DataFrame ─────────────────────────────────────────────
        cache_entry = ticker_cache.get(ticker)
        if cache_entry is None:
            continue
        _ts, df = cache_entry
        if df is None or len(df) < 55:  # need at least 50 bars for vol avg + 5 recent
            continue

        try:
            close = df["Close"]

            # ── 52-week high proximity ────────────────────────────────────────
            high_52w = close.iloc[-252:].max() if len(close) >= 252 else close.max()
            last_close = float(close.iloc[-1])
            if high_52w <= 0:
                continue
            if (high_52w - last_close) / high_52w > DISCOVERY_52WK_HIGH_PCT:
                continue  # more than DISCOVERY_52WK_HIGH_PCT below the 52wk high

            # ── Volume expansion: 5-day avg >= DISCOVERY_VOL_RATIO × 50-day avg ──
            vol = df["Volume"].astype(float)
            avg_vol_50d = float(vol.iloc[-55:-5].mean())  # 50-day avg (exclude last 5)
            avg_vol_5d  = float(vol.iloc[-5:].mean())
            if avg_vol_50d <= 0:
                continue
            if avg_vol_5d < DISCOVERY_VOL_RATIO * avg_vol_50d:
                continue

            candidates.append(ticker)

        except Exception:
            continue  # skip silently; discovery is best-effort

    # ── Cap at DISCOVERY_MAX_PCT of universe ──
    max_count = int(len(tickers) * DISCOVERY_MAX_PCT)
    return set(candidates[:max_count])


# ────────────────────────────────────────────────────────────────────────────
# Shared state (single-process; safe with asyncio event loop)
# ────────────────────────────────────────────────────────────────────────────

# In-memory price cache: {ticker: (timestamp, price)}
_price_cache: dict = {}
PRICE_CACHE_TTL = 60  # seconds

# In-memory earnings blackout cache: {ticker: {"blackout": bool, "cached_at": ISO str}}
_earnings_cache: dict = {}
_earnings_cache_lock = threading.Lock()

# Last scan's RS rank map and top sectors — used for on-demand scoring
_last_rs_rank_map: Dict[str, float] = {}
_last_top_sectors: List[str] = []

# ── Disk-persisted OHLCV cache (scanner's own — separate from WFO price_cache) ─
from cache_store import CacheStore as _CacheStore
_cache_store: _CacheStore = _CacheStore(cache_dir=SCAN_CACHE_DIR)

_scan_state: Dict = {
    "in_progress": False,
    "progress": 0,
    "total": 0,
    "started_at": None,
    "last_completed": None,
    "last_error": None,
    "engine_stats": {
        "e0": {},
        "e1": {"zones_saved": 0},
        "e2": {"vcp": 0, "watchlist": 0},
        "e3": {"pullback": 0, "relaxed": 0},
        "e5": {"cup_handle": 0, "flat_base": 0},
        "e6": {"res_breakout": 0},
        "e7": {"options_catalyst": 0},
        "e8": {"htf": 0},
        "e9": {"lce": 0},
        "total_tickers": 0,
        "total_duration_s": 0.0,
        "forced": False,
        "dry_run": False,
        "timing": {
            "regime_s": 0.0,
            "spy_fetch_s": 0.0,
            "prefetch_s": 0.0,
            "process_s": 0.0,
            "db_s": 0.0,
            "total_s": 0.0,
            "pass1_filter_s": 0.0,
            "fetch_s": 0.0,
            "rs_cache_s": 0.0,
            "pass2_s": 0.0,
        },
        "filtered": {
            "liquidity":        0,
            "earnings":         0,
            "insufficient_data": 0,
            "vitality":         0,
            "rs_rank_gate":     0,
            "rs_score_gate":    0,
            "ind_failed":       0,
        },
        "pass1_survivors": 0,
        "pass1_thresholds": {},
        "cache_hit_rate": 0.0,
    },
    "dry_run_setups": None,
}
_semaphore: Optional[asyncio.Semaphore] = None
_ticker_cache: dict = {}  # ticker → (timestamp: float, df: Optional[pd.DataFrame])

# ── JSON encoder for numpy types ─────────────────────────────────────────────
class _NumpyEncoder(json.JSONEncoder):
    """Serialize numpy scalars and arrays that leak into report dicts."""
    def default(self, obj):
        if isinstance(obj, np.integer):  return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.bool_):    return bool(obj)
        if isinstance(obj, np.ndarray):  return obj.tolist()
        return super().default(obj)


def _json_sanitize(obj):
    """
    Recursively replace NaN/Inf (numpy or native float) with None so the
    output is valid JSON. Browsers reject the literal `NaN` token.
    """
    if isinstance(obj, dict):
        return {k: _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_sanitize(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, np.floating):
        v = float(obj)
        return None if not math.isfinite(v) else v
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return _json_sanitize(obj.tolist())
    return obj

# ── Backtest diagnostics state ────────────────────────────────────────────────
BACKTEST_DIAG_CACHE_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), BACKTEST_DIAG_CACHE_FILE))

_backtest_diag_status: dict = {
    "status":      "idle",   # "idle" | "running" | "completed" | "failed"
    "done":        0,
    "total":       0,
    "last_run":    None,     # ISO timestamp of last completed run
    "phase":       None,     # 1 | 2 | None
    "phase_label": None,     # human-readable phase description
}

# ── IS/OOS diagnostics state ──────────────────────────────────────────────────
ISOOS_DIAG_CACHE_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "cache", "isoos_diagnostics.json")
)

_isoos_running: bool = False
_isoos_status: dict = {
    "status":     "idle",   # "idle" | "running_is" | "running_oos" | "completed" | "failed"
    "is_done":    False,
    "current":    0,
    "total":      0,
    "phase":      None,     # "is" | "oos" | "done" | None
    "step_label": None,     # human-readable current step within each period
    "error":      None,
}


def _backtest_trade_to_analytics(tr: dict) -> dict:
    """Map TradeRecord.to_dict() fields to analytics.py contract."""
    return {
        "ticker":       tr["ticker"],
        "setup_type":   tr["setup_type"],
        "entry_price":  tr["entry_price"],
        "stop_loss":    tr["initial_stop"],   # initial_stop → stop_loss
        "close_price":  tr["exit_price"],     # exit_price  → close_price
        "status":       "closed",
        "regime_score": None,
        "regime":       tr.get("regime", "UNKNOWN"),
    }

# WFO in-memory state
_wfo_download_jobs: Dict[str, Dict] = {}   # job_id → progress dict
_wfo_runs:          Dict[str, Dict] = {}   # run_id → progress dict

# ── Email digest cache ────────────────────────────────────────────────────────
# Populated by the 7:30 AM scheduler job; consumed by the 8:00 AM email job.
_digest_cache: dict = {}
_digest_cache_lock = threading.Lock()

# ── APScheduler instance ──────────────────────────────────────────────────────
_scheduler: Optional[BackgroundScheduler] = None

# ────────────────────────────────────────────────────────────────────────────
# Earnings blackout helpers (Task 1)
# ────────────────────────────────────────────────────────────────────────────

def _load_earnings_cache() -> dict:
    """Load earnings cache from disk; return empty dict on any error."""
    try:
        if os.path.exists(EARNINGS_CACHE_FILE):
            with open(EARNINGS_CACHE_FILE, "r") as f:
                return json.load(f)
    except Exception as exc:
        log.warning("Could not load earnings cache: %s", exc)
    return {}


def _save_earnings_cache(cache: dict) -> None:
    """Persist earnings cache to disk."""
    try:
        os.makedirs(os.path.dirname(EARNINGS_CACHE_FILE), exist_ok=True)
        with open(EARNINGS_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception as exc:
        log.warning("Could not save earnings cache: %s", exc)


def _check_earnings_blackout_sync(ticker: str) -> bool:
    """
    Return True if ``ticker`` has an earnings event within
    EARNINGS_BLACKOUT_DAYS calendar days.

    Thread-safe: reads/writes global ``_earnings_cache`` under
    ``_earnings_cache_lock``.  Calls yfinance only for stale / missing entries.
    Fails *open* on any error (returns False) so individual fetch issues
    never block a ticker from being analysed.
    """
    now = datetime.utcnow()

    # ── Read from cache ───────────────────────────────────────────────────────
    with _earnings_cache_lock:
        entry = _earnings_cache.get(ticker)

    if entry is not None:
        try:
            cached_at = datetime.fromisoformat(entry["cached_at"])
            if (now - cached_at).total_seconds() < EARNINGS_CACHE_TTL_HOURS * 3600:
                return entry["blackout"]
        except Exception:
            pass

    # ── Fetch earnings calendar from yfinance ─────────────────────────────────
    blackout = False
    try:
        cal = yf.Ticker(ticker).calendar
        if cal is not None:
            # yfinance may return a dict or a DataFrame depending on version
            dates = []
            if isinstance(cal, dict):
                raw = cal.get("Earnings Date", [])
                dates = list(raw) if hasattr(raw, "__iter__") and not isinstance(raw, str) else ([raw] if raw else [])
            elif hasattr(cal, "to_dict"):
                cal_dict = cal.to_dict("list")
                dates = cal_dict.get("Earnings Date", [])

            dates_to_check = []
            for d in dates:
                try:
                    if hasattr(d, "to_pydatetime"):
                        d = d.to_pydatetime().replace(tzinfo=None)
                    elif isinstance(d, str):
                        d = datetime.fromisoformat(d)
                    dates_to_check.append(d.strftime("%Y-%m-%d"))
                except Exception:
                    pass
            today_str = now.strftime("%Y-%m-%d")
            blackout = _in_earnings_blackout(today_str, dates_to_check)
    except Exception:
        pass  # Fail open — don't block tickers we can't check

    # ── Write result to cache ─────────────────────────────────────────────────
    with _earnings_cache_lock:
        _earnings_cache[ticker] = {"blackout": blackout, "cached_at": now.isoformat()}

    return blackout


# ────────────────────────────────────────────────────────────────────────────
# Scheduler jobs (run at 7:30 AM and 8:00 AM ET daily)
# ────────────────────────────────────────────────────────────────────────────

def run_morning_scan() -> None:
    """
    7:30 AM ET job — run all scan engines and store results in _digest_cache.

    APScheduler calls this in a background thread, not in the asyncio event loop,
    so we use asyncio.run() to create a fresh event loop for the async scan pipeline.
    The semaphore is re-created inside that loop so it is bound to the correct loop.
    """
    log.info("[scheduler] 7:30 AM scan job starting…")
    try:
        async def _scan_and_cache() -> None:
            global _digest_cache

            # Create a fresh semaphore local to this loop (do not overwrite the
            # module-level _semaphore used by the main FastAPI event loop)
            _local_semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

            scan_ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

            # Initialise DB (idempotent) in case the server was restarted
            await init_db(DB_PATH)

            # Run full scan pipeline (saves to DB and updates _scan_state)
            await _run_scan(scan_ts, ACTIVE_UNIVERSE, force=False, dry_run=False, semaphore=_local_semaphore)

            # Pull results from DB to build the digest cache
            from database import get_latest_regime as _get_regime, get_latest_setups as _get_setups

            regime = await _get_regime(DB_PATH) or {}
            vcp_setups     = await _get_setups(DB_PATH, setup_type="VCP")
            watchlist      = await _get_setups(DB_PATH, setup_type="WATCHLIST")
            res_setups     = await _get_setups(DB_PATH, setup_type="RES_BREAKOUT")
            pb_setups      = await _get_setups(DB_PATH, setup_type="PULLBACK")
            opt_setups     = await _get_setups(DB_PATH, setup_type="OPTIONS_CATALYST")
            htf_setups     = await _get_setups(DB_PATH, setup_type="HTF")
            lce_setups     = await _get_setups(DB_PATH, setup_type="LCE")

            # Enrich regime with SPY SMA50 for BULL/BEAR/NEUTRAL badge
            spy_sma50: Optional[float] = None
            try:
                spy_df_sched = await _fetch("SPY", semaphore=_local_semaphore)
                if spy_df_sched is not None and len(spy_df_sched) >= 50:
                    from indicators import sma as _sma_fn
                    adj_col = "Adj Close" if "Adj Close" in spy_df_sched.columns else "Close"
                    sma50_series = _sma_fn(spy_df_sched[adj_col], 50)
                    spy_sma50 = float(sma50_series.iloc[-1])
            except Exception as sma_exc:
                log.warning("[scheduler] Could not compute SPY SMA50: %s", sma_exc)

            if isinstance(regime, dict):
                regime["spy_sma50"] = spy_sma50

            with _digest_cache_lock:
                _digest_cache = {
                    "regime":           regime,
                    "vcp":              vcp_setups,
                    "vcp_dry":          watchlist,
                    "res_breakout":     res_setups,
                    "pullback":         pb_setups,
                    "options_catalyst": opt_setups,
                    "htf":              htf_setups,
                    "lce":              lce_setups,
                }
            log.info(
                "[scheduler] Digest cache built: vcp=%d  dry=%d  res=%d  pb=%d  opt=%d  htf=%d  lce=%d",
                len(vcp_setups), len(watchlist), len(res_setups), len(pb_setups), len(opt_setups),
                len(htf_setups), len(lce_setups),
            )

        asyncio.run(_scan_and_cache())

    except Exception as exc:
        log.error("[scheduler] Morning scan job failed: %s", exc)


def send_morning_email() -> None:
    """
    8:00 AM ET job — send the email digest from _digest_cache.

    If the cache is empty (e.g., scan failed), the email is skipped with a warning.
    """
    log.info("[scheduler] 8:00 AM email job starting…")
    with _digest_cache_lock:
        cache_snapshot = dict(_digest_cache)
    if not cache_snapshot:
        log.warning(
            "[scheduler] Email digest skipped: _digest_cache is empty. "
            "The 7:30 AM scan may not have completed."
        )
        return
    try:
        send_digest(cache_snapshot)
    except Exception as exc:
        log.error("[scheduler] Email send job failed: %s", exc)


# ────────────────────────────────────────────────────────────────────────────
# App lifecycle
# ────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _semaphore, _scheduler

    # Validate and log trailing stop configuration
    validate_trail_config()   # raises AssertionError if mode != "ema20"
    _log_trail_config()

    _semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    await init_db(DB_PATH)
    log.info("SQLite DB initialised at %s", DB_PATH)
    _cache_store.preload_index()
    log.info("Scan cache index preloaded")

    # ── APScheduler: scan at 7:30 AM ET, email at 8:00 AM ET ────────────────
    _scheduler = BackgroundScheduler(timezone="America/New_York")
    _scheduler.add_job(
        run_morning_scan,
        trigger="cron",
        hour=7,
        minute=30,
        id="morning_scan",
        replace_existing=True,
        misfire_grace_time=600,  # allow up to 10 min late if server was temporarily down
    )
    _scheduler.add_job(
        send_morning_email,
        trigger="cron",
        hour=8,
        minute=0,
        id="morning_email",
        replace_existing=True,
        misfire_grace_time=600,
    )
    _scheduler.add_job(
        run_prewarm_job,
        trigger="cron",
        hour=9,
        minute=15,
        id="prewarm_cache",
        replace_existing=True,
        misfire_grace_time=600,
    )
    _scheduler.start()
    log.info(
        "[scheduler] Started — prewarm at 09:15 ET, scan at 07:30 ET, email at 08:00 ET"
    )

    # Warm the price cache in the background immediately on startup.
    # By the time the first manual scan or dashboard load happens, data is ready.
    asyncio.create_task(_prewarm_price_cache())

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("[scheduler] Stopped")


app = FastAPI(
    title="Swing Trading Dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ────────────────────────────────────────────────────────────────────────────
# Data helpers
# ────────────────────────────────────────────────────────────────────────────

def _batch_download_sync(tickers_batch: List[str]) -> Dict[str, pd.DataFrame]:
    """
    Download 1y daily OHLCV for a batch of tickers in ONE yfinance HTTP request.
    Returns {ticker: DataFrame} for tickers that returned valid data.
    Much faster than individual Ticker().history() calls.
    """
    if not tickers_batch:
        return {}
    if len(tickers_batch) == 1:
        t = tickers_batch[0]
        try:
            df = yf.Ticker(t).history(period="1y", interval="1d", auto_adjust=False)
            return {t: df} if df is not None and not df.empty else {}
        except Exception:
            return {}
    try:
        raw = yf.download(
            tickers_batch,
            period="1y",
            interval="1d",
            auto_adjust=False,
            group_by="ticker",
            progress=False,
            threads=True,
            timeout=60,
        )
        result: Dict[str, pd.DataFrame] = {}
        top_level = raw.columns.get_level_values(0).unique().tolist()
        for ticker in tickers_batch:
            try:
                if ticker not in top_level:
                    continue
                df = raw[ticker].copy()
                df = df.dropna(how="all")
                if df.empty:
                    continue
                if df.columns.duplicated().any():
                    df = df.loc[:, ~df.columns.duplicated()]
                result[ticker] = df
            except Exception:
                pass
        return result
    except Exception as exc:
        log.warning("Batch download failed: %s", exc)
        return {}


# ────────────────────────────────────────────────────────────────────────────
# Worker queue phases
# ────────────────────────────────────────────────────────────────────────────

def _effective_compute_workers() -> int:
    """Return the number of async compute workers for Pass 2.

    These are asyncio coroutines, NOT threads — cpu_count-based caps do not
    apply here. GIL contention is in the ThreadPoolExecutor (handled by Python
    internally). A high worker count lets the event loop overlap I/O waits
    across all survivors, matching the old asyncio.gather() behaviour.
    """
    return SCAN_COMPUTE_WORKERS


async def _run_io_phase(
    survivors: List[str],
    cache_store,                 # CacheStore instance
    semaphore: asyncio.Semaphore,
    workers: int = SCAN_IO_WORKERS,
) -> None:
    """
    Parallel incremental fetch for Pass 1 survivors.
    Uses a bounded queue (workers × SCAN_QUEUE_MULTIPLIER) to limit memory pressure.
    """
    if not survivors:
        return
    await cache_store.bulk_fetch_incremental(survivors, semaphore, workers=workers)


async def _run_compute_phase(
    survivors: List[str],
    process_fn,                  # async callable(ticker, idx, **kwargs)
    workers: Optional[int] = None,
    **process_kwargs,
) -> None:
    """
    Bounded worker pool for Pass 2 (indicators + engines).
    Replaces asyncio.gather(*[_process(t,i) for ...]).
    """
    if not survivors:
        return

    n_workers = workers if workers is not None else _effective_compute_workers()
    queue: asyncio.Queue = asyncio.Queue(maxsize=n_workers * SCAN_QUEUE_MULTIPLIER)

    async def _worker():
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                break
            ticker, idx = item
            try:
                await process_fn(ticker, idx, **process_kwargs)
            except Exception as exc:
                log.error("Compute worker error for %s: %s", ticker, exc)
            finally:
                queue.task_done()

    worker_tasks = [asyncio.create_task(_worker()) for _ in range(n_workers)]
    for i, ticker in enumerate(survivors):
        await queue.put((ticker, i))
    for _ in worker_tasks:
        await queue.put(None)
    await asyncio.gather(*worker_tasks)


# ────────────────────────────────────────────────────────────────────────────
# Pass 1 — fast metadata filter
# ────────────────────────────────────────────────────────────────────────────

def _compute_breadth_from_metadata(
    active_universe: List[str],
    cache_store,
) -> tuple:
    """
    Compute breadth (% above SMA50) and H/L ratio from full-universe metadata.
    Replaces compute_universe_breadth() for the regime breadth component.
    Uses the full universe — not just Pass 1 survivors.
    Returns (breadth_pct, hl_ratio) — defaults (0.5, 0.5) on empty metadata.
    """
    above = 0
    near_high = 0
    total = 0
    for ticker in active_universe:
        meta = cache_store.get_meta(ticker)
        if not meta:
            continue
        total += 1
        if meta.get("above_sma50"):
            above += 1
        lc  = meta.get("last_close", 0)
        h52 = meta.get("high_52w", 0)
        if h52 > 0 and lc / h52 >= 0.95:
            near_high += 1
    if total == 0:
        return 0.5, 0.5
    return above / total, near_high / total


def _identify_discovery_candidates(
    active_universe: List[str],
    cache_store,
    rs_cache: dict,
) -> set:
    """
    Identify RS 60–70 tickers near 52-week high with volume expansion.
    These bypass the Pass 1 RS floor gate.
    """
    candidates = set()
    for ticker in active_universe:
        rs = rs_cache.get(ticker)
        if rs is None or not (DISCOVERY_RS_MIN <= rs < DISCOVERY_RS_MAX):
            continue
        meta = cache_store.get_meta(ticker)
        if not meta:
            continue
        lc  = meta.get("last_close", 0)
        h52 = meta.get("high_52w", 0)
        vr  = meta.get("vol_ratio_5d", 0)
        near_high = h52 > 0 and lc / h52 >= (1 - DISCOVERY_52WK_HIGH_PCT)
        vol_surge = vr >= DISCOVERY_VOL_RATIO
        if near_high and vol_surge:
            candidates.add(ticker)
    return candidates


def _compute_below_sma50_thresholds(
    active_universe: List[str],
    cache_store,
) -> tuple:
    """
    Compute adaptive Pass 1 thresholds from the current universe distribution.

    Returns (vol_thr, prox_thr) where:
      vol_thr  = Nth percentile of vol_ratio_5d across ALL tickers with metadata,
                 clamped to [PASS1_BELOW_SMA50_VOL_FLOOR, PASS1_BELOW_SMA50_VOL_CEIL].
      prox_thr = Nth percentile of (last_close / high_52w) across BELOW-SMA50 tickers,
                 clamped to [PASS1_BELOW_SMA50_PROX_FLOOR, PASS1_BELOW_SMA50_PROX_CEIL].

    Falls back to fixed constants when fewer than PASS1_BELOW_SMA50_MIN_SAMPLE tickers
    are available in either distribution.
    """
    vol_vals  = []   # all tickers with metadata
    prox_vals = []   # below-SMA50 tickers only

    for ticker in active_universe:
        meta = cache_store.get_meta(ticker)
        if meta is None:
            continue
        vr = meta.get("vol_ratio_5d")
        if vr is not None:
            vol_vals.append(vr)
        lc  = meta.get("last_close", 0)
        h52 = meta.get("high_52w",   0)
        if not meta.get("above_sma50", True) and h52 > 0 and lc > 0:
            prox_vals.append(lc / h52)

    # Vol threshold — Nth percentile of full universe
    if len(vol_vals) >= PASS1_BELOW_SMA50_MIN_SAMPLE:
        import statistics as _stats
        sorted_vol = sorted(vol_vals)
        idx = int(len(sorted_vol) * PASS1_BELOW_SMA50_VOL_PERCENTILE / 100)
        raw_vol = sorted_vol[min(idx, len(sorted_vol) - 1)]
        vol_thr = max(PASS1_BELOW_SMA50_VOL_FLOOR, min(PASS1_BELOW_SMA50_VOL_CEIL, raw_vol))
    else:
        raw_vol = None
        vol_thr = PASS1_BELOW_SMA50_VOL_RATIO   # fixed fallback

    # Proximity threshold — Nth percentile of below-SMA50 distribution
    if len(prox_vals) >= PASS1_BELOW_SMA50_MIN_SAMPLE:
        sorted_prox = sorted(prox_vals)
        idx = int(len(sorted_prox) * PASS1_BELOW_SMA50_PROX_PERCENTILE / 100)
        raw_prox = sorted_prox[min(idx, len(sorted_prox) - 1)]
        prox_thr = max(PASS1_BELOW_SMA50_PROX_FLOOR, min(PASS1_BELOW_SMA50_PROX_CEIL, raw_prox))
    else:
        raw_prox = None
        prox_thr = PASS1_BELOW_SMA50_MIN_52W_PCT   # fixed fallback

    log.info(
        "Pass 1 adaptive thresholds: vol_thr=%.3f (P%d of %d tickers, raw=%s) | "
        "prox_thr=%.3f (P%d of %d below-SMA50 tickers, raw=%s)",
        vol_thr,  PASS1_BELOW_SMA50_VOL_PERCENTILE,  len(vol_vals),
        f"{raw_vol:.3f}"  if raw_vol  is not None else "fixed",
        prox_thr, PASS1_BELOW_SMA50_PROX_PERCENTILE, len(prox_vals),
        f"{raw_prox:.3f}" if raw_prox is not None else "fixed",
    )
    return vol_thr, prox_thr


def _pass1_filter(
    active_universe: List[str],
    cache_store,
    rs_cache: dict,
) -> tuple:
    """
    Fast metadata-only filter. Returns (survivors, discovery_set).

    Filters applied in order (cheapest first) when metadata is present:
      1. Not excluded-stale (> PRICE_CACHE_MAX_STALE_DAYS biz days)
      2. Price floor              (PASS1_MIN_PRICE)
      3. Volume / dollar-vol     (PASS1_MIN_AVG_VOLUME, PASS1_MIN_DOLLAR_VOLUME)
      4. Above 50-day SMA        (PASS1_REQUIRE_ABOVE_SMA50) — all setup types need uptrend
      5. 52-week high proximity  (PASS1_MIN_52W_HIGH_PCT)    — skip deep drawdown stocks
      6. RS pre-filter           (PASS1_MIN_RS_RANK_WARM when valid cache, else PASS1_MIN_RS_RANK)
    Tickers with no metadata pass through unconditionally (cold start / new entries).
    Then adaptive tightening if survivors > PASS1_MAX_SURVIVORS.
    """
    discovery = _identify_discovery_candidates(active_universe, cache_store, rs_cache)

    # Use a higher RS floor when a representative cache is available.
    # This avoids fetching tickers that will clearly fail RS_RANK_MIN_PERCENTILE (70) later.
    rs_floor = PASS1_MIN_RS_RANK_WARM if rs_cache else PASS1_MIN_RS_RANK

    # Compute adaptive below-SMA50 thresholds from the current universe distribution.
    # Falls back to fixed constants when insufficient metadata is available.
    _vol_thr, _prox_thr = _compute_below_sma50_thresholds(active_universe, cache_store)

    # Counters for log summary
    _cnt = {"cold": 0, "excl": 0, "price": 0, "vol": 0, "sma50": 0, "prox52": 0, "rs": 0, "pass": 0}

    def _apply_filters(universe):
        result = []
        for ticker in universe:
            is_disc = ticker in discovery
            meta = cache_store.get_meta(ticker)
            if meta is None:
                _cnt["cold"] += 1
                result.append(ticker)       # cold start / new ticker — let I/O phase decide
                continue
            if cache_store.is_excluded(ticker):
                _cnt["excl"] += 1
                continue
            if meta.get("last_close", 0) < PASS1_MIN_PRICE:
                _cnt["price"] += 1
                continue
            if (meta.get("avg_vol_20d", 0) < PASS1_MIN_AVG_VOLUME
                    or meta.get("dollar_vol", 0) < PASS1_MIN_DOLLAR_VOLUME):
                _cnt["vol"] += 1
                continue
            lc  = meta.get("last_close", 0)
            h52 = meta.get("high_52w",   0)
            vr  = meta.get("vol_ratio_5d", 0)
            if not is_disc:
                if meta.get("above_sma50", True):
                    # Uptrend confirmed — only reject deep drawdowns (avoids stocks whose SMA50
                    # is elevated from a distant bull run while the stock is now far off highs)
                    if h52 > 0 and lc / h52 < PASS1_MIN_52W_HIGH_PCT:
                        _cnt["prox52"] += 1
                        continue
                else:
                    # Below SMA50 — allow ONLY if: near recent highs (adaptive prox threshold)
                    # AND a quality signal is present (volume expansion OR strong RS).
                    # This preserves pullback-to-SMA50, VCP coils, and early-stage bases
                    # while filtering clear downtrends (deep drawdown with no buying interest).
                    # Thresholds are adaptive (percentile-based) — see _compute_below_sma50_thresholds().
                    near_high = h52 > 0 and lc / h52 >= _prox_thr
                    vol_ok    = vr  >= _vol_thr
                    rs_below  = rs_cache.get(ticker)
                    rs_ok     = rs_below is not None and rs_below >= PASS1_BELOW_SMA50_MIN_RS
                    if not (near_high and (vol_ok or rs_ok)):
                        _cnt["sma50"] += 1
                        continue
            rs = rs_cache.get(ticker)
            if rs is not None and not is_disc and rs < rs_floor:
                _cnt["rs"] += 1
                continue
            _cnt["pass"] += 1
            result.append(ticker)
        return result

    survivors = _apply_filters(active_universe)
    log.info(
        "Pass 1 filter breakdown: cold=%d excl=%d price=%d vol=%d sma50=%d prox52=%d rs=%d pass=%d",
        _cnt["cold"], _cnt["excl"], _cnt["price"], _cnt["vol"],
        _cnt["sma50"], _cnt["prox52"], _cnt["rs"], _cnt["pass"],
    )

    if len(survivors) > PASS1_MAX_SURVIVORS:
        for rs_step, dv_mult in [(50, 1.0), (50, 1.6), (55, 1.6)]:
            new_survivors = [
                t for t in survivors
                if t in discovery
                or cache_store.get_meta(t) is None  # no metadata: keep for I/O phase
                or (
                    (rs_cache.get(t) or 0) >= rs_step
                    and (cache_store.get_meta(t) or {}).get("dollar_vol", 0) >= PASS1_MIN_DOLLAR_VOLUME * dv_mult
                )
            ]
            log.info(
                "Pass 1 adaptive tighten: RS>=%d dollar_vol*%.1f -> %d survivors",
                rs_step, dv_mult, len(new_survivors),
            )
            survivors = new_survivors
            if len(survivors) <= PASS1_MAX_SURVIVORS:
                break

    thresholds = {
        "vol_thr":   _vol_thr,
        "prox_thr":  _prox_thr,
        "rs_floor":  rs_floor,
        "rs_source": "warm" if rs_cache else "cold",
        "cnt":       dict(_cnt),
    }
    return survivors, discovery, thresholds


async def _fetch(
    ticker: str,
    retry_count: int = 0,
    semaphore: Optional[asyncio.Semaphore] = None,
) -> Optional[pd.DataFrame]:
    """
    Download daily OHLCV for one ticker with retry logic and exponential backoff.

    Returns a cached DataFrame if a fresh entry exists in _ticker_cache:
      - Successful fetches are cached for CACHE_TTL_SUCCESS seconds (4 h).
      - Failed fetches are negatively cached for CACHE_TTL_FAILURE seconds (15 min)
        so transient errors do not cause repeated retries within the same session.

    Semaphore is acquired per-attempt (not held across retries) to prevent
    deadlock when multiple tasks retry simultaneously.

    The ``semaphore`` parameter allows callers that run in an isolated
    ``asyncio.run()`` loop (e.g. the APScheduler morning-scan job) to supply
    their own local semaphore so the module-level ``_semaphore`` (bound to the
    main FastAPI event loop) is never touched from a background thread.
    """
    _sem = semaphore if semaphore is not None else _semaphore
    # ── In-memory TTL cache ───────────────────────────────────────────────────
    # Successive scan runs within the same session reuse cached data, preventing
    # yfinance rate-limiting from causing different tickers to be dropped each run.
    entry = _ticker_cache.get(ticker)
    if entry is not None:
        cached_ts, cached_df = entry
        ttl = CACHE_TTL_SUCCESS if cached_df is not None else CACHE_TTL_FAILURE
        if time.time() - cached_ts < ttl:
            return cached_df

    for attempt in range(retry_count, FETCH_MAX_RETRIES + 1):
        need_retry = False
        backoff_delay = 0.0
        async with _sem:
            loop = asyncio.get_event_loop()
            try:
                def _do_download(t=ticker):
                    """Bind ticker via default arg; use Ticker().history() for thread-safe isolation."""
                    return yf.Ticker(t).history(
                        period=DATA_FETCH_PERIOD,
                        interval="1d",
                        auto_adjust=False,
                    )
                df = await loop.run_in_executor(None, _do_download)

                if df is None or df.empty:
                    if attempt < FETCH_MAX_RETRIES:
                        backoff_delay = FETCH_BACKOFF_BASE * (2 ** attempt)
                        log.warning(
                            "Fetch %s: empty/None data (attempt %d/%d), retrying in %.1fs...",
                            ticker,
                            attempt + 1,
                            FETCH_MAX_RETRIES,
                            backoff_delay,
                        )
                        need_retry = True
                    else:
                        log.warning(
                            "Fetch DROPPED %s: empty/None data after %d retries",
                            ticker, FETCH_MAX_RETRIES,
                        )
                        _ticker_cache[ticker] = (time.time(), None)
                        return None
                else:
                    # Flatten MultiIndex (newer yfinance versions)
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    # Deduplicate columns (yfinance can produce duplicates)
                    if df.columns.duplicated().any():
                        df = df.loc[:, ~df.columns.duplicated()]
                    _ticker_cache[ticker] = (time.time(), df)
                    return df

            except Exception as exc:
                is_rate_limit = "RateLimit" in type(exc).__name__ or "Too Many" in str(exc)
                if attempt < FETCH_MAX_RETRIES:
                    # Rate limit errors need a much longer pause than generic errors
                    backoff_delay = (30.0 * (2 ** attempt)) if is_rate_limit else (FETCH_BACKOFF_BASE * (2 ** attempt))
                    log.warning(
                        "Fetch %s: %s (attempt %d/%d), retrying in %.0fs...",
                        ticker,
                        type(exc).__name__,
                        attempt + 1,
                        FETCH_MAX_RETRIES,
                        backoff_delay,
                    )
                    need_retry = True
                else:
                    log.warning(
                        "Fetch DROPPED %s: %s after %d retries",
                        ticker, type(exc).__name__, FETCH_MAX_RETRIES,
                    )
                    _ticker_cache[ticker] = (time.time(), None)
                    return None
        # Semaphore released — sleep outside before next attempt
        if need_retry:
            await asyncio.sleep(backoff_delay)
    _ticker_cache[ticker] = (time.time(), None)
    return None


# ────────────────────────────────────────────────────────────────────────────
# Price-cache pre-warmer
# ────────────────────────────────────────────────────────────────────────────

async def _prewarm_price_cache() -> None:
    """Download 1y OHLCV for every universe ticker and populate _ticker_cache.

    Called in two places:
      1. Server startup (background task) — so the first manual scan is instant.
      2. 9:15 AM ET scheduled job — refreshes the cache before market open, so
         morning scans hit warm data even if the server has been running since
         before the previous session's cache expired (TTL = 4 h).

    Only fetches tickers that are missing or stale; a warm cache is a no-op.
    """
    tickers = [t for t in ACTIVE_UNIVERSE if t != "SPY"]
    if not tickers:
        return

    now = time.time()
    uncached = [
        t for t in tickers
        if t not in _ticker_cache
        or now - _ticker_cache[t][0] >= CACHE_TTL_SUCCESS
    ]

    if not uncached:
        log.info("[prewarm] Price cache already warm (%d tickers) — skipping.", len(tickers))
        return

    log.info("[prewarm] Warming price cache: %d/%d tickers uncached…", len(uncached), len(tickers))
    t0   = time.time()
    loop = asyncio.get_running_loop()
    batches = [
        uncached[i: i + BULK_DOWNLOAD_BATCH_SIZE]
        for i in range(0, len(uncached), BULK_DOWNLOAD_BATCH_SIZE)
    ]

    ok = 0
    for i, batch in enumerate(batches):
        try:
            batch_data = await loop.run_in_executor(
                None, lambda b=batch: _batch_download_sync(b)
            )
            for ticker, df in batch_data.items():
                _ticker_cache[ticker] = (time.time(), df)
            ok += len(batch_data)
            log.info("[prewarm] Batch %d/%d done (%d ok)", i + 1, len(batches), len(batch_data))
        except Exception as exc:
            log.warning("[prewarm] Batch %d/%d failed: %s", i + 1, len(batches), exc)

    log.info("[prewarm] Complete — %d tickers cached in %.1fs", ok, time.time() - t0)


def run_prewarm_job() -> None:
    """APScheduler-compatible sync wrapper around _prewarm_price_cache.

    Scheduled at 9:15 AM ET — 15 minutes before market open — so the
    first morning scan is instant regardless of when the server last ran.
    """
    log.info("[scheduler] 9:15 AM pre-warm job starting…")
    try:
        asyncio.run(_prewarm_price_cache())
    except Exception as exc:
        log.error("[scheduler] Pre-warm job failed: %s", exc)


# ────────────────────────────────────────────────────────────────────────────
# Background scan worker
# ────────────────────────────────────────────────────────────────────────────

async def _run_scan(
    scan_ts: str,
    tickers: List[str],
    force: bool = False,
    dry_run: bool = False,
    semaphore: Optional[asyncio.Semaphore] = None,
) -> None:
    """
    Full scan pipeline:
      Engine 0 → (if bullish) Engine 1 → Engine 2 + Engine 3
    Results written to SQLite; frontend reads from DB.

    The optional ``semaphore`` parameter is forwarded to ``_fetch`` so that
    callers running inside an isolated ``asyncio.run()`` event loop (e.g. the
    APScheduler morning-scan job) can supply their own loop-local semaphore
    without touching the module-level one used by the FastAPI event loop.
    """
    global _scan_state
    scan_start_time = time.time()

    log.info("▶ Scan started  ts=%s  tickers=%d", scan_ts, len(tickers))
    _scan_state.update(
        in_progress=True,
        progress=0,
        total=len(tickers),
        started_at=scan_ts,
        last_error=None,
        engine_stats={
            "e0": {},
            "e1": {"zones_saved": 0},
            "e2": {"vcp": 0},
            "watchlist": {"res_breakout_near": 0, "pullback_approaching": 0},
            "e3": {"pullback": 0, "relaxed": 0},
            "e5": {"cup_handle": 0, "flat_base": 0},
            "e6": {"res_breakout": 0},
            "e7": {"options_catalyst": 0},
            "e8": {"htf": 0},
            "e9": {"lce": 0},
            "total_tickers": 0,
            "total_duration_s": 0.0,
            "forced": force,
            "dry_run": dry_run,
            "timing": {
                "regime_s": 0.0,
                "spy_fetch_s": 0.0,
                "prefetch_s": 0.0,
                "process_s": 0.0,
                "db_s": 0.0,
                "total_s": 0.0,
                "pass1_filter_s": 0.0,
                "fetch_s": 0.0,
                "rs_cache_s": 0.0,
                "pass2_s": 0.0,
            },
            "filtered": {
                "liquidity":        0,
                "earnings":         0,
                "insufficient_data": 0,
                "vitality":         0,
                "rs_rank_gate":     0,
                "rs_score_gate":    0,
                "ind_failed":       0,
            },
            "pass1_survivors": 0,
            "pass1_thresholds": {},
            "cache_hit_rate": 0.0,
        },
        dry_run_setups=None,
    )

    # ── Rebuild universe at most once per 24 h (SEC EDGAR → pre-filters → save) ──
    # Skip when:
    #   • specific tickers passed via ?tickers= debug override
    #   • active_universe.json is less than 24 h old (use cached list)
    import os as _os, time as _time
    _universe_age_h = (
        (_time.time() - _os.path.getmtime(UNIVERSE_FILE)) / 3600
        if _os.path.exists(UNIVERSE_FILE) else 999
    )
    _universe_stale = _universe_age_h >= 48
    global ACTIVE_UNIVERSE, SECTORS
    if tickers is ACTIVE_UNIVERSE and _universe_stale:
        log.info("Universe is %.1fh old — rebuilding via SEC EDGAR + yfinance pre-filters…", _universe_age_h)
        _scan_state["rebuilding_universe"] = True
        loop = asyncio.get_running_loop()
        try:
            universe_dict = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: build_universe(
                        min_atr_pct=MIN_ATR_PCT,
                    ),
                ),
                timeout=1200,  # 20-minute hard cap — prevents scan from hanging indefinitely
            )
            if universe_dict["tickers"]:
                save_universe(universe_dict, UNIVERSE_FILE)
                new_tickers = universe_dict["tickers"]
                if len(new_tickers) > MAX_TICKERS_PER_SCAN:
                    log.warning(
                        "Rebuilt universe has %d tickers, capping to %d",
                        len(new_tickers), MAX_TICKERS_PER_SCAN,
                    )
                    new_tickers = new_tickers[:MAX_TICKERS_PER_SCAN]
                ACTIVE_UNIVERSE = new_tickers
                SECTORS = universe_dict["sectors"]
                tickers = ACTIVE_UNIVERSE
                _scan_state["rebuilding_universe"] = False
                log.info(
                    "Universe rebuilt: %d tickers (price≥$10, vol≥500K, ATR%%≥%.1f%%)",
                    len(tickers),
                    MIN_ATR_PCT,
                )
            else:
                log.warning("Universe rebuild returned 0 tickers — keeping existing universe")
                _scan_state["rebuilding_universe"] = False
        except asyncio.TimeoutError:
            log.error(
                "Universe rebuild timed out after 20 min — proceeding with existing %d-ticker list",
                len(tickers),
            )
            _scan_state["rebuilding_universe"] = False
        except Exception:
            log.exception("Universe rebuild failed — proceeding with existing universe")
            _scan_state["rebuilding_universe"] = False
    elif tickers is ACTIVE_UNIVERSE:
        log.info("Universe is %.1fh old — using cached list (%d tickers)", _universe_age_h, len(tickers))

    # Update total now that tickers may have been replaced by the fresh universe
    _scan_state["total"] = len(tickers)

    try:
        if not dry_run:
            await save_scan_run(DB_PATH, scan_ts)

        loop = asyncio.get_running_loop()

        # ── SPY data (consolidated single fetch for 3m return + RS Line) ──
        # Fetched before per-ticker processing; used for RS Line calculations.
        spy_3m_return = 0.0
        spy_df_full = None
        spy_fetch_start = time.time()
        try:
            spy_df_full = await _fetch("SPY", semaphore=semaphore)
            if spy_df_full is not None and len(spy_df_full) >= MIN_CANDLES_FOR_RS:
                log.info("SPY data fetched: %d days for RS Line", len(spy_df_full))
                # Extract 3-month return from the consolidated fetch
                if len(spy_df_full) >= DAYS_3_MONTHS:
                    adj_col = "Adj Close" if "Adj Close" in spy_df_full.columns else "Close"
                    spy_close = spy_df_full[adj_col]
                    spy_3m_return = float(
                        spy_close.iloc[-1] / spy_close.iloc[-DAYS_3_MONTHS] - 1
                    )
                    log.info("SPY 3-month return: %.2f%%", spy_3m_return * 100)
        except Exception as exc:
            log.warning("Could not fetch SPY data for RS/3m return: %s", exc)

        spy_fetch_time = time.time() - spy_fetch_start
        log.info("SPY fetch completed  [%.1fs]", spy_fetch_time)
        _scan_state["engine_stats"]["timing"]["spy_fetch_s"] = round(spy_fetch_time, 2)

        # ── Compute universe breadth from cache store metadata ────────────
        _breadth_start = time.time()
        breadth_pct, hl_ratio = _compute_breadth_from_metadata(tickers, _cache_store)
        log.info(
            "Breadth from metadata: %.1f%% above SMA50  H/L: %.2f  [%.2fs]",
            breadth_pct * 100, hl_ratio, time.time() - _breadth_start,
        )

        # ── RS rank cache: refresh if near-stale (>20h) before Pass 1 ────
        _rs_cache_start = time.time()
        from scoring import _load_rs_cache as _lrc, _rs_cache_age_seconds, _rs_cache_valid
        _raw_rs_cache = _lrc()
        if _raw_rs_cache and _rs_cache_age_seconds(_raw_rs_cache) > RS_RANK_CACHE_REFRESH_THRESHOLD:
            log.info("RS cache is >20h old — refreshing before Pass 1")
            compute_rs_rank_map(_ticker_cache, tickers, spy_df_full, sample_size=len(tickers))
            _raw_rs_cache = _lrc()   # reload the freshly written file
        _scan_state["engine_stats"]["timing"]["rs_cache_s"] = round(time.time() - _rs_cache_start, 2)
        # Only use the RS cache for Pass 1 if it is representative (≥ RS_RANK_CACHE_MIN_TICKERS).
        # An incomplete cache (e.g. from a debug run with 3 tickers) would silently
        # mis-classify all real tickers as having no RS data while {A,B,C} get spurious ranks.
        if _rs_cache_valid(_raw_rs_cache):
            _rs_for_pass1 = {k: v for k, v in _raw_rs_cache.items() if not k.startswith("_")}
            log.info("Pass 1 RS: using cached map (%d tickers)", len(_rs_for_pass1))
        else:
            _rs_for_pass1 = {}
            log.warning(
                "Pass 1 RS: cache invalid or too small — RS filter bypassed for this scan "
                "(cache will be recomputed post-I/O)"
            )

        # ── PASS 1: fast metadata filter ──────────────────────────────────
        _pass1_start = time.time()
        _survivors, _discovery_tickers, _p1_thresholds = _pass1_filter(tickers, _cache_store, _rs_for_pass1)
        _pass1_time = round(time.time() - _pass1_start, 2)
        _scan_state["engine_stats"]["timing"]["pass1_filter_s"] = _pass1_time
        _scan_state["engine_stats"]["pass1_survivors"] = len(_survivors)
        _scan_state["engine_stats"]["pass1_thresholds"] = _p1_thresholds
        log.info(
            "Pass 1 complete: %d → %d survivors  [%.2fs]",
            len(tickers), len(_survivors), _pass1_time,
        )

        # ── I/O phase: incremental fetch for survivors only ───────────────
        _fetch_start = time.time()
        await _run_io_phase(_survivors, _cache_store, semaphore or _semaphore)
        _fetch_time = round(time.time() - _fetch_start, 2)
        _scan_state["engine_stats"]["timing"]["fetch_s"] = _fetch_time
        log.info("Incremental fetch complete  [%.1fs]", _fetch_time)

        # Populate _ticker_cache from _cache_store for downstream compatibility
        _now = time.time()
        for _t in _survivors:
            _df = _cache_store.get(_t)
            if _df is not None:
                _ticker_cache[_t] = (_now, _df)

        # ── RS rank map + top sectors (post-I/O, using freshly fetched data) ──
        rs_rank_start = time.time()
        _rs_rank_map = compute_rs_rank_map(_ticker_cache, _survivors, spy_df_full, sample_size=len(_survivors))
        _top_sectors = compute_top_sectors(
            _ticker_cache, _survivors, SECTORS, spy_df_full, top_n=TOP_SECTORS_N
        )
        global _last_rs_rank_map, _last_top_sectors
        _last_rs_rank_map = _rs_rank_map
        _last_top_sectors = _top_sectors
        log.info(
            "RS rank map: %d tickers ranked  top_sectors=%s  [%.1fs]",
            len(_rs_rank_map), _top_sectors, time.time() - rs_rank_start,
        )
        if _rs_rank_map:
            _rs_vals = sorted(_rs_rank_map.values())
            _n = len(_rs_vals)
            _rs_mean   = sum(_rs_vals) / _n
            _rs_median = _rs_vals[_n // 2]
            _rs_p25    = _rs_vals[_n // 4]
            _rs_p75    = _rs_vals[_n * 3 // 4]
            _rs_below60 = sum(1 for v in _rs_vals if v < 60)
            _rs_below70 = sum(1 for v in _rs_vals if v < 70)
            log.info(
                "RS distribution: mean=%.1f  median=%.1f  P25=%.1f  P75=%.1f  "
                "below60=%d (%.0f%%)  below70=%d (%.0f%%)",
                _rs_mean, _rs_median, _rs_p25, _rs_p75,
                _rs_below60, _rs_below60 / _n * 100,
                _rs_below70, _rs_below70 / _n * 100,
            )
        else:
            log.warning(
                "RS rank map is empty (SPY data unavailable?) — "
                "RS rank gate will be bypassed for all tickers this scan"
            )
        if _discovery_tickers:
            log.info(
                "Discovery layer: %d candidate(s) (RS 60-70, near-high, vol expansion)",
                len(_discovery_tickers),
            )

        # ── Engine 0: Multi-factor regime (computed after prefetch for breadth) ──
        regime_start = time.time()
        regime = await loop.run_in_executor(
            None, check_market_regime, breadth_pct, hl_ratio
        )
        regime_time = time.time() - regime_start
        if not dry_run:
            await save_regime(DB_PATH, scan_ts, regime)
        log.info(
            "Engine 0: %s  score=%d  (SPY=%.2f  EMA20=%.2f  SMA50=%.2f)  "
            "breadth=%.1f%%  VIX=%.1f  [%.1fs]",
            regime["regime"],
            regime["regime_score"],
            regime["spy_close"],
            regime["spy_20ema"],
            regime.get("spy_sma50", 0.0),
            breadth_pct * 100,
            regime.get("vix", 0.0),
            regime_time,
        )
        _scan_state["engine_stats"]["e0"] = {
            "spy_close":    round(regime["spy_close"], 2),
            "spy_ema20":    round(regime["spy_20ema"], 2),
            "regime_score": regime["regime_score"],
            "is_bullish":   regime["is_bullish"],
            "duration_s":   round(regime_time, 1),
            "factors":      regime.get("factors", {}),
        }
        _scan_state["engine_stats"]["timing"]["regime_s"] = round(regime_time, 2)

        if not regime["is_bullish"]:
            log.info(
                "Regime DEFENSIVE (score=%d < %d) — all engines active; "
                "scoring applies regime penalty (0 pts) and lower score gate (%d)%s",
                regime["regime_score"], REGIME_SELECTIVE_THRESHOLD,
                MIN_SETUP_SCORE_DEFENSIVE,
                "  [force=True]" if force else "",
            )

        # ── Load earnings cache from disk (Task 1) ────────────────────────────
        global _earnings_cache
        _earnings_cache = _load_earnings_cache()
        log.info("Earnings cache loaded: %d entries", len(_earnings_cache))

        # ── Per-ticker processing ─────────────────────────────────────────
        # Collect setups instead of saving individually for batch optimization
        collected_setups: List[Dict] = []
        collected_zones: Dict[str, List[Dict]] = {}   # ticker → zones, batch-saved after loop
        dropped_tickers: List[str] = []  # Track tickers that failed all retries
        vcp_count = 0
        pb_count = 0
        base_count = 0
        res_count  = 0
        opt_count  = 0
        htf_count  = 0
        lce_count  = 0
        liquidity_filtered = 0
        earnings_filtered  = 0
        process_start_time = time.time()

        async def _process(ticker: str, idx: int) -> None:
            nonlocal vcp_count, pb_count, base_count, res_count, opt_count, htf_count, lce_count, dropped_tickers, liquidity_filtered, earnings_filtered

            try:
                # ── Data Integrity Check ────────────────────────────────────
                # Skip tickers with empty/delisted data immediately
                df = await _fetch(ticker, semaphore=semaphore)
                if df is None or len(df) < MIN_CANDLES_FOR_ANALYSIS:
                    if df is None:
                        dropped_tickers.append(ticker)  # Record as dropped
                    _scan_state["engine_stats"]["filtered"]["insufficient_data"] += 1
                    log.debug("Skipped %s: insufficient data", ticker)
                    return

                # Deduplicate columns (belt-and-suspenders after _fetch)
                if df.columns.duplicated().any():
                    df = df.loc[:, ~df.columns.duplicated()]

                # Check for empty Close column or all-NaN values
                close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
                if close_col not in df.columns:
                    _scan_state["engine_stats"]["filtered"]["insufficient_data"] += 1
                    log.debug("Skipped %s: no valid price data", ticker)
                    return
                close_series = df[close_col]
                if isinstance(close_series, pd.DataFrame):
                    close_series = close_series.iloc[:, 0]
                if close_series.isna().all():
                    _scan_state["engine_stats"]["filtered"]["insufficient_data"] += 1
                    log.debug("Skipped %s: all-NaN price data", ticker)
                    return

                # ── Price Action Vitality — skip zombie / buyout-flatline stocks ──
                if not is_price_vital(df):
                    _scan_state["engine_stats"]["filtered"]["vitality"] += 1
                    log.debug(
                        "Skipped %s: flatline/zombie stock "
                        "(10-day H-L range < 2%% of high)",
                        ticker,
                    )
                    return

                # ── Task 8: RS Rank gate ──────────────────────────────────────────
                # Restored to RS_RANK_MIN_PERCENTILE (70). The missing-BRK issue
                # was the empty RS rank cache bug (fixed in scoring.py), not this
                # threshold. Stocks approaching a breakout have RS > 70 by nature.
                # Bypass: empty map (SPY fail), force mode, discovery candidates.
                if _rs_rank_map and not force:
                    _ticker_rs_rank = _rs_rank_map.get(ticker)
                    if _ticker_rs_rank is None or _ticker_rs_rank < RS_RANK_MIN_PERCENTILE:
                        if ticker not in _discovery_tickers:
                            _scan_state["engine_stats"]["filtered"]["rs_rank_gate"] += 1
                            log.debug(
                                "Skipped %s: RS rank %.1f < %.0f (threshold)",
                                ticker,
                                _ticker_rs_rank if _ticker_rs_rank is not None else 0.0,
                                RS_RANK_MIN_PERCENTILE,
                            )
                            return

                # ── Earnings Blackout — checked BEFORE compute_indicators ─────────
                # Earnings check needs only _earnings_cache (loaded before the loop).
                # Moving it here avoids a full compute_indicators call for blackout tickers.
                blackout = await loop.run_in_executor(
                    None, _check_earnings_blackout_sync, ticker
                )
                if blackout:
                    earnings_filtered += 1
                    _scan_state["engine_stats"]["filtered"]["earnings"] += 1
                    log.debug("Skipped %s: earnings within %d days", ticker, EARNINGS_BLACKOUT_DAYS)
                    return

                # ── Centralized Indicator Engine (Task 6) ────────────────────────
                ind: Optional[TickerIndicators] = await loop.run_in_executor(
                    None, compute_indicators, df, spy_df_full
                )
                if ind is None:
                    _scan_state["engine_stats"]["filtered"]["ind_failed"] += 1
                    log.debug("Skipped %s: insufficient data for indicators", ticker)
                    return

                # ── Liquidity Gate (Task 7) ───────────────────────────────────────
                if (
                    ind.avg_volume_50d < LIQUIDITY_MIN_AVG_VOLUME
                    or ind.dollar_volume < LIQUIDITY_MIN_DOLLAR_VOLUME
                ):
                    liquidity_filtered += 1
                    _scan_state["engine_stats"]["filtered"]["liquidity"] += 1
                    log.debug(
                        "Skipped %s: illiquid (vol50d=%.0f  $vol=%.1fM)",
                        ticker, ind.avg_volume_50d, ind.dollar_volume / 1_000_000,
                    )
                    return

                # ── Use pre-computed RS values from indicator engine ───────────────
                rs_ratio    = ind.rs_ratio
                rs_52w_high = ind.rs_52w_high
                rs_blue_dot = ind.rs_blue_dot
                rs_score    = ind.rs_score

                # ── RS Score gate (mirrors backtest_engine.py line 837) ───────────
                # Backtest only backtests bars where rs_score >= rs_threshold (0.088).
                # Live scanner must apply the same gate to stay consistent.
                # Bypassed in force/dev mode so everything is visible for debugging.
                if not force and rs_score < _LIVE_PARAMS.rs_threshold:
                    _scan_state["engine_stats"]["filtered"]["rs_score_gate"] += 1
                    log.debug(
                        "Skipped %s: rs_score=%.4f < rs_threshold=%.4f",
                        ticker, rs_score, _LIVE_PARAMS.rs_threshold,
                    )
                    return

                # ── S/R Zone calculation (uses full weekly resample, stays separate) ──
                zones: List[Dict] = []
                try:
                    zones = await loop.run_in_executor(None, calculate_sr_zones, ticker, df)
                except Exception as exc:
                    log.warning("S/R zone calculation failed for %s: %s", ticker, exc)

                if zones:
                    collected_zones[ticker] = zones   # batch-saved after processing loop
                    _scan_state["engine_stats"]["e1"]["zones_saved"] += 1

                # Detect trendline early (used by VCP follow-up, near-breakout, and pullback)
                tl = await loop.run_in_executor(None, detect_trendline, ticker, df)

                # ── Engine 2: VCP (all regimes) ──────────────────────────────────
                vcp = None
                if True:
                    vcp = await loop.run_in_executor(
                        None, scan_vcp, ticker, df, zones, spy_3m_return,
                        rs_ratio, rs_52w_high, rs_blue_dot, rs_score
                    )
                    if vcp:
                        # Sanitize VCP output: ensure all numeric fields are proper floats
                        try:
                            vcp["entry"] = float(vcp.get("entry", 0.0))
                            vcp["stop_loss"] = float(vcp.get("stop_loss", 0.0))
                            vcp["take_profit"] = float(vcp.get("take_profit", 0.0))
                            vcp["rr"] = float(vcp.get("rr", 2.0))
                        except (ValueError, TypeError) as conv_err:
                            log.warning("VCP conversion failed for %s: %s", ticker, conv_err)
                            return

                        # Add sector to setup and collect for batch save
                        vcp["sector"] = SECTORS.get(ticker, "Unknown")
                        collected_setups.append(vcp)
                        vcp_count += 1
                        _scan_state["engine_stats"]["e2"]["vcp"] += 1

                        setup_type = "RS LEAD" if vcp.get("is_rs_lead") else "VCP"
                        log.info("  %s      %-6s  entry=%.2f", setup_type, ticker, vcp["entry"])

                # ── Near-breakout / Watchlist (always runs — useful even in DEFENSIVE) ──
                # ── Watchlist: RES_BREAKOUT approaching ──────────────────────────
                try:
                    wl_res = await loop.run_in_executor(
                        None, scan_res_breakout_near, ticker, df, zones
                    )
                    if wl_res:
                        wl_res["sector"] = SECTORS.get(ticker, "Unknown")
                        wl_res["rs_blue_dot"] = rs_blue_dot
                        collected_setups.append(wl_res)
                        _scan_state["engine_stats"]["watchlist"]["res_breakout_near"] += 1
                        log.info("  WL_BRK   %-6s  dist=%.1f%%", ticker, wl_res.get("distance_pct", 0))
                except Exception as wl_exc:
                    log.warning("WL res_breakout_near failed for %s: %s", ticker, wl_exc)

                # ── Watchlist: PULLBACK approaching ───────────────────────────────
                try:
                    wl_pb = await loop.run_in_executor(
                        None, scan_pullback_approaching, ticker, df, zones, tl, rs_score
                    )
                    if wl_pb:
                        wl_pb["sector"] = SECTORS.get(ticker, "Unknown")
                        wl_pb["rs_blue_dot"] = rs_blue_dot
                        collected_setups.append(wl_pb)
                        _scan_state["engine_stats"]["watchlist"]["pullback_approaching"] += 1
                        log.info("  WL_PB    %-6s  sup=%.2f  src=%s", ticker, wl_pb.get("support_level", 0), wl_pb.get("support_source", ""))
                except Exception as wl_exc:
                    log.warning("WL pullback_approaching failed for %s: %s", ticker, wl_exc)

                # ── Engine 3: Pullback (always runs — scoring handles regime quality) ──
                if True:
                    _regime_str = regime.get("regime", "SELECTIVE")
                    pb, pb_score = await loop.run_in_executor(
                        None, scan_pullback_scored, ticker, df, zones, _LIVE_PARAMS, tl, rs_score, _regime_str
                    )
                    _pb_final = pb_score * _LIVE_PARAMS.pullback_weight
                    if pb and _pb_final >= _LIVE_PARAMS.score_threshold:
                        # Sanitize pullback output
                        try:
                            pb["entry"] = float(pb.get("entry", 0.0))
                            pb["stop_loss"] = float(pb.get("stop_loss", 0.0))
                            pb["take_profit"] = float(pb.get("take_profit", 0.0))
                            pb["rr"] = float(pb.get("rr", 2.0))
                        except (ValueError, TypeError) as conv_err:
                            log.warning("Pullback conversion failed for %s: %s", ticker, conv_err)
                            return

                        _apply_tp_multiple(pb, _LIVE_PARAMS)
                        pb["sector"]   = SECTORS.get(ticker, "Unknown")
                        pb["rs_score"] = rs_score
                        pb["vol_ratio"] = pb.get("volume_ratio", pb.get("vol_ratio", 0.0))
                        pb["recommended_execution"] = "Enter at next market open (T+1)"
                        collected_setups.append(pb)
                        pb_count += 1
                        _scan_state["engine_stats"]["e3"]["pullback"] += 1
                        log.info("  PULLBACK %-6s  entry=%.2f  score=%.2f", ticker, pb["entry"], pb_score)
                    else:
                        # Only check relaxed if no strict pullback found
                        try:
                            _regime_str = regime.get("regime", "SELECTIVE")
                            pb_relaxed = await loop.run_in_executor(
                                None, lambda: scan_relaxed_pullback(ticker, df, zones, tl, rs_score, params=_LIVE_PARAMS, regime=_regime_str)
                            )
                            if pb_relaxed:
                                # Sanitize relaxed pullback output
                                try:
                                    pb_relaxed["entry"] = float(pb_relaxed.get("entry", 0.0))
                                    pb_relaxed["stop_loss"] = float(pb_relaxed.get("stop_loss", 0.0))
                                    pb_relaxed["take_profit"] = float(pb_relaxed.get("take_profit", 0.0))
                                    pb_relaxed["rr"] = float(pb_relaxed.get("rr", 2.0))
                                except (ValueError, TypeError) as conv_err:
                                    log.warning("Relaxed pullback conversion failed for %s: %s", ticker, conv_err)
                                    return

                                _apply_tp_multiple(pb_relaxed, _LIVE_PARAMS)
                                pb_relaxed["sector"] = SECTORS.get(ticker, "Unknown")
                                pb_relaxed["recommended_execution"] = "Enter at next market open (T+1)"
                                collected_setups.append(pb_relaxed)
                                pb_count += 1
                                _scan_state["engine_stats"]["e3"]["relaxed"] += 1
                                log.info("  PULLBACK %-6s  entry=%.2f (relaxed)", ticker, pb_relaxed["entry"])
                        except Exception as pb_rel_exc:
                            log.warning("Relaxed pullback check failed for %s: %s", ticker, pb_rel_exc)

                # Engine 5: Base pattern (Cup & Handle / Flat Base)
                try:
                    base = await loop.run_in_executor(
                        None, scan_base_pattern, ticker, df,
                        spy_3m_return, rs_ratio, rs_52w_high, rs_blue_dot, rs_score, zones, _LIVE_PARAMS
                    )
                    if base:
                        try:
                            base["entry"] = float(base.get("entry", 0.0))
                            base["stop_loss"] = float(base.get("stop_loss", 0.0))
                            base["take_profit"] = float(base.get("take_profit", 0.0))
                            base["rr"] = float(base.get("rr", 2.0))
                        except (ValueError, TypeError) as conv_err:
                            log.warning("Base pattern conversion failed for %s: %s", ticker, conv_err)
                        else:
                            _apply_tp_multiple(base, _LIVE_PARAMS)
                            base["sector"]       = SECTORS.get(ticker, "Unknown")
                            base["rs_score"]     = rs_score
                            base["rs_blue_dot"]  = rs_blue_dot
                            base["rs_ratio"]     = rs_ratio
                            _vr_base = base.get("volume_ratio", base.get("vol_ratio", 0.0))
                            base["vol_ratio"]    = _vr_base
                            base["is_vol_surge"] = _vr_base >= 1.5
                            base["recommended_execution"] = "Enter at next market open (T+1)"
                            collected_setups.append(base)
                            base_count += 1
                            if base.get("base_type") == "CUP_HANDLE":
                                _scan_state["engine_stats"]["e5"]["cup_handle"] += 1
                            else:
                                _scan_state["engine_stats"]["e5"]["flat_base"] += 1
                            log.info("  BASE     %-6s  %s  Q=%d  entry=%.2f",
                                     ticker, base.get("base_type", ""), base.get("quality_score", 0), base["entry"])
                except Exception as base_exc:
                    log.warning("Base pattern check failed for %s: %s", ticker, base_exc)

                # Engine 6: Resistance breakout (always runs — scoring handles regime quality)
                _brk_regime_ok = True
                if zones and _brk_regime_ok:
                    try:
                        res_brk = await loop.run_in_executor(
                            None, scan_resistance_breakout, ticker, df, zones, False, _LIVE_PARAMS
                        )
                        if res_brk:
                            try:
                                res_brk["entry"]      = float(res_brk.get("entry", 0.0))
                                res_brk["stop_loss"]  = float(res_brk.get("stop_loss", 0.0))
                                res_brk["take_profit"]= float(res_brk.get("take_profit", 0.0))
                                res_brk["rr"]         = float(res_brk.get("rr", 2.0))
                            except (ValueError, TypeError) as conv_err:
                                log.warning("ResBreakout conversion failed for %s: %s", ticker, conv_err)
                            else:
                                _apply_tp_multiple(res_brk, _LIVE_PARAMS)
                                res_brk["sector"]       = SECTORS.get(ticker, "Unknown")
                                # Inject RS + volume fields not computed by engine6
                                res_brk["rs_score"]     = rs_score
                                res_brk["rs_blue_dot"]  = rs_blue_dot
                                res_brk["rs_ratio"]     = rs_ratio
                                # vol_ratio alias: engine6 uses "volume_ratio", frontend reads "vol_ratio"
                                _vr = res_brk.get("volume_ratio", 0.0)
                                res_brk["vol_ratio"]    = _vr
                                res_brk["is_vol_surge"] = _vr >= 1.5
                                # Gap-chase protection (mirrors backtest_engine.py brk_gap_pct filter).
                                # Flag if current close is already beyond the gap threshold so the
                                # trader knows not to chase an extended entry.
                                _zone_upper  = float(res_brk.get("zone_upper", res_brk.get("resistance_level", 0.0)))
                                _last_close  = float(df["Close"].iloc[-1]) if len(df) > 0 else 0.0
                                _gap_thresh  = _zone_upper * (1.0 + getattr(_LIVE_PARAMS, "brk_gap_pct", 0.01021))
                                if _zone_upper > 0 and _last_close > _gap_thresh:
                                    res_brk["gap_risk"]      = True
                                    res_brk["signal_status"] = "EXTENDED — do not chase"
                                else:
                                    res_brk["gap_risk"]      = False
                                    res_brk["signal_status"] = "valid"
                                res_brk["recommended_execution"] = "Enter at next market open (T+1)"
                                collected_setups.append(res_brk)
                                res_count += 1
                                _scan_state["engine_stats"]["e6"]["res_breakout"] += 1
                                log.info("  RES_BRK  %-6s  level=%.2f  vol=×%.1f  rs=%.3f",
                                         ticker, res_brk.get("resistance_level", 0),
                                         _vr, rs_score)
                    except Exception as res_exc:
                        log.warning("ResBreakout check failed for %s: %s", ticker, res_exc)

                # Engine 8: High Tight Flag
                if zones:
                    try:
                        htf = await loop.run_in_executor(
                            None, scan_htf, ticker, df, zones
                        )
                        if htf:
                            try:
                                htf["entry"]      = float(htf.get("entry", 0.0))
                                htf["stop_loss"]  = float(htf.get("stop_loss", 0.0))
                                htf["take_profit"]= float(htf.get("take_profit", 0.0))
                                htf["rr"]         = float(htf.get("rr", 2.0))
                            except (ValueError, TypeError) as conv_err:
                                log.warning("HTF conversion failed for %s: %s", ticker, conv_err)
                            else:
                                _apply_tp_multiple(htf, _LIVE_PARAMS)
                                htf["sector"]       = SECTORS.get(ticker, "Unknown")
                                htf["rs_score"]     = rs_score
                                htf["rs_blue_dot"]  = rs_blue_dot
                                htf["rs_ratio"]     = rs_ratio
                                _vr_htf = htf.get("volume_ratio", htf.get("vol_ratio", 0.0))
                                htf["vol_ratio"]    = _vr_htf
                                htf["is_vol_surge"] = _vr_htf >= 1.5
                                htf["recommended_execution"] = "Enter at next market open (T+1)"
                                collected_setups.append(htf)
                                htf_count += 1
                                _scan_state["engine_stats"]["e8"]["htf"] += 1
                                log.info("  HTF      %-6s  runup=%.0f%%  flag=%dd  vol=×%.1f",
                                         ticker, htf.get("runup_pct", 0),
                                         htf.get("flag_bars", 0), htf.get("volume_ratio", 0))
                    except Exception as htf_exc:
                        log.warning("HTF check failed for %s: %s", ticker, htf_exc)

                # Engine 9: Low Cheat Entry
                if zones:
                    try:
                        lce = await loop.run_in_executor(
                            None, scan_lce, ticker, df, zones
                        )
                        if lce:
                            try:
                                lce["entry"]      = float(lce.get("entry", 0.0))
                                lce["stop_loss"]  = float(lce.get("stop_loss", 0.0))
                                lce["take_profit"]= float(lce.get("take_profit", 0.0))
                                lce["rr"]         = float(lce.get("rr", 2.0))
                            except (ValueError, TypeError) as conv_err:
                                log.warning("LCE conversion failed for %s: %s", ticker, conv_err)
                            else:
                                _apply_tp_multiple(lce, _LIVE_PARAMS)
                                lce["sector"]       = SECTORS.get(ticker, "Unknown")
                                lce["rs_score"]     = rs_score
                                lce["rs_blue_dot"]  = rs_blue_dot
                                lce["rs_ratio"]     = rs_ratio
                                _vr_lce = lce.get("volume_ratio", lce.get("vol_ratio", 0.0))
                                lce["vol_ratio"]    = _vr_lce
                                lce["is_vol_surge"] = _vr_lce >= 1.5
                                lce["recommended_execution"] = "Enter at next market open (T+1)"
                                collected_setups.append(lce)
                                lce_count += 1
                                _scan_state["engine_stats"]["e9"]["lce"] += 1
                                log.info("  LCE      %-6s  dist=%.1f%%  vol=×%.2f",
                                         ticker, lce.get("distance_to_resistance_pct", 0),
                                         lce.get("volume_ratio", 0))
                    except Exception as lce_exc:
                        log.warning("LCE check failed for %s: %s", ticker, lce_exc)

                # Engine 7: Options Catalyst (not gated by market regime)
                # Wrapped with IO semaphore: options chain fetch is a live HTTP call
                # and must be rate-limited like all other yfinance requests.
                try:
                    async with _semaphore:
                        opt = await loop.run_in_executor(
                            None, scan_options_catalyst, ticker, df
                        )
                    if opt:
                        try:
                            opt["entry"]      = float(opt.get("entry", 0.0))
                            opt["stop_loss"]  = float(opt.get("stop_loss", 0.0))
                            opt["take_profit"]= float(opt.get("take_profit", 0.0))
                            opt["rr"]         = float(opt.get("rr", 2.0))
                        except (ValueError, TypeError) as conv_err:
                            log.warning("Options conversion failed for %s: %s", ticker, conv_err)
                        else:
                            opt["sector"] = SECTORS.get(ticker, "Unknown")
                            collected_setups.append(opt)
                            opt_count += 1
                            _scan_state["engine_stats"]["e7"]["options_catalyst"] += 1
                            log.info("  OPTIONS  %-6s  score=%.0f  vol=%d  C/P=%.2f  DTE=%d",
                                     ticker, opt.get("options_score", 0),
                                     opt.get("total_call_volume", 0),
                                     opt.get("call_put_ratio", 0),
                                     opt.get("dte", 0))
                except Exception as opt_exc:
                    log.warning("Options check failed for %s: %s", ticker, opt_exc)

            except Exception as exc:
                log.error("Error processing %s: %s", ticker, exc)
                import traceback
                log.error("Traceback for %s:\n%s", ticker, traceback.format_exc())
            finally:
                _scan_state["progress"] = idx + 1

        # ── PASS 2: bounded compute worker pool ───────────────────────────
        _pass2_start = time.time()
        await _run_compute_phase(_survivors, _process)
        _scan_state["engine_stats"]["timing"]["pass2_s"] = round(time.time() - _pass2_start, 2)
        _scan_state["engine_stats"]["cache_hit_rate"] = _cache_store.cache_hit_rate()

        # ── Tag discovery candidates in collected setups ───────────────────────
        if _discovery_tickers:
            for _s in collected_setups:
                if _s.get("ticker") in _discovery_tickers:
                    _s["is_discovery"] = True

        process_time = time.time() - process_start_time
        _scan_state["engine_stats"]["timing"]["process_s"] = round(process_time, 2)
        _f = _scan_state["engine_stats"]["filtered"]
        log.info(
            "Per-ticker processing completed  [%.1fs]  "
            "setups: vcp=%d pb=%d base=%d res=%d opt=%d HTF=%d LCE=%d total=%d  |  "
            "rejected: data=%d vital=%d rs_rank=%d earn=%d ind=%d liq=%d rs_score=%d",
            process_time,
            vcp_count, pb_count, base_count, res_count, opt_count, htf_count, lce_count,
            len(collected_setups),
            _f["insufficient_data"], _f["vitality"], _f["rs_rank_gate"],
            _f["earnings"], _f["ind_failed"], _f["liquidity"], _f["rs_score_gate"],
        )

        # ── Sector Clustering — inject hot_sector flag before saving ─────────
        try:
            _inject_hot_sector(collected_setups)
        except Exception as exc:
            log.warning("Sector clustering failed: %s", exc)

        # ── Task 9: Unified scoring — score and sort (no score cap) ─────────
        # Score gate removed: all setups shown regardless of score or regime.
        # Scoring still runs so the score column is populated and rows are
        # sorted by score descending.
        pre_score_count = len(collected_setups)
        _score_threshold = 0
        try:
            collected_setups = score_and_filter_setups(
                collected_setups,
                _rs_rank_map,
                regime,
                _top_sectors,
                min_score=_score_threshold,
            )
            log.info(
                "Scoring: %d → %d setups (filtered %d below score %d)  "
                "top_sectors=%s",
                pre_score_count,
                len(collected_setups),
                pre_score_count - len(collected_setups),
                _score_threshold,
                _top_sectors,
            )
        except Exception as exc:
            log.warning("Setup scoring failed (keeping all setups): %s", exc)

        # ── Batch Save S/R Zones (replaces per-ticker saves inside _process) ──
        if collected_zones and not dry_run:
            zone_tickers = len(collected_zones)
            zone_total   = sum(len(z) for z in collected_zones.values())
            await batch_save_sr_zones(DB_PATH, scan_ts, collected_zones)
            log.info("Batch saved %d zones (%d tickers) to database", zone_total, zone_tickers)

        # ── Batch Save All Setups (5-10x faster than individual saves) ──────
        db_save_time = 0.0
        if collected_setups and not dry_run:
            db_save_start = time.time()
            await batch_save_setups(DB_PATH, scan_ts, collected_setups)
            db_save_time = time.time() - db_save_start
            log.info("Batch saved %d setups to database  [%.1fs]", len(collected_setups), db_save_time)
        _scan_state["engine_stats"]["timing"]["db_s"] = round(db_save_time, 2)

        # ── Persist earnings cache to disk (Task 1) ───────────────────────────
        with _earnings_cache_lock:
            _save_earnings_cache(dict(_earnings_cache))
        log.info("Earnings cache saved: %d entries", len(_earnings_cache))

        if dry_run:
            _scan_state["dry_run_setups"] = {
                "vcp":               [s for s in collected_setups if s.get("setup_type") == "VCP"],
                "pullback":          [s for s in collected_setups if s.get("setup_type") == "PULLBACK"],
                "base":              [s for s in collected_setups if s.get("setup_type") == "BASE"],
                "res_breakout":      [s for s in collected_setups if s.get("setup_type") == "RES_BREAKOUT"],
                "watchlist":         [s for s in collected_setups if s.get("setup_type") == "WATCHLIST"],
                "options_catalyst":  [s for s in collected_setups if s.get("setup_type") == "OPTIONS_CATALYST"],
                "htf":               [s for s in collected_setups if s.get("setup_type") == "HTF"],
                "lce":               [s for s in collected_setups if s.get("setup_type") == "LCE"],
            }
            log.info("DRY RUN: stored %d setups in memory (no DB write)", len(collected_setups))

        # ── Sector Summary with Bold Highlighting ───────────────────────────
        try:
            sector_counts: Dict[str, int] = {}
            for s in collected_setups:
                sector = s.get("sector", "Unknown")
                sector_counts[sector] = sector_counts.get(sector, 0) + 1

            # Sort by count descending
            sorted_sectors = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)

            # Log with visual separator and bold for 3+ setups
            log.info("═════════════════════════════════════════════════════════")
            log.info("SECTOR SUMMARY — INSTITUTIONAL ROTATION ALERT")
            log.info("═════════════════════════════════════════════════════════")

            for sector, count in sorted_sectors:
                if count >= 3:
                    # Bold formatting with emoji for high-activity sectors
                    log.info("🔥 **%s (%d setups)**", sector, count)
                else:
                    log.info("   %s (%d setup%s)", sector, count, "s" if count != 1 else "")

            log.info("═════════════════════════════════════════════════════════")
        except Exception as exc:
            log.warning("Sector summary failed: %s", exc)

        total_scan_elapsed = time.time() - scan_start_time
        _scan_state["engine_stats"]["total_tickers"] = len(tickers)
        _scan_state["engine_stats"]["total_duration_s"] = round(total_scan_elapsed, 1)
        _scan_state["engine_stats"]["timing"]["total_s"] = round(total_scan_elapsed, 2)
        _scan_state["engine_stats"]["filtered"]["liquidity"] = liquidity_filtered
        _scan_state["engine_stats"]["filtered"]["earnings"] = earnings_filtered
        if not dry_run:
            await complete_scan_run(DB_PATH, scan_ts, len(tickers))
        _scan_state["last_completed"] = scan_ts

        # ── Data Quality Report ───────────────────────────────────────────
        processed_tickers = len(tickers) - len(dropped_tickers)
        if dropped_tickers:
            log.warning(
                "⚠ DATA QUALITY: %d/%d tickers dropped after retries",
                len(dropped_tickers),
                len(tickers),
            )
            log.warning("  Dropped tickers: %s", ", ".join(sorted(dropped_tickers[:20])))
            if len(dropped_tickers) > 20:
                log.warning("  ... and %d more", len(dropped_tickers) - 20)
        else:
            log.info("✓ DATA QUALITY: All %d tickers processed successfully (0 dropped)", len(tickers))

        log.info(
            "✔ Scan complete  VCP=%d  Pullbacks=%d  Base=%d  ResBreakout=%d  Options=%d  HTF=%d  LCE=%d  "
            "Processed=%d/%d  filtered(liq=%d  earn=%d)  "
            "Total=%.1fs  [regime=%.1fs  spy=%.1fs  fetch=%.1fs  process=%.1fs  db=%.1fs]",
            vcp_count, pb_count, base_count, res_count, opt_count, htf_count, lce_count,
            processed_tickers, len(tickers),
            liquidity_filtered, earnings_filtered,
            total_scan_elapsed,
            regime_time, spy_fetch_time, _fetch_time, process_time, db_save_time,
        )

    except Exception as exc:
        log.error("Scan worker crashed: %s", exc)
        _scan_state["last_error"] = str(exc)
    finally:
        _scan_state["in_progress"] = False


# ────────────────────────────────────────────────────────────────────────────
# Scan helpers
# ────────────────────────────────────────────────────────────────────────────

def compute_universe_breadth(
    ticker_cache: dict,
    tickers: List[str],
    sample_size: int = 200,
) -> tuple:
    """
    Compute two breadth metrics from the bulk-prefetch cache.

    Returns
    -------
    (breadth_pct, hl_ratio) : tuple[float, float]
        breadth_pct : fraction of sampled tickers where close > SMA50 (0.0–1.0)
        hl_ratio    : new_highs / (new_highs + new_lows + 1)   (0.0–1.0)
    """
    candidates = [t for t in tickers if t in ticker_cache and ticker_cache[t][1] is not None]
    sample = candidates[:sample_size]
    if not sample:
        return 0.5, 0.5

    above_50 = new_highs = new_lows = total = 0

    for t in sample:
        _, df = ticker_cache[t]
        if df is None or len(df) < 52:
            continue
        try:
            adj = "Adj Close" if "Adj Close" in df.columns else "Close"
            close = df[adj].dropna()
            if len(close) < 52:
                continue
            lc = float(close.iloc[-1])
            sma50_val = close.rolling(50).mean().iloc[-1]
            if pd.isna(sma50_val):
                continue
            if lc > float(sma50_val):
                above_50 += 1
            lookback = min(252, len(close))
            h52 = float(close.iloc[-lookback:].max())
            l52 = float(close.iloc[-lookback:].min())
            if lc >= h52 * 0.97:
                new_highs += 1
            elif lc <= l52 * 1.03:
                new_lows += 1
            total += 1
        except Exception:
            pass

    if total == 0:
        return 0.5, 0.5

    breadth_pct = above_50 / total
    hl_ratio    = new_highs / (new_highs + new_lows + 1)
    return round(breadth_pct, 3), round(hl_ratio, 3)


def _inject_hot_sector(setups: List[Dict], threshold: int = 3) -> None:
    """
    Mutate each setup in-place: set hot_sector=True if its sector has
    ≥ threshold setups in the current scan batch, False otherwise.

    hot_sector is persisted in the metadata JSON column and surfaced
    to the frontend as a 🔥 flag for institutional rotation signals.
    """
    sector_counts: Dict[str, int] = {}
    for s in setups:
        sector = s.get("sector", "Unknown")
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    hot = {sector for sector, count in sector_counts.items() if count >= threshold}

    for s in setups:
        s["hot_sector"] = s.get("sector", "Unknown") in hot


async def _inject_narratives(setups: list) -> None:
    """Add 'narrative' field to each setup in-place (lazy, at fetch time)."""
    regime_row = await get_latest_regime(DB_PATH)
    raw_regime = regime_row.get("regime", "NEUTRAL") if regime_row else "NEUTRAL"
    # Engine 0 writes AGGRESSIVE/SELECTIVE/DEFENSIVE; map to narrative vocabulary
    _REGIME_MAP = {
        "AGGRESSIVE": "BULLISH",
        "SELECTIVE":  "BULLISH",
        "DEFENSIVE":  "BEARISH",
    }
    regime_str = _REGIME_MAP.get(raw_regime, "NEUTRAL")
    for s in setups:
        s["narrative"] = generate_narrative(s, regime_str)


# ────────────────────────────────────────────────────────────────────────────
# Pydantic request models
# ────────────────────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    ticker:      str
    start_date:  date
    end_date:    date
    setup_types: List[str] = Field(default_factory=lambda: ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"])

    @model_validator(mode="after")
    def check_date_range(self) -> "BacktestRequest":
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be before end_date")
        return self


class BacktestRunRequest(BaseModel):
    start_date:    str           = Field(default_factory=lambda: BACKTEST_DIAG_START_DATE)
    end_date:      str           = Field(default_factory=lambda: BACKTEST_DIAG_END_DATE)
    max_positions: int           = 4
    ticker_count:  Optional[int] = None
    min_score:     float         = 0.0
    setup_types:   List[str]     = Field(default_factory=lambda: [
        "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"
    ])


class ISOOSRunRequest(BaseModel):
    is_start_date:  str           = "2017-01-01"
    is_end_date:    str           = "2021-12-31"
    oos_start_date: str           = "2022-01-01"
    oos_end_date:   str           = "2024-12-31"
    max_positions:  int           = 4
    ticker_count:   Optional[int] = None
    min_score:      float         = 0.0
    setup_types:    List[str]     = Field(default_factory=lambda: [
        "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"
    ])


class WFODownloadRequest(BaseModel):
    tickers: List[str]


class WFORunRequest(BaseModel):
    tickers:     List[str]
    setup_types: List[str] = Field(
        default_factory=lambda: ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"]
    )
    is_months:   int = 24
    oos_months:  int = 3
    step_months: int = 3
    min_trades:  int = 20


def _generate_analysis_narrative(ticker: str, signals: dict, best_setup: dict | None) -> dict:
    """Rule-based narrative generator for stock analysis."""
    rs_score  = signals.get("rs_score", 0.0) or 0.0
    vol_ratio = signals.get("vol_ratio", 1.0) or 1.0
    above_ema = signals.get("above_ema20", False)
    above_sma = signals.get("above_sma50", False)
    score     = best_setup.get("setup_score", 0) if best_setup else 0

    sentences = []

    # RS sentence
    if rs_score > 0.10:
        sentences.append("Relative strength is strong — the stock is meaningfully outperforming the market.")
    elif rs_score > 0.02:
        sentences.append("Relative strength is modestly positive versus the benchmark.")
    elif rs_score > -0.05:
        sentences.append("Relative strength is near-neutral, neither leading nor lagging significantly.")
    else:
        sentences.append("Relative strength is declining — the stock is underperforming the market.")

    # Volume sentence
    if vol_ratio >= 1.5:
        sentences.append(f"Volume is surging at {vol_ratio:.1f}× the 50-day average, showing strong participation.")
    elif vol_ratio >= 1.1:
        sentences.append("Volume is above average, indicating improving buying interest.")
    else:
        sentences.append("Volume participation is below average, limiting conviction in any move.")

    # Trend sentence
    if above_ema and above_sma:
        sentences.append("Price is trading above both the 20-day EMA and 50-day SMA, confirming a healthy uptrend structure.")
    elif above_ema and not above_sma:
        sentences.append("Price is recovering above the 20-day EMA but remains below the 50-day SMA — trend is mixed.")
    else:
        sentences.append("Price is trading below key moving averages — no clear uptrend structure is present.")

    # Setup sentence
    if best_setup:
        st    = best_setup.get("setup_type", "setup")
        entry = best_setup.get("entry") or 0
        sentences.append(f"A {st} pattern has been detected with an entry near ${entry:.2f}.")
    else:
        sentences.append("No high-quality breakout pattern has been identified at current price levels.")

    # Verdict
    if score >= 70 and best_setup:
        verdict = "TRADE CANDIDATE"; verdict_color = "go";     quality = "Strong"
    elif score >= 50 or (best_setup and score >= 40):
        verdict = "WATCHLIST";       verdict_color = "accent";  quality = "Moderate"
    else:
        verdict = "AVOID";           verdict_color = "halt";    quality = "Weak" if score > 0 else "No Setup"

    return {
        "verdict":       verdict,
        "verdict_color": verdict_color,
        "quality":       quality,
        "narrative":     " ".join(sentences),
    }


# ────────────────────────────────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────────────────────────────────

@app.get("/api/market-overview")
async def market_overview_endpoint():
    """Cached market sentiment: Fear & Greed, SPY/QQQ performance, top news."""
    return await get_market_overview()


@app.post("/api/run-backtest")
async def run_backtest(req: BacktestRequest, background_tasks: BackgroundTasks):
    """
    Kick off a backtest run in the background.
    Returns immediately with a run_id; poll /api/backtest-results/{ticker}
    to retrieve results once complete.
    """
    run_id = str(uuid.uuid4())

    async def _do_backtest():
        try:
            engine = BacktestEngine(
                ticker=req.ticker,
                start_date=str(req.start_date),
                end_date=str(req.end_date),
                setup_types=req.setup_types,
                run_id=run_id,
            )
            summary = await engine.run()
            result  = summary.to_dict()
            await save_backtest_result(DB_PATH, result)
            log.info("Backtest %s done: %d trades", summary.run_id, summary.total_trades)
        except Exception as exc:
            log.exception("Backtest %s failed: %s", run_id, exc)

    background_tasks.add_task(_do_backtest)
    return {"run_id": run_id, "status": "started"}


@app.get("/api/backtest-results/{ticker}")
async def backtest_results(ticker: str):
    """Return all completed backtest runs for a ticker."""
    results = await get_backtest_results(DB_PATH, ticker.upper())
    return {"ticker": ticker.upper(), "results": results}


# ─────────────────────────────────────────────────────────────────────────────
# WFO Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/wfo/download")
async def wfo_download(req: WFODownloadRequest, background_tasks: BackgroundTasks):
    """
    Start a background download of 10-year OHLCV data for the requested tickers.
    SPY is added automatically. Returns {job_id} for polling.
    """
    tickers = [t.upper() for t in req.tickers]
    if "SPY" not in tickers:
        tickers = ["SPY"] + tickers

    job_id = str(uuid.uuid4())
    progress = {
        "status":            "running",
        "tickers_completed": 0,
        "total_tickers":     len(tickers),
    }
    _wfo_download_jobs[job_id] = progress

    def _run_download():
        try:
            download_and_cache(tickers, job_id, progress)
        except Exception as exc:
            progress["status"] = "error"
            log.exception("WFO download job %s failed: %s", job_id, exc)

    background_tasks.add_task(_run_download)
    return {"job_id": job_id, "total_tickers": len(tickers)}


@app.get("/api/wfo/download-status/{job_id}")
async def wfo_download_status(job_id: str):
    """Poll download job progress."""
    job = _wfo_download_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/wfo/run")
async def wfo_run(req: WFORunRequest, background_tasks: BackgroundTasks):
    """
    Start a walk-forward validation run in the background.
    Returns {run_id} for polling.
    """
    run_id = str(uuid.uuid4())
    progress = {"windows_completed": 0, "total_windows": 0}
    _wfo_runs[run_id] = progress

    await create_wfo_run(DB_PATH, run_id)

    async def _do_wfo():
        try:
            result = await run_wfo(
                tickers=req.tickers,
                setup_types=req.setup_types,
                is_months=req.is_months,
                oos_months=req.oos_months,
                step_months=req.step_months,
                min_trades=req.min_trades,
                run_id=run_id,
                progress=progress,
            )
            total = progress["total_windows"]
            if total > 0:
                await update_wfo_progress(
                    DB_PATH, run_id, 100,
                    progress["windows_completed"], total,
                )
            await save_wfo_result(DB_PATH, run_id, json.dumps(result.to_dict(), default=_json_safe))
            log.info("WFO run %s complete: %d windows", run_id, len(result.windows))
        except Exception as exc:
            log.exception("WFO run %s failed: %s", run_id, exc)
            try:
                await mark_wfo_error(DB_PATH, run_id)
            except Exception:
                pass

    background_tasks.add_task(_do_wfo)
    return {"run_id": run_id, "status": "started"}


@app.get("/api/wfo/status/{run_id}")
async def wfo_status(run_id: str):
    """Poll WFO run progress."""
    row = await get_wfo_run(DB_PATH, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    mem = _wfo_runs.get(run_id, {})
    return {
        "status":            row["status"],
        "progress_pct":      row["progress_pct"],
        "windows_completed": mem.get("windows_completed", row["windows_completed"]),
        "total_windows":     mem.get("total_windows",     row["total_windows"]),
    }


@app.get("/api/wfo/results/{run_id}")
async def wfo_results(run_id: str):
    """Return the full WFO result JSON."""
    row = await get_wfo_run(DB_PATH, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["status"] != "done" or not row["result_json"]:
        return {"status": row["status"], "result": None}
    return {"status": "done", "result": json.loads(row["result_json"])}


@app.get("/api/wfo/audit/{run_id}")
async def wfo_audit(run_id: str, period: str = "oos"):
    """
    Run per-engine diagnostic audit on a completed WFO run.

    Query param:
      period : "oos" (default) | "is" | "all"
        oos  — audit only OOS trades (unbiased, recommended)
        is   — audit only IS trades (in-sample)
        all  — combine IS + OOS trades
    """
    from engine_audit import run_audit as _run_audit

    row = await get_wfo_run(DB_PATH, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["status"] != "done" or not row["result_json"]:
        raise HTTPException(status_code=400, detail="Run not complete")

    result   = json.loads(row["result_json"])
    windows  = result.get("windows", [])

    period = period.lower()
    trades: list = []
    for w in windows:
        if period in ("oos", "all"):
            trades.extend(w.get("oos_trades", []))
        if period in ("is", "all"):
            trades.extend(w.get("is_trades", []))

    label = {"oos": "OOS", "is": "IS", "all": "IS+OOS"}.get(period, "OOS")
    audit = _run_audit(trades, period_label=label)
    return {"run_id": run_id, "period": label, "audit": audit}


@app.get("/api/wfo/export/{run_id}")
async def wfo_export(run_id: str):
    """Export full trade-level CSV for a completed WFO run."""
    from fastapi.responses import StreamingResponse
    import csv
    import io

    row = await get_wfo_run(DB_PATH, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["status"] != "done" or not row["result_json"]:
        raise HTTPException(status_code=400, detail="Run not complete")

    result = json.loads(row["result_json"])

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "window_num", "period", "is_start", "is_end", "oos_start", "oos_end",
        "ticker", "setup_type", "signal_date", "entry_date", "entry_price",
        "initial_stop", "take_profit", "exit_date", "exit_price",
        "exit_reason", "holding_days", "rr_achieved", "pnl_pct", "is_win",
    ])

    for win in result["windows"]:
        base = [
            win["window_num"], "", win["is_start"], win["is_end"],
            win["oos_start"], win["oos_end"],
        ]
        for trade in win["is_trades"]:
            writer.writerow(base[:1] + ["IS"] + base[2:] + [
                trade["ticker"], trade["setup_type"], trade["signal_date"],
                trade["entry_date"], trade["entry_price"], trade["initial_stop"],
                trade["take_profit"], trade["exit_date"], trade["exit_price"],
                trade["exit_reason"], trade["holding_days"],
                trade["rr_achieved"], trade["pnl_pct"], trade["is_win"],
            ])
        for trade in win["oos_trades"]:
            writer.writerow(base[:1] + ["OOS"] + base[2:] + [
                trade["ticker"], trade["setup_type"], trade["signal_date"],
                trade["entry_date"], trade["entry_price"], trade["initial_stop"],
                trade["take_profit"], trade["exit_date"], trade["exit_price"],
                trade["exit_reason"], trade["holding_days"],
                trade["rr_achieved"], trade["pnl_pct"], trade["is_win"],
            ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=wfo_{run_id}.csv"},
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/api/run-scan")
async def trigger_scan(
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Bypass bearish halt gate"),
    dry_run: bool = Query(False, description="Run pipeline without saving to DB"),
    tickers: Optional[str] = Query(None, description="Comma-separated tickers for single-ticker debug scan"),
):
    """
    Trigger a full market scan.  Returns immediately; scan runs in background.
    Poll /api/scan-status to track progress.

    Pass ?tickers=EQT,NVDA to run only those tickers (dev debug mode).
    """
    if _scan_state["in_progress"]:
        return {
            "status": "already_running",
            "progress": _scan_state["progress"],
            "total": _scan_state["total"],
        }

    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        ticker_list = ACTIVE_UNIVERSE

    scan_ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    background_tasks.add_task(_run_scan, scan_ts, ticker_list, force, dry_run)

    return {
        "status": "started",
        "scan_timestamp": scan_ts,
        "tickers": len(ticker_list),
        "forced": force,
        "dry_run": dry_run,
        "message": f"Scanning {len(ticker_list)} tickers in background",
    }


@app.post("/api/build-universe")
async def trigger_build_universe(background_tasks: BackgroundTasks):
    """Trigger a full universe rebuild in the background.
    Operator-facing: rebuilds active_universe.json with tightened liquidity constants.
    Returns immediately with a job_id (no polling endpoint needed).
    """
    job_id = str(uuid.uuid4())[:8]

    async def _run_build():
        loop = asyncio.get_event_loop()
        log.info("[build-universe] Starting (job %s)", job_id)
        try:
            universe = await loop.run_in_executor(
                None,
                lambda: build_universe(
                    min_avg_volume=LIQUIDITY_MIN_AVG_VOLUME,
                    min_dollar_volume=LIQUIDITY_MIN_DOLLAR_VOLUME,
                    min_atr_pct=MIN_ATR_PCT,
                ),
            )
            save_universe(universe, UNIVERSE_FILE)
            log.info(
                "[build-universe] Done (job %s): %d tickers saved to %s",
                job_id, len(universe["tickers"]), UNIVERSE_FILE,
            )
        except Exception as exc:
            log.error("[build-universe] Failed (job %s): %s", job_id, exc)

    background_tasks.add_task(_run_build)
    return {"job_id": job_id, "status": "started"}


@app.get("/api/scan-status")
async def scan_status():
    """Current scan progress (poll this after POST /api/run-scan)."""
    total = max(_scan_state["total"], 1)
    return {
        "in_progress": _scan_state["in_progress"],
        "progress": _scan_state["progress"],
        "total": _scan_state["total"],
        "progress_pct": round(_scan_state["progress"] / total * 100, 1),
        "started_at": _scan_state["started_at"],
        "last_completed": _scan_state["last_completed"],
        "last_error": _scan_state["last_error"],
        "engine_stats": _scan_state["engine_stats"],
        "dry_run_setups": _scan_state.get("dry_run_setups"),
        "prefetching": _scan_state.get("prefetching", False),
        "rebuilding_universe": _scan_state.get("rebuilding_universe", False),
    }


@app.get("/api/regime")
async def get_regime():
    """Latest market regime from the last completed scan."""
    regime = await get_latest_regime(DB_PATH)
    if regime is None:
        return {
            "regime": "NO_DATA",
            "is_bullish": False,
            "spy_close": 0.0,
            "spy_20ema": 0.0,
            "scan_timestamp": None,
        }
    return regime


@app.get("/api/setups")
async def get_all_setups():
    """All VCP + Pullback setups from the latest scan."""
    setups = await get_latest_setups(DB_PATH)
    await _inject_narratives(setups)
    return {"setups": setups, "count": len(setups)}


@app.get("/api/setups/vcp")
async def get_vcp_setups():
    """VCP breakout setups from the latest scan."""
    setups = await get_latest_setups(DB_PATH, setup_type="VCP")
    await _inject_narratives(setups)
    return {"setups": setups, "count": len(setups)}


@app.get("/api/setups/pullback")
async def get_pullback_setups():
    """Tactical pullback setups from the latest scan."""
    setups = await get_latest_setups(DB_PATH, setup_type="PULLBACK")
    await _inject_narratives(setups)
    return {"setups": setups, "count": len(setups)}


@app.get("/api/setups/base")
async def get_base_setups():
    """Cup & Handle and Flat Base setups from the latest scan."""
    setups = await get_latest_setups(DB_PATH, setup_type="BASE")
    setups.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    await _inject_narratives(setups)
    return {"setups": setups, "count": len(setups)}


@app.get("/api/setups/res-breakout")
async def get_res_breakout_setups():
    """Resistance breakout setups (fresh break above KDE zone, last 3 days)."""
    setups = await get_latest_setups(DB_PATH, setup_type="RES_BREAKOUT")
    setups.sort(key=lambda x: x.get("days_since_breakout", 99))
    await _inject_narratives(setups)
    return {"setups": setups, "count": len(setups)}


@app.get("/api/setups/options-catalyst")
async def get_options_catalyst_setups():
    """Options Catalyst setups — unusual near-term call activity (Engine 7)."""
    setups = await get_latest_setups(DB_PATH, setup_type="OPTIONS_CATALYST")
    setups.sort(key=lambda x: x.get("options_score", 0), reverse=True)
    await _inject_narratives(setups)
    return {"setups": setups, "count": len(setups)}


@app.get("/api/setups/htf")
async def get_htf_setups():
    """High Tight Flag setups from the latest scan."""
    setups = await get_latest_setups(DB_PATH, setup_type="HTF")
    setups.sort(key=lambda x: x.get("runup_pct", 0), reverse=True)
    await _inject_narratives(setups)
    return {"setups": setups, "count": len(setups)}


@app.get("/api/setups/lce")
async def get_lce_setups():
    """Low Cheat Entry setups from the latest scan."""
    setups = await get_latest_setups(DB_PATH, setup_type="LCE")
    setups.sort(key=lambda x: x.get("distance_to_resistance_pct", 99))
    await _inject_narratives(setups)
    return {"setups": setups, "count": len(setups)}


@app.get("/api/watchlist")
async def get_watchlist():
    """Near-breakout tickers from the latest scan (within 1.5% of KDE/TDL level)."""
    items = await get_latest_setups(DB_PATH, setup_type="WATCHLIST")
    # Sort by ATR-normalized distance (closest in ATR terms first).
    # atr_distance = distance_pct / (atr/entry * 100) — how many ATRs away.
    # Falls back to raw distance_pct sort if atr/entry not available.
    def _wl_sort_key(x):
        dist  = x.get("distance_pct", 99)
        atr   = x.get("atr", 0)
        entry = x.get("entry", 0)
        if atr > 0 and entry > 0:
            atr_pct = atr / entry * 100
            return dist / atr_pct if atr_pct > 0 else 99
        return 99
    items.sort(key=_wl_sort_key)
    await _inject_narratives(items)
    return {"items": items, "count": len(items)}


@app.get("/api/prices")
async def get_prices(tickers: str):
    """
    Returns latest price for a comma-separated list of tickers.
    Caches results for 60 seconds to avoid hammering yfinance.
    Query: /api/prices?tickers=AAPL,MSFT,NVDA
    Returns: {"AAPL": 182.50, "MSFT": 415.20, ...}
    """
    # Parse, deduplicate, uppercase, cap at 50
    raw = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    seen: set = set()
    ticker_list = []
    for t in raw:
        if t not in seen:
            seen.add(t)
            ticker_list.append(t)
    ticker_list = ticker_list[:50]

    now = time.time()
    result: dict = {}
    uncached: list = []

    # Check cache first
    for t in ticker_list:
        entry = _price_cache.get(t)
        if entry is not None:
            ts, price = entry
            if now - ts < PRICE_CACHE_TTL:
                result[t] = price
                continue
        uncached.append(t)

    # Serve uncached prices from the main ticker cache first (avoids extra yfinance calls)
    still_missing: list = []
    for t in uncached:
        cached_entry = _ticker_cache.get(t)
        if cached_entry is not None:
            _, df_cached = cached_entry
            if df_cached is not None and not df_cached.empty:
                try:
                    adj = "Adj Close" if "Adj Close" in df_cached.columns else "Close"
                    price = float(df_cached[adj].dropna().iloc[-1])
                    _price_cache[t] = (now, price)
                    result[t] = price
                    continue
                except Exception:
                    pass
        still_missing.append(t)

    # Fetch any tickers not in the main cache via yfinance
    if still_missing:
        try:
            loop = asyncio.get_event_loop()

            def _batch_download(tks=still_missing):
                return yf.download(
                    tks,
                    period="5d",
                    interval="1d",
                    progress=False,
                    group_by="ticker" if len(tks) > 1 else None,
                )

            df = await loop.run_in_executor(None, _batch_download)

            if df is not None and not df.empty:
                fetch_ts = time.time()
                if len(still_missing) == 1:
                    t = still_missing[0]
                    try:
                        adj = "Adj Close" if "Adj Close" in df.columns else "Close"
                        price = float(df[adj].dropna().iloc[-1])
                        _price_cache[t] = (fetch_ts, price)
                        result[t] = price
                    except Exception:
                        pass
                else:
                    for t in still_missing:
                        try:
                            adj = "Adj Close" if "Adj Close" in df.columns else "Close"
                            price = float(df[adj][t].dropna().iloc[-1])
                            _price_cache[t] = (fetch_ts, price)
                            result[t] = price
                        except Exception:
                            pass
        except Exception as exc:
            log.warning("[prices] batch fetch error: %s", exc)

    return result


@app.get("/api/sr-zones/{ticker}")
async def get_sr_zones(ticker: str):
    """S/R zones for a ticker from the last scan (pre-computed, instant)."""
    zones = await get_sr_zones_for_ticker_from_db(DB_PATH, ticker.upper())
    return {"ticker": ticker.upper(), "zones": zones, "count": len(zones)}


@app.get("/api/debug/{ticker}")
async def debug_ticker(ticker: str):
    """
    Dev mode: run all engines live for a single ticker and return
    structured pass/fail results for the DebugDrawer component.
    """
    sym = ticker.upper()
    loop = asyncio.get_event_loop()

    # Fetch OHLCV
    df = await _fetch(sym)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"No data for {sym}")
    if len(df) < MIN_CANDLES_FOR_ANALYSIS:
        raise HTTPException(status_code=422, detail=f"Insufficient history for {sym}")

    # Indicators for display
    adj = "Adj Close" if "Adj Close" in df.columns else "Close"
    close_adj = df[adj]
    ema8_s  = _ema(close_adj, 8)
    ema20_s = _ema(close_adj, 20)
    sma50_s = _sma(close_adj, 50)
    cci20_s = _cci(df["High"], df["Low"], close_adj, 20)

    lc   = float(close_adj.iloc[-1])
    l8   = float(ema8_s.iloc[-1])  if pd.notna(ema8_s.iloc[-1])  else None
    l20  = float(ema20_s.iloc[-1]) if pd.notna(ema20_s.iloc[-1]) else None
    l50  = float(sma50_s.iloc[-1]) if pd.notna(sma50_s.iloc[-1]) else None
    lcci = float(cci20_s.iloc[-1]) if pd.notna(cci20_s.iloc[-1]) else None

    # Zones: DB first, fresh computation as fallback
    zones = await get_sr_zones_for_ticker_from_db(DB_PATH, sym)
    if not zones:
        try:
            zones = await loop.run_in_executor(None, calculate_sr_zones, sym, df)
        except Exception:
            zones = []

    # RS metrics
    rs_ratio    = 0.0
    rs_52w_high = 0.0
    rs_blue_dot = False
    rs_score    = 0
    rs_signals  = {"rs_improving": False, "rs_near_high": False, "rs_acceleration": 0.0}
    try:
        spy_df = await _fetch("SPY")
        if spy_df is not None and len(spy_df) >= MIN_CANDLES_FOR_RS:
            rs_line = await loop.run_in_executor(None, calculate_rs_line, df, spy_df)
            if rs_line is not None and len(rs_line) >= MIN_CANDLES_FOR_RS:
                rs_stats    = get_rs_stats(rs_line)
                rs_ratio    = round(float(rs_stats.get("rs_ratio", 0.0)), 4)
                rs_52w_high = float(rs_stats.get("rs_52w_high", 0.0))
                rs_blue_dot = bool(detect_rs_blue_dot(rs_line))
                rs_score    = int(await loop.run_in_executor(None, calculate_rs_score, df, spy_df))
                rs_signals  = get_rs_signals(rs_line)
    except Exception as exc:
        log.warning("debug RS failed for %s: %s", sym, exc)

    # Regime from DB (latest)
    regime_row = await get_latest_regime(DB_PATH) or {
        "is_bullish": False, "spy_close": 0.0, "spy_20ema": 0.0, "regime": "NO_DATA"
    }

    # Trendline (used by pullback engines)
    try:
        tl = await loop.run_in_executor(None, detect_trendline, sym, df)
    except Exception:
        tl = None

    # Helper: run a sync engine function safely
    def _run_engine(fn, *args):
        try:
            return fn(*args)
        except Exception:
            return None

    # ── Gate checks (mirrors _process_ticker logic) ───────────────────────
    regime_label   = regime_row.get("regime", "UNKNOWN")
    is_bullish     = bool(regime_row.get("is_bullish", False))

    rs_threshold_gate = rs_score >= _LIVE_PARAMS.rs_threshold  # mirrors backtest line 837
    brk_regime_ok     = (
        regime_label == "AGGRESSIVE"
        or not getattr(_LIVE_PARAMS, "brk_aggressive_only", True)
    )

    # Engine 2 — VCP
    e2 = await loop.run_in_executor(
        None, _run_engine, scan_vcp,
        sym, df, zones, 0.0, rs_ratio, rs_52w_high, rs_blue_dot, rs_score,
        rs_signals["rs_improving"], rs_signals["rs_near_high"], rs_signals["rs_acceleration"]
    ) if is_bullish else None

    # Engine 3 — Pullback (scored mode with _LIVE_PARAMS, then relaxed fallback)
    e3_scored_result = None
    e3_score         = 0.0
    e3_final_score   = 0.0
    e3_passes_gate   = False
    e3_relaxed       = False

    if is_bullish and rs_threshold_gate:
        _regime_str = regime_row.get("regime", "SELECTIVE")
        e3_scored_result, e3_score = await loop.run_in_executor(
            None, scan_pullback_scored, sym, df, zones, _LIVE_PARAMS, tl, rs_score, _regime_str
        )
        e3_final_score = e3_score * _LIVE_PARAMS.pullback_weight
        e3_passes_gate = e3_final_score >= _LIVE_PARAMS.score_threshold

    e3 = e3_scored_result if e3_passes_gate else None
    if e3 is None and is_bullish:
        _regime_str = regime_row.get("regime", "SELECTIVE")
        e3 = await loop.run_in_executor(None, lambda: scan_relaxed_pullback(sym, df, zones, tl, rs_score, params=_LIVE_PARAMS, regime=_regime_str))
        if e3 is not None:
            e3_relaxed = True

    # Engine 5 — Base pattern (always runs; passes _LIVE_PARAMS)
    e5 = await loop.run_in_executor(
        None, _run_engine, scan_base_pattern,
        sym, df, 0.0, rs_ratio, rs_52w_high, rs_blue_dot, rs_score, zones, _LIVE_PARAMS
    )

    # Engine 6 — Resistance breakout (gated by regime + zones; passes _LIVE_PARAMS)
    e6 = await loop.run_in_executor(
        None, _run_engine, scan_resistance_breakout, sym, df, zones, False, _LIVE_PARAMS
    ) if (zones and brk_regime_ok) else None

    def _eng(result, extra_keys=()):
        if result is None:
            return {"triggered": False, "result": None, "rejection": None}
        out = {
            "triggered": True,
            "result":    result.get("setup_type") or result.get("signal"),
            "rejection": None,
        }
        for k in extra_keys:
            if k in result:
                out[k] = result[k]
        return out

    # Engine 2 block
    e2_out = _eng(e2, ("is_breakout", "is_vol_surge", "is_rs_lead"))
    if e2 is not None:
        e2_out["path"]      = "B" if e2.get("is_breakout") else "A"
        e2_out["vol_surge"] = e2.get("is_vol_surge", False)
        e2_out.pop("is_vol_surge", None)

    # Engine 3 block — include scoring breakdown
    e3_out = _eng(e3, ())
    e3_out["raw_score"]    = round(e3_score, 3)
    e3_out["final_score"]  = round(e3_final_score, 3)
    e3_out["passes_gate"]  = e3_passes_gate
    e3_out["gate_formula"] = f"{e3_score:.3f} × {_LIVE_PARAMS.pullback_weight:.3f} = {e3_final_score:.3f} (need ≥ {_LIVE_PARAMS.score_threshold:.3f})"
    if e3 is not None and e3_relaxed:
        e3_out["is_relaxed"] = True

    # Engine 5 block
    e5_out = _eng(e5, ("base_type", "quality_score"))
    if e5 is not None and e5.get("base_type"):
        e5_out["result"] = e5["base_type"]

    # Engine 6 block
    e6_out = _eng(e6, ("days_since_breakout", "volume_ratio"))
    e6_out["regime_gate_ok"] = brk_regime_ok
    if not brk_regime_ok:
        e6_out["skipped_reason"] = f"brk_aggressive_only=True blocks BRK in {regime_label} regime"

    return {
        "ticker": sym,
        "live_params": {
            "rs_threshold":      _LIVE_PARAMS.rs_threshold,
            "cci_threshold":     _LIVE_PARAMS.cci_threshold,
            "ema_distance":      _LIVE_PARAMS.ema_distance,
            "score_threshold":   _LIVE_PARAMS.score_threshold,
            "pullback_weight":   _LIVE_PARAMS.pullback_weight,
            "breakout_weight":   _LIVE_PARAMS.breakout_weight,
            "base_weight":       _LIVE_PARAMS.base_weight,
            "brk_aggressive_only": _LIVE_PARAMS.brk_aggressive_only,
            "brk_vol_mult":      _LIVE_PARAMS.brk_vol_mult,
            "brk_donchian_n":    _LIVE_PARAMS.brk_donchian_n,
            "base_vol_ratio":    _LIVE_PARAMS.base_vol_ratio,
            "base_quality_min":  _LIVE_PARAMS.base_quality_min,
        },
        "gates": {
            "rs_threshold_pass":  rs_threshold_gate,
            "rs_score":           round(float(rs_score), 4),
            "rs_threshold":       _LIVE_PARAMS.rs_threshold,
            "regime":             regime_label,
            "is_bullish":         is_bullish,
            "brk_regime_ok":      brk_regime_ok,
        },
        "regime": {
            "is_bullish": is_bullish,
            "spy_close":  regime_row.get("spy_close"),
            "spy_20ema":  regime_row.get("spy_20ema"),
            "label":      regime_label,
        },
        "rs": {
            "ratio":    rs_ratio,
            "blue_dot": rs_blue_dot,
            "rs_score": round(float(rs_score), 4),
        },
        "indicators": {
            "close":       round(lc, 2),
            "ema8":        round(l8, 2)   if l8   is not None else None,
            "ema20":       round(l20, 2)  if l20  is not None else None,
            "sma50":       round(l50, 2)  if l50  is not None else None,
            "cci":         round(lcci, 1) if lcci is not None else None,
            "above_ema8":  bool(l8  is not None and lc > l8),
            "above_ema20": bool(l20 is not None and lc > l20),
            "above_sma50": bool(l50 is not None and lc > l50),
        },
        "zones":   zones,
        "engine2": e2_out,
        "engine3": e3_out,
        "engine5": e5_out,
        "engine6": e6_out,
    }


def _build_v5_analysis_fields(
    best_setup: dict | None,
    signals: dict,
    regime_score: int,
) -> dict:
    """
    Compute V5 extended analysis fields for the /api/analyze endpoint.

    Parameters
    ----------
    best_setup   : best matching setup from DB for this ticker, or None
    signals      : existing signals dict (price, vol_ratio, rs_score, etc.)
    regime_score : current Engine 0 regime score (0–100)

    Returns
    -------
    dict with: detected_setup, setup_quality_score, rs_rank, regime_alignment,
               entry_quality, price_risk_pct, risk_level, reject_reasons
    """
    reject_reasons: list[str] = []

    # ── detected setup ────────────────────────────────────────────────────
    detected_setup      = best_setup.get("setup_type")   if best_setup else None
    setup_quality_score = int(best_setup.get("setup_score") or 0) if best_setup else 0
    rs_rank_raw         = best_setup.get("rs_rank")      if best_setup else None
    rs_rank             = float(rs_rank_raw) if rs_rank_raw is not None else None

    # ── reject reasons (ALL conditions checked, ALL failures collected) ───
    if rs_rank is not None and rs_rank < 70:
        reject_reasons.append(
            "Weak relative strength — RS rank below minimum threshold (70th percentile)"
        )
    elif rs_rank is None:
        reject_reasons.append(
            "Relative strength rank unavailable — insufficient price history or no recent scan"
        )

    if detected_setup is None:
        reject_reasons.append(
            "No valid setup pattern detected under current strategy rules"
        )

    if regime_score < 40:
        reject_reasons.append(
            "Market regime is defensive — conditions do not support new entries"
        )

    if best_setup and (setup_quality_score or 0) < 70:
        reject_reasons.append(
            "Setup detected but unified score is below the minimum quality threshold (70)"
        )

    # ── regime alignment ─────────────────────────────────────────────────
    if regime_score >= 70:
        regime_alignment = "STRONG"
    elif regime_score >= 40:
        regime_alignment = "MODERATE"
    else:
        regime_alignment = "WEAK"

    # ── entry quality ────────────────────────────────────────────────────
    _d = best_setup.get("distance_pct") if best_setup else None
    distance_pct = float(_d) if _d is not None else 999
    vol_ratio    = float(signals.get("vol_ratio") or 0)
    rs_blue_dot  = bool(best_setup.get("rs_blue_dot")) if best_setup else False

    if distance_pct < 0.01 and vol_ratio > 1.5 and rs_blue_dot:
        entry_quality = "IDEAL"
    elif distance_pct < 0.03 or vol_ratio > 1.0:
        entry_quality = "ACCEPTABLE"
    else:
        entry_quality = "EXTENDED"

    # ── price risk ────────────────────────────────────────────────────────
    price_risk_pct: float | None = None
    risk_level = "UNKNOWN"
    if best_setup:
        entry_p = best_setup.get("entry") or 0
        stop_p  = best_setup.get("stop_loss") or 0
        if entry_p > 0 and stop_p > 0:
            price_risk_pct = (entry_p - stop_p) / entry_p
            if price_risk_pct < 0.02:
                risk_level = "LOW"
            elif price_risk_pct < 0.04:
                risk_level = "MODERATE"
            else:
                risk_level = "HIGH"

    return {
        "detected_setup":      detected_setup,
        "setup_quality_score": setup_quality_score,
        "rs_rank":             round(rs_rank, 1) if rs_rank is not None else None,
        "regime_alignment":    regime_alignment,
        "entry_quality":       entry_quality,
        "price_risk_pct":      round(price_risk_pct * 100, 2) if price_risk_pct is not None else None,
        "risk_level":          risk_level,
        "reject_reasons":      reject_reasons,
    }


async def _on_demand_score_ticker(
    ticker: str,
    df: "pd.DataFrame",
    spy_df: "pd.DataFrame",
) -> Optional[dict]:
    """
    Run the full engine pipeline on a single ticker on demand.
    Used by analyze_ticker when the stock has no existing DB setup.

    Returns the highest-scored setup dict (with setup_score), or None.
    """
    import asyncio as _asyncio
    loop = _asyncio.get_event_loop()

    # ── RS rank ──────────────────────────────────────────────────────────────
    rs_rank: float = _last_rs_rank_map.get(ticker, 0.0)
    if rs_rank == 0.0:
        # Ticker not in last scan map — estimate from 12m return vs SPY
        try:
            n252 = min(252, len(df) - 1, len(spy_df) - 1)
            _sr = float(df["Close"].iloc[-1] / df["Close"].iloc[-(n252 + 1)] - 1)
            _spy_r = float(spy_df["Close"].iloc[-1] / spy_df["Close"].iloc[-(n252 + 1)] - 1)
            # Linear mapping: 0.25 outperformance ≈ rank 100, -0.25 ≈ rank 0
            rs_rank = float(min(99.0, max(1.0, 50.0 + (_sr - _spy_r) * 150.0)))
        except Exception:
            rs_rank = 50.0

    # ── RS score (63-day raw) ────────────────────────────────────────────────
    try:
        n63 = min(63, len(df) - 1, len(spy_df) - 1)
        _s63 = float(df["Close"].iloc[-1] / df["Close"].iloc[-(n63 + 1)] - 1)
        _spy63 = float(spy_df["Close"].iloc[-1] / spy_df["Close"].iloc[-(n63 + 1)] - 1)
        rs_score = _s63 - _spy63
        spy_3m = _spy63
    except Exception:
        rs_score = 0.0
        spy_3m = 0.0

    # ── RS ratio / blue dot ──────────────────────────────────────────────────
    try:
        _spy_aligned = spy_df["Close"].reindex(df.index, method="ffill")
        _rs_line = df["Close"] / _spy_aligned
        rs_ratio = float(_rs_line.iloc[-1])
        rs_52w_high = float(_rs_line.rolling(min(252, len(_rs_line))).max().iloc[-1])
        rs_blue_dot = rs_ratio >= rs_52w_high * 0.995
    except Exception:
        rs_ratio = 1.0
        rs_52w_high = 1.0
        rs_blue_dot = False

    # ── Regime ───────────────────────────────────────────────────────────────
    try:
        _regime_row = await get_latest_regime(DB_PATH)
        _regime_str = _regime_row.get("regime", "SELECTIVE") if _regime_row else "SELECTIVE"
        _regime_score_val = int(_regime_row.get("regime_score", 50) or 50) if _regime_row else 50
    except Exception:
        _regime_str = "SELECTIVE"
        _regime_score_val = 50
    regime = {"regime": _regime_str, "regime_score": _regime_score_val, "is_bullish": _regime_str != "DEFENSIVE"}

    top_sectors = _last_top_sectors or []
    sector = SECTORS.get(ticker, "Unknown")

    # ── Engine 1: SR zones ───────────────────────────────────────────────────
    try:
        zones = await loop.run_in_executor(None, calculate_sr_zones, ticker, df)
    except Exception:
        zones = []

    collected: list = []

    # ── Engine 2: VCP / WATCHLIST ────────────────────────────────────────────
    try:
        _vcp = await loop.run_in_executor(
            None, scan_vcp, ticker, df, zones, spy_3m,
            rs_ratio, rs_52w_high, rs_blue_dot, rs_score,
        )
        if _vcp:
            _vcp["sector"] = sector
            collected.append(_vcp)
    except Exception:
        pass

    # WATCHLIST (near-breakout approaching)
    try:
        from engines.engine2 import scan_near_breakout as _snb
        _wl = await loop.run_in_executor(None, _snb, ticker, df, zones)
        if _wl:
            _wl["sector"] = sector
            _wl["rs_blue_dot"] = rs_blue_dot
            collected.append(_wl)
    except Exception:
        pass

    # ── Engine 3: Pullback ───────────────────────────────────────────────────
    try:
        _tl = await loop.run_in_executor(None, detect_trendline, ticker, df)
        _pb, _ = await loop.run_in_executor(
            None, scan_pullback_scored, ticker, df, zones, _LIVE_PARAMS, _tl, rs_score, _regime_str
        )
        if _pb:
            _pb["sector"] = sector
            _pb["rs_score"] = rs_score
            collected.append(_pb)
    except Exception:
        pass

    # ── Engine 5: Base ───────────────────────────────────────────────────────
    try:
        from engines.engine5 import scan_base_pattern as _sbp
        _base = await loop.run_in_executor(
            None, _sbp, ticker, df, spy_3m,
            rs_ratio, rs_52w_high, rs_blue_dot, rs_score, zones, _LIVE_PARAMS,
        )
        if _base:
            _base["sector"] = sector
            _base["rs_score"] = rs_score
            collected.append(_base)
    except Exception:
        pass

    # ── Engine 6: ResBreakout ────────────────────────────────────────────────
    try:
        from engines.engine6 import scan_resistance_breakout as _srb
        _brk = await loop.run_in_executor(None, _srb, ticker, df, zones, False, _LIVE_PARAMS)
        if _brk:
            _brk["sector"] = sector
            _brk["rs_score"] = rs_score
            _brk["rs_blue_dot"] = rs_blue_dot
            collected.append(_brk)
    except Exception:
        pass

    if not collected:
        return None

    # ── Score all, pick best (min_score=0 — caller decides what to show) ─────
    _scored = score_and_filter_setups(
        collected, {ticker: rs_rank}, regime, top_sectors, min_score=0
    )
    if not _scored:
        return None

    best = _scored[0]
    best["rs_rank"] = round(rs_rank, 1)
    best["on_demand"] = True   # flag so frontend can indicate this is a live compute
    return best


@app.get("/api/analyze/{ticker}")
async def analyze_ticker(ticker: str):
    """Full technical analysis for any ticker."""
    import yfinance as yf
    import pandas as pd
    ticker = ticker.upper().strip()

    try:
        regime_score = 50  # neutral fallback; overwritten below after DB fetch
        raw = yf.download(ticker, period="1y", auto_adjust=True, progress=False)
        if raw is None or raw.empty or len(raw) < 60:
            return {
                "ticker": ticker, "score": 0, "setup_type": None,
                "entry": None, "stop_loss": None, "take_profit": None, "rr": None,
                "verdict": "NO DATA", "verdict_color": "halt",
                "quality": "No Data", "narrative": "Insufficient price history to perform analysis.",
                "signals": {},
                **_build_v5_analysis_fields(None, {}, 50),
            }

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = raw.rename(columns=str.title).copy()

        close   = float(df["Close"].iloc[-1])
        ema20   = float(df["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
        sma50   = float(df["Close"].rolling(50).mean().iloc[-1])
        vol_50  = float(df["Volume"].rolling(50).mean().iloc[-1]) if "Volume" in df.columns else 1.0
        vol_now = float(df["Volume"].iloc[-1]) if "Volume" in df.columns else 1.0
        vol_ratio = (vol_now / vol_50) if vol_50 > 0 else 1.0

        spy_df_analyze = None
        try:
            spy_raw = yf.download("SPY", period="1y", auto_adjust=True, progress=False)
            if isinstance(spy_raw.columns, pd.MultiIndex):
                spy_raw.columns = spy_raw.columns.get_level_values(0)
            spy_df_analyze = spy_raw.rename(columns=str.title).copy()
            spy_close = spy_df_analyze["Close"]
            n = min(63, len(df) - 1, len(spy_close) - 1)
            stock_ret = float(df["Close"].iloc[-1] / df["Close"].iloc[-(n + 1)] - 1)
            spy_ret   = float(spy_close.iloc[-1] / spy_close.iloc[-(n + 1)] - 1)
            rs_score  = stock_ret - spy_ret
        except Exception:
            rs_score = 0.0

        signals = {
            "price":       close,
            "ema20":       ema20,
            "sma50":       sma50,
            "above_ema20": close > ema20,
            "above_sma50": close > sma50,
            "vol_ratio":   round(vol_ratio, 2),
            "rs_score":    round(rs_score, 4),
        }

        from database import get_setups_by_ticker
        existing = await get_setups_by_ticker(DB_PATH, ticker)
        best_setup = None
        if existing:
            best_setup = max(existing, key=lambda s: s.get("setup_score") or 0)
            signals["vol_ratio"] = best_setup.get("vol_ratio", signals["vol_ratio"])
            signals["rs_score"]  = best_setup.get("rs_score",  signals["rs_score"])

        # ── On-demand scoring for tickers not in the latest scan ─────────────
        if best_setup is None and spy_df_analyze is not None:
            try:
                best_setup = await _on_demand_score_ticker(ticker, df, spy_df_analyze)
                if best_setup:
                    signals["vol_ratio"] = best_setup.get("vol_ratio", signals["vol_ratio"])
                    signals["rs_score"]  = best_setup.get("rs_score",  signals["rs_score"])
                    log.info("On-demand score for %s: %s  score=%s",
                             ticker, best_setup.get("setup_type"), best_setup.get("setup_score"))
            except Exception as _ode:
                log.warning("On-demand scoring failed for %s: %s", ticker, _ode)

        # Fetch current regime score for V5 alignment fields
        try:
            regime_data  = await get_latest_regime(DB_PATH)
            regime_score = int(regime_data.get("regime_score") or 50) if regime_data else 50
        except Exception:
            regime_score = 50  # neutral fallback

        analysis = _generate_analysis_narrative(ticker, signals, best_setup)

        return {
            "ticker":      ticker,
            "score":       int(best_setup.get("setup_score") or 0) if best_setup else 0,
            "setup_type":  best_setup.get("setup_type")   if best_setup else None,
            "entry":       best_setup.get("entry")        if best_setup else None,
            "stop_loss":   best_setup.get("stop_loss")    if best_setup else None,
            "take_profit": best_setup.get("take_profit")  if best_setup else None,
            "rr":          best_setup.get("rr")           if best_setup else None,
            **analysis,
            "signals":     signals,
            **_build_v5_analysis_fields(best_setup, signals, regime_score),
        }

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return {
            "ticker": ticker, "score": 0, "setup_type": None,
            "entry": None, "stop_loss": None, "take_profit": None, "rr": None,
            "verdict": "ERROR", "verdict_color": "halt",
            "quality": "Error", "narrative": f"Analysis failed: {str(exc)[:120]}",
            "signals": {},
            **_build_v5_analysis_fields(None, {}, 50),
        }


@app.get("/api/chart/{ticker}")
async def get_chart_data(ticker: str):
    """
    Returns chart-ready payload for lightweight-charts:
      candles  – raw OHLCV (Open/High/Low/Close)
      ema8     – 8-period EMA of Adj Close
      ema20    – 20-period EMA of Adj Close
      sma50    – 50-period SMA of Adj Close
      cci      – 20-period CCI
      sr_zones – from last scan DB (pre-computed)

    The candle OHLC uses raw prices (standard charting convention).
    Indicators are calculated on Adj Close (adjusted for splits/dividends).
    """
    sym = ticker.upper()
    df = await _fetch(sym)

    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"No data for {sym}")
    if len(df) < 55:
        raise HTTPException(status_code=422, detail=f"Insufficient history for {sym}")

    adj = "Adj Close" if "Adj Close" in df.columns else "Close"
    close_adj = df[adj]
    high = df["High"]
    low = df["Low"]

    # Indicators on Adj Close
    ema8 = _ema(close_adj, 8)
    ema20 = _ema(close_adj, 20)
    sma50 = _sma(close_adj, 50)
    cci20 = _cci(high, low, close_adj, 20)

    def _series(idx, vals, dec=2):
        out = []
        for ts, v in zip(idx, vals):
            if pd.notna(v):
                out.append({"time": ts.strftime("%Y-%m-%d"), "value": round(float(v), dec)})
        return out

    # Raw OHLCV candles
    candles = []
    for ts, row in df.iterrows():
        o = row.get("Open", np.nan)
        h = row.get("High", np.nan)
        l = row.get("Low", np.nan)
        c = row.get("Close", np.nan)   # raw close for candle display
        v = row.get("Volume", 0)
        if all(pd.notna(x) for x in [o, h, l, c]):
            candles.append(
                {
                    "time": ts.strftime("%Y-%m-%d"),
                    "open": round(float(o), 2),
                    "high": round(float(h), 2),
                    "low": round(float(l), 2),
                    "close": round(float(c), 2),
                    "volume": int(v) if pd.notna(v) else 0,
                }
            )

    # S/R zones: try DB first (fast); fall back to fresh Engine 1 computation
    # so that manually-searched tickers always see their KDE bands.
    zones = await get_sr_zones_for_ticker_from_db(DB_PATH, sym)
    if not zones:
        try:
            loop = asyncio.get_event_loop()
            zones = await loop.run_in_executor(None, calculate_sr_zones, sym, df)
        except Exception as exc:
            log.warning("Fresh zone calculation failed for %s: %s", sym, exc)
            zones = []

    # Detect trendline (fresh computation for chart display)
    trendline = None
    try:
        loop = asyncio.get_event_loop()
        trendline = await loop.run_in_executor(None, detect_trendline, sym, df)
    except Exception as exc:
        log.warning("Trendline detection failed %s: %s", sym, exc)

    # Fetch latest base setup for this ticker (for chart overlay)
    base_setup = None
    try:
        all_base = await get_latest_setups(DB_PATH, setup_type="BASE")
        for s in all_base:
            if s.get("ticker") == sym and s.get("geometry"):
                base_setup = {
                    "base_type": s.get("base_type"),
                    "geometry": s["geometry"],
                    "entry": s.get("entry"),
                    "stop_loss": s.get("stop_loss"),
                    "signal": s.get("signal"),
                    "quality_score": s.get("quality_score"),
                }
                break
    except Exception as exc:
        log.warning("Base setup lookup failed for %s: %s", sym, exc)

    # SMA 200 for chart display
    sma200 = _sma(close_adj, 200)

    # ATR (14-period) for chart metadata
    atr14 = _atr(high, low, close_adj, 14)
    last_atr = float(atr14.iloc[-1]) if pd.notna(atr14.iloc[-1]) else None
    last_close = float(close_adj.iloc[-1]) if pd.notna(close_adj.iloc[-1]) else None
    atr_pct = round(last_atr / last_close * 100, 2) if last_atr and last_close else None

    # Above 200 SMA?
    last_sma200 = float(sma200.iloc[-1]) if pd.notna(sma200.iloc[-1]) else None
    above_200sma = (last_close > last_sma200) if last_close and last_sma200 else None

    # Ticker metadata from yfinance info (name, sector, industry, market cap)
    ticker_info = {
        "name": None, "sector": None, "industry": None,
        "market_cap": None, "atr": round(last_atr, 2) if last_atr else None,
        "atr_pct": atr_pct, "above_200sma": above_200sma,
    }
    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: yf.Ticker(sym).info)
        ticker_info["name"] = info.get("shortName") or info.get("longName")
        ticker_info["sector"] = info.get("sector")
        ticker_info["industry"] = info.get("industry")
        ticker_info["market_cap"] = info.get("marketCap")
    except Exception as exc:
        log.warning("Could not fetch info for %s: %s", sym, exc)

    # Earnings date — next scheduled earnings (from yfinance calendar)
    earnings_date: Optional[str] = None
    try:
        loop = asyncio.get_event_loop()
        cal = await loop.run_in_executor(None, lambda: yf.Ticker(sym).calendar)
        if isinstance(cal, dict):
            ed_list = cal.get("Earnings Date", [])
            if ed_list:
                ed = ed_list[0]
                if hasattr(ed, "strftime"):
                    earnings_date = ed.strftime("%Y-%m-%d")
                elif isinstance(ed, str):
                    earnings_date = ed[:10]
    except Exception as exc:
        log.warning("Could not fetch earnings date for %s: %s", sym, exc)

    # RS Line for chart display — compute fresh against SPY
    rs_line_series: list = []
    rs_52w_high_val: Optional[float] = None
    rs_blue_dot_chart: bool = False
    try:
        spy_df_chart = await _fetch("SPY")
        if spy_df_chart is not None and not spy_df_chart.empty:
            spy_adj_col = "Adj Close" if "Adj Close" in spy_df_chart.columns else "Close"
            spy_close_chart = spy_df_chart[spy_adj_col]
            common_dates = close_adj.index.intersection(spy_close_chart.index)
            if len(common_dates) >= MIN_CANDLES_FOR_RS:
                rs_vals = (close_adj[common_dates] / spy_close_chart[common_dates]).iloc[-MIN_CANDLES_FOR_RS:]
                rs_52w_high_val = round(float(rs_vals.max()), 4)
                rs_blue_dot_chart = float(rs_vals.iloc[-1]) >= rs_52w_high_val * (1 - RS_BLUE_DOT_TOLERANCE_PCT)
                for ts, v in rs_vals.items():
                    if pd.notna(v):
                        rs_line_series.append({"time": ts.strftime("%Y-%m-%d"), "value": round(float(v), 4)})
    except Exception as exc:
        log.warning("RS line chart calculation failed for %s: %s", sym, exc)

    # Inject WATCHLIST pivot resistance into zones if Engine 1 missed it.
    # scan_res_breakout_near finds confirmed pivot highs independently;
    # those levels are not saved to sr_zones, so the chart would show no line.
    try:
        async with aiosqlite.connect(DB_PATH, timeout=10) as _wdb:
            _wdb.row_factory = aiosqlite.Row
            async with _wdb.execute(
                """SELECT metadata FROM scan_setups
                   WHERE ticker=? AND setup_type='WATCHLIST'
                   ORDER BY scan_timestamp DESC LIMIT 3""",
                (sym,),
            ) as _wcur:
                wl_rows = await _wcur.fetchall()
        for _wr in wl_rows:
            _meta = json.loads(_wr["metadata"] or "{}")
            _rl = _meta.get("resistance_level")
            if not _rl or not isinstance(_rl, (int, float)) or _rl <= 0:
                continue
            _already = any(abs(z["level"] - _rl) / _rl < 0.015 for z in zones)
            if _already:
                continue
            _atr_w = last_atr if last_atr else _rl * 0.005
            zones.append({
                "level": round(_rl, 2),
                "upper": round(_rl + 0.1 * _atr_w, 2),
                "lower": round(_rl - 0.1 * _atr_w, 2),
                "type": "RESISTANCE",
                "source": "watchlist_pivot",
                "is_primary": bool(last_close and abs(_rl - last_close) / last_close <= 0.05),
            })
            break  # one resistance injection is enough
    except Exception as _wexc:
        log.warning("Watchlist zone injection failed for %s: %s", sym, _wexc)

    return {
        "ticker": sym,
        "candles": candles,
        "ema8": _series(df.index, ema8),
        "ema20": _series(df.index, ema20),
        "sma50": _series(df.index, sma50),
        "sma200": _series(df.index, sma200),
        "cci": _series(df.index, cci20, dec=1),
        "rs_line": rs_line_series,
        "rs_52w_high": rs_52w_high_val,
        "rs_blue_dot": rs_blue_dot_chart,
        "sr_zones": zones,
        "trendline": trendline,
        "base_setup": base_setup,
        "ticker_info": ticker_info,
        "earnings_date": earnings_date,
    }


# ────────────────────────────────────────────────────────────────────────────
# Trade endpoints
# ────────────────────────────────────────────────────────────────────────────

class TradeIn(BaseModel):
    ticker:      str
    entry_price: float
    quantity:    float
    stop_loss:   float
    targets:     List[float] = Field(..., min_length=1, max_length=3)
    entry_date:  str
    notes:       str = ""
    setup_type:  str = ""


class CloseTradeIn(BaseModel):
    exit_price: Optional[float] = None
    exit_date:  Optional[str]   = None


async def _enrich_trade(trade: Dict) -> Dict:
    """
    Fetch fresh market data for a trade and add:
      current_price, pl_dollar, pl_pct,
      ema8, ema20, health ('HOLD' | 'CAUTION' | 'EXIT')
    Falls back gracefully if the fetch fails.
    """
    result = {**trade, "current_price": None, "pl_dollar": None,
              "pl_pct": None, "ema8": None, "ema20": None, "health": "UNKNOWN"}
    try:
        df = await _fetch(trade["ticker"])
        if df is None or len(df) < 25:
            return result

        adj = "Adj Close" if "Adj Close" in df.columns else "Close"
        close = df[adj]
        high  = df["High"]
        low   = df["Low"]

        ema8_s  = _ema(close, 8)
        ema20_s = _ema(close, 20)
        cci20_s = _cci(high, low, close, 20)

        lc   = float(close.iloc[-1])
        l8   = float(ema8_s.iloc[-1])
        l20  = float(ema20_s.iloc[-1])

        # CCI hook below 100: was above 100, now crossed below (bearish)
        cci_hook_below = False
        if len(cci20_s.dropna()) >= 2:
            cci_prev = float(cci20_s.dropna().iloc[-2])
            cci_last = float(cci20_s.dropna().iloc[-1])
            cci_hook_below = cci_prev > 100 and cci_last < 100

        # Health signal
        if lc < l20 or cci_hook_below:
            health = "EXIT"
        elif lc < l8:          # above 20 EMA but below 8 EMA
            health = "CAUTION"
        else:
            health = "HOLD"

        ep   = trade["entry_price"]
        qty  = trade["quantity"]
        pl_d = round((lc - ep) * qty, 2)
        pl_p = round((lc / ep - 1) * 100, 2) if ep > 0 else 0.0

        # EMA20 trailing stop: floor is previous bar's EMA20 (no lookahead).
        prev_ema20_live = (float(ema20_s.iloc[-2])
                           if len(ema20_s.dropna()) >= 2 else None)
        trailing_stop = _compute_live_trail(
            current_stop  = float(trade["stop_loss"]),
            entry_price   = float(trade["entry_price"]),
            current_price = lc,
            prev_ema20    = prev_ema20_live,
            current_ema20 = l20,
        )

        is_risk_free = trailing_stop > trade["entry_price"]

        result.update({
            "current_price": round(lc, 2),
            "pl_dollar":     pl_d,
            "pl_pct":        pl_p,
            "ema8":          round(l8, 2),
            "ema20":         round(l20, 2),
            "health":        health,
            "trailing_stop": round(trailing_stop, 2),
            "is_risk_free":  is_risk_free,
        })
    except Exception as exc:
        log.warning("Trade enrichment failed %s: %s", trade["ticker"], exc)
    return result


@app.post("/api/trades", status_code=201)
async def create_trade(body: TradeIn):
    """Add a new active trade to the portfolio."""
    trade_id = await add_trade(DB_PATH, body.model_dump())
    return {"id": trade_id, "status": "active", **body.model_dump()}


@app.get("/api/trades")
async def list_trades():
    """
    Return all active trades enriched with live price, P/L, and health signal.
    Fetches are run concurrently (bounded by the shared semaphore).
    """
    trades = await get_trades(DB_PATH, status="active")
    if not trades:
        return {"trades": [], "count": 0}

    enriched = await asyncio.gather(*[_enrich_trade(t) for t in trades])
    return {"trades": list(enriched), "count": len(enriched)}


@app.get("/api/diagnostics/report")
async def diagnostics_report():
    """
    Strategy-level performance diagnostics computed from closed trades.

    Returns five sections:
      summary             — overall portfolio metrics (total_trades, profit_factor,
                            win_rate, avg_R, expectancy, max_drawdown, equity_curve_R)
      setup_breakdown     — metrics per setup type (with low_sample flag)
      ticker_distribution — ranked ticker R contribution
      regime_performance  — metrics bucketed by market regime tier
      regime_stability    — flip frequency and duration metrics from scan history
    """
    try:
        raw_trades, regime_history = await asyncio.gather(
            get_closed_trades(DB_PATH, limit=10000),
            get_regime_history(DB_PATH),
        )

        # Retrospective regime enrichment: for each closed trade look up the
        # closest market_regime scan at or before entry_date.
        # Single bulk fetch + in-memory binary search — O(n log m).
        normalized = []
        if regime_history:
            from bisect import bisect_right as _bisect_right
            ts_dates = [h["scan_timestamp"][:10] for h in regime_history]

            for t in raw_trades:
                entry_date = (t.get("entry_date") or "")[:10]
                idx = _bisect_right(ts_dates, entry_date) - 1
                if idx >= 0:
                    regime_label = regime_history[idx]["regime"] or "UNKNOWN"
                    regime_score = regime_history[idx]["regime_score"] or 0
                else:
                    # entry_date predates all scans — use earliest available
                    regime_label = regime_history[0]["regime"] or "UNKNOWN"
                    regime_score = regime_history[0]["regime_score"] or 0
                normalized.append({
                    **t,
                    "close_price":  t.get("exit_price"),
                    "regime":       regime_label,
                    "regime_score": regime_score,
                    "status":       "closed",
                })
        else:
            # No regime data available — analytics still work; regime bucket = UNKNOWN
            for t in raw_trades:
                normalized.append({
                    **t,
                    "close_price":  t.get("exit_price"),
                    "regime":       "UNKNOWN",
                    "regime_score": 0,
                    "status":       "closed",
                })

        return {
            "summary":              compute_live_diagnostics(normalized),
            "setup_breakdown":      compute_setup_breakdown(normalized),
            "ticker_distribution":  compute_ticker_distribution(normalized),
            "regime_performance":   compute_regime_performance(normalized),
            "regime_stability":     compute_regime_stability(regime_history),
            "selective_analysis":   compute_selective_breakdown(normalized),
        }
    except Exception as exc:
        log.error("diagnostics_report failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to generate diagnostics report")


@app.post("/api/diagnostics/backtest/run", status_code=202)
async def run_backtest_diagnostics(
    background_tasks: BackgroundTasks,
    req: BacktestRunRequest = Body(default=BacktestRunRequest()),
):
    """
    Trigger a background portfolio-coordinated backtest.
    Accepts optional JSON body (BacktestRunRequest). No body = defaults used.
    Returns 409 if a run is already in progress.
    """
    global _backtest_diag_status
    if _backtest_diag_status["status"] == "running":
        raise HTTPException(status_code=409, detail="Backtest already running")

    all_tickers = list(ACTIVE_UNIVERSE) if ACTIVE_UNIVERSE else list(SCAN_UNIVERSE)
    tickers     = all_tickers[:req.ticker_count] if req.ticker_count else all_tickers

    _backtest_diag_status.update({
        "status":      "running",
        "done":        0,
        "total":       len(tickers),
        "phase":       1,
        "phase_label": "Loading tickers & computing signals",
    })

    config = BacktestConfig(
        start_date    = req.start_date,
        end_date      = req.end_date,
        max_positions = req.max_positions,
        ticker_count  = req.ticker_count,
        min_score     = req.min_score,
        setup_types   = req.setup_types,
    )

    async def _do_backtest():
        global _backtest_diag_status
        try:
            async def _progress(done: int, total: int):
                # Detect Phase 2 start: progress resets to 0 after Phase 1 completed
                if done == 0 and _backtest_diag_status["done"] > 0:
                    _backtest_diag_status["phase"]       = 2
                    _backtest_diag_status["phase_label"] = "Simulating portfolio day by day"
                _backtest_diag_status["done"]  = done
                _backtest_diag_status["total"] = total

            raw_trades = await run_portfolio_backtest_universe(
                tickers,
                config,
                params=BacktestParams(),
                progress_cb=_progress,
                sectors=SECTORS,
            )
            adapted = [_backtest_trade_to_analytics(t) for t in raw_trades]

            report = {
                "generated_at":        datetime.now(timezone.utc).isoformat(),
                "start_date":          req.start_date,
                "end_date":            req.end_date,
                "max_positions":       req.max_positions,
                "tickers_run":         len(tickers),
                "setup_types":         req.setup_types,
                "min_score":           req.min_score,
                "total_trades":        len(adapted),
                "summary":             compute_live_diagnostics(adapted),
                "setup_breakdown":     compute_setup_breakdown(adapted),
                "ticker_distribution": compute_ticker_distribution(adapted),
                "regime_performance":  compute_regime_performance(adapted),
                "selective_analysis":  compute_selective_breakdown(adapted),
                "trades":              raw_trades,
            }

            os.makedirs(os.path.dirname(BACKTEST_DIAG_CACHE_PATH), exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(BACKTEST_DIAG_CACHE_PATH))
            try:
                with os.fdopen(tmp_fd, "w") as f:
                    json.dump(_json_sanitize(report), f)
                os.replace(tmp_path, BACKTEST_DIAG_CACHE_PATH)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            now_iso = datetime.now(timezone.utc).isoformat()
            _backtest_diag_status.update({"status": "completed", "last_run": now_iso})
            log.info("Portfolio backtest complete: %d trades from %d tickers",
                     len(adapted), len(tickers))
        except Exception as exc:
            _backtest_diag_status["status"] = "failed"
            log.error("Portfolio backtest failed: %s", exc)

    background_tasks.add_task(_do_backtest)
    return {"status": "started", "tickers": len(tickers)}


@app.get("/api/diagnostics/backtest/status")
async def backtest_diagnostics_status():
    """Poll progress of the background V4 backtest run."""
    return {
        "status":      _backtest_diag_status["status"],
        "done":        _backtest_diag_status["done"],
        "total":       _backtest_diag_status["total"],
        "last_run":    _backtest_diag_status["last_run"],
        "phase":       _backtest_diag_status["phase"],
        "phase_label": _backtest_diag_status["phase_label"],
    }


@app.get("/api/diagnostics/backtest")
async def backtest_diagnostics_report():
    """
    Return the cached V4 baseline backtest diagnostics report.
    Returns 404 if no run has been completed yet.
    """
    if not os.path.exists(BACKTEST_DIAG_CACHE_PATH):
        raise HTTPException(
            status_code=404,
            detail="No backtest cache found. POST /api/diagnostics/backtest/run to generate.",
        )
    try:
        with open(BACKTEST_DIAG_CACHE_PATH, "r") as f:
            return json.load(f)
    except Exception as exc:
        log.error("Failed to read backtest diagnostics cache: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to read backtest cache")


# ── IS / OOS Split endpoints ──────────────────────────────────────────────────

@app.post("/api/diagnostics/isoos/run", status_code=202)
async def run_isoos_diagnostics(
    background_tasks: BackgroundTasks,
    req: ISOOSRunRequest = Body(default=ISOOSRunRequest()),
):
    """
    Trigger IS/OOS split backtest. Runs two sequential portfolio backtests
    (IS period then OOS period) and caches combined results.
    Returns 409 if already running.
    """
    global _isoos_running, _isoos_status
    if _isoos_running:
        raise HTTPException(status_code=409, detail="IS/OOS backtest already running")

    all_tickers = list(ACTIVE_UNIVERSE) if ACTIVE_UNIVERSE else list(SCAN_UNIVERSE)
    tickers     = all_tickers[:req.ticker_count] if req.ticker_count else all_tickers

    _isoos_running = True
    _isoos_status.update({
        "status":     "running_is",
        "is_done":    False,
        "current":    0,
        "total":      len(tickers),
        "phase":      "is",
        "step_label": "Loading tickers & computing signals",
        "error":      None,
    })

    async def _do_isoos():
        global _isoos_running, _isoos_status
        try:
            # ── Phase IS ──────────────────────────────────────────────────
            async def _progress_is(done: int, total: int):
                if done == 0 and _isoos_status["current"] > 0:
                    _isoos_status["step_label"] = "Simulating portfolio day by day"
                _isoos_status["current"] = done
                _isoos_status["total"]   = total

            is_config = BacktestConfig(
                start_date    = req.is_start_date,
                end_date      = req.is_end_date,
                max_positions = req.max_positions,
                ticker_count  = req.ticker_count,
                min_score     = req.min_score,
                setup_types   = req.setup_types,
            )
            is_raw = await run_portfolio_backtest_universe(
                tickers, is_config, params=BacktestParams(), progress_cb=_progress_is,
                sectors=SECTORS,
            )
            is_adapted = [_backtest_trade_to_analytics(t) for t in is_raw]

            # ── Phase OOS ─────────────────────────────────────────────────
            _isoos_status.update({
                "status":     "running_oos",
                "phase":      "oos",
                "current":    0,
                "total":      len(tickers),
                "step_label": "Loading tickers & computing signals",
            })

            async def _progress_oos(done: int, total: int):
                if done == 0 and _isoos_status["current"] > 0:
                    _isoos_status["step_label"] = "Simulating portfolio day by day"
                _isoos_status["current"] = done
                _isoos_status["total"]   = total

            oos_config = BacktestConfig(
                start_date    = req.oos_start_date,
                end_date      = req.oos_end_date,
                max_positions = req.max_positions,
                ticker_count  = req.ticker_count,
                min_score     = req.min_score,
                setup_types   = req.setup_types,
            )
            oos_raw = await run_portfolio_backtest_universe(
                tickers, oos_config, params=BacktestParams(), progress_cb=_progress_oos,
                sectors=SECTORS,
            )
            oos_adapted = [_backtest_trade_to_analytics(t) for t in oos_raw]

            # ── Analytics & cache ─────────────────────────────────────────
            report = {
                "generated_at":   datetime.now(timezone.utc).isoformat(),
                "config": {
                    "is_start_date":  req.is_start_date,
                    "is_end_date":    req.is_end_date,
                    "oos_start_date": req.oos_start_date,
                    "oos_end_date":   req.oos_end_date,
                    "max_positions":  req.max_positions,
                    "setup_types":    req.setup_types,
                    "min_score":      req.min_score,
                },
                "is": {
                    "summary":         compute_live_diagnostics(is_adapted),
                    "setup_breakdown": compute_setup_breakdown(is_adapted),
                },
                "oos": {
                    "summary":         compute_live_diagnostics(oos_adapted),
                    "setup_breakdown": compute_setup_breakdown(oos_adapted),
                },
            }

            os.makedirs(os.path.dirname(ISOOS_DIAG_CACHE_PATH), exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(ISOOS_DIAG_CACHE_PATH))
            try:
                with os.fdopen(tmp_fd, "w") as f:
                    json.dump(_json_sanitize(report), f)
                os.replace(tmp_path, ISOOS_DIAG_CACHE_PATH)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            _isoos_status.update({
                "status":  "completed",
                "is_done": True,
                "phase":   "done",
            })
            log.info("IS/OOS backtest complete: IS=%d trades, OOS=%d trades",
                     len(is_adapted), len(oos_adapted))

        except Exception as exc:
            _isoos_status.update({
                "status": "failed",
                "error":  str(exc),
            })
            log.error("IS/OOS backtest failed: %s", exc)
        finally:
            _isoos_running = False
            if _isoos_status["status"] in ("running_is", "running_oos"):
                _isoos_status["status"] = "failed"

    background_tasks.add_task(_do_isoos)
    return {"status": "started", "tickers": len(tickers)}


@app.get("/api/diagnostics/isoos/status")
async def isoos_diagnostics_status():
    """Poll progress of the IS/OOS background backtest run."""
    return {
        "status":     _isoos_status["status"],
        "is_done":    _isoos_status["is_done"],
        "current":    _isoos_status["current"],
        "total":      _isoos_status["total"],
        "phase":      _isoos_status["phase"],
        "step_label": _isoos_status["step_label"],
        "error":      _isoos_status["error"],
    }


@app.get("/api/diagnostics/isoos")
async def isoos_diagnostics_report():
    """
    Return the cached IS/OOS split diagnostics report.
    Returns 404 if no run has been completed yet.
    """
    if not os.path.exists(ISOOS_DIAG_CACHE_PATH):
        raise HTTPException(
            status_code=404,
            detail="No IS/OOS cache found. POST /api/diagnostics/isoos/run to generate.",
        )
    try:
        with open(ISOOS_DIAG_CACHE_PATH, "r") as f:
            return json.load(f)
    except Exception as exc:
        log.error("Failed to read IS/OOS diagnostics cache: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to read IS/OOS cache")


@app.delete("/api/trades/{trade_id}", status_code=200)
async def delete_trade(trade_id: int, body: CloseTradeIn = None):
    """Close (soft-delete) an active trade, optionally recording exit price/date."""
    exit_price = body.exit_price if body else None
    exit_date  = body.exit_date  if body else None
    # Default exit_date to today if exit_price provided but date omitted
    if exit_price is not None and exit_date is None:
        from datetime import date as _date
        exit_date = _date.today().isoformat()
    ok = await close_trade(DB_PATH, trade_id, exit_price=exit_price, exit_date=exit_date)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found or already closed")
    return {"id": trade_id, "status": "closed"}


@app.get("/api/trades/closed")
async def list_closed_trades():
    """Return the 50 most recently closed trades with realised P/L."""
    trades = await get_closed_trades(DB_PATH)
    return {"trades": trades, "count": len(trades)}


@app.post("/api/send-digest")
async def send_digest_now(email: str):
    """
    Immediately build a digest from the latest DB data and send to the given email.
    Query: POST /api/send-digest?email=you@example.com
    """
    import re
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        raise HTTPException(status_code=422, detail="Invalid email address")

    regime = await get_latest_regime(DB_PATH) or {}
    vcp      = await get_latest_setups(DB_PATH, setup_type="VCP")
    watchlist= await get_latest_setups(DB_PATH, setup_type="WATCHLIST")
    res      = await get_latest_setups(DB_PATH, setup_type="RES_BREAKOUT")
    pb       = await get_latest_setups(DB_PATH, setup_type="PULLBACK")
    opt      = await get_latest_setups(DB_PATH, setup_type="OPTIONS_CATALYST")

    total = len(vcp) + len(watchlist) + len(res) + len(pb) + len(opt)
    if total == 0:
        raise HTTPException(status_code=409, detail="No scan data yet — run a scan first")

    # Enrich with SPY SMA50
    try:
        spy_df = await _fetch("SPY", semaphore=_semaphore)
        if spy_df is not None and len(spy_df) >= 50:
            from indicators import sma as _sma_fn
            adj_col = "Adj Close" if "Adj Close" in spy_df.columns else "Close"
            regime["spy_sma50"] = float(_sma_fn(spy_df[adj_col], 50).iloc[-1])
    except Exception as exc:
        log.warning("send-digest: could not compute SPY SMA50: %s", exc)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: _send_to(email, {
            "regime":           regime,
            "vcp":              vcp,
            "vcp_dry":          watchlist,
            "res_breakout":     res,
            "pullback":         pb,
            "options_catalyst": opt,
        }),
    )
    return {"ok": True, "email": email, "setups": total}


def _send_to(email: str, data: dict) -> None:
    """Send digest to an arbitrary email (overrides EMAIL_TO env var)."""
    import os as _os
    orig = _os.environ.get("EMAIL_TO")
    _os.environ["EMAIL_TO"] = email
    try:
        from email_digest import send_digest
        send_digest(data)
    finally:
        if orig is None:
            _os.environ.pop("EMAIL_TO", None)
        else:
            _os.environ["EMAIL_TO"] = orig
