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
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from indicators import ema as _ema, sma as _sma, cci as _cci, atr as _atr
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from constants import (
    CACHE_TTL_FAILURE,
    CACHE_TTL_SUCCESS,
    CONCURRENCY_LIMIT,
    DATA_FETCH_PERIOD,
    DB_PATH,
    DAYS_3_MONTHS,
    FETCH_BACKOFF_BASE,
    FETCH_MAX_RETRIES,
    MAX_TICKERS_PER_SCAN,
    MIN_CANDLES_FOR_ANALYSIS,
    MIN_CANDLES_FOR_RS,
    TRADING_DAYS_IN_YEAR,
)
from database import (
    complete_scan_run,
    get_latest_regime,
    get_latest_scan_timestamp,
    get_latest_setups,
    get_sr_zones_for_ticker_from_db,
    init_db,
    save_regime,
    save_scan_run,
    save_setup,
    batch_save_setups,
    save_sr_zones,
    add_trade,
    get_trades,
    close_trade,
)
from engines.engine0 import check_market_regime
from engines.engine1 import calculate_sr_zones
from engines.engine2 import scan_vcp, detect_trendline, scan_near_breakout
from engines.engine3 import scan_pullback, scan_relaxed_pullback
from engines.engine4 import calculate_rs_line, detect_rs_blue_dot, get_rs_stats, calculate_rs_score
from engines.engine5 import scan_base_pattern
from engines.engine6 import scan_resistance_breakout
from engines.engine7 import scan_options_catalyst
from tickers import SCAN_UNIVERSE
from validation import is_price_vital
from universe_builder import load_universe, UNIVERSE_FILE

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
# Universe & Sector loading (active_universe.json with tickers.py fallback)
# ────────────────────────────────────────────────────────────────────────────

ACTIVE_UNIVERSE = SCAN_UNIVERSE  # default fallback
SECTORS = {}

_universe_result = load_universe(UNIVERSE_FILE)
if _universe_result is not None:
    ACTIVE_UNIVERSE, SECTORS = _universe_result
    if len(ACTIVE_UNIVERSE) > MAX_TICKERS_PER_SCAN:
        log.warning(
            "Universe has %d tickers, capping to %d",
            len(ACTIVE_UNIVERSE), MAX_TICKERS_PER_SCAN,
        )
        ACTIVE_UNIVERSE = ACTIVE_UNIVERSE[:MAX_TICKERS_PER_SCAN]
    log.info("Loaded active universe: %d tickers from %s", len(ACTIVE_UNIVERSE), UNIVERSE_FILE)
else:
    log.info("No active_universe.json, using SCAN_UNIVERSE (%d tickers)", len(SCAN_UNIVERSE))
    try:
        with open("sectors.json", "r") as f:
            SECTORS = json.load(f)
        log.info("Loaded %d sectors from sectors.json (fallback)", len(SECTORS))
    except Exception as e:
        log.warning("Could not load sectors.json: %s", e)

# ────────────────────────────────────────────────────────────────────────────
# Shared state (single-process; safe with asyncio event loop)
# ────────────────────────────────────────────────────────────────────────────

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
        "total_tickers": 0,
        "total_duration_s": 0.0,
        "forced": False,
        "dry_run": False,
    },
    "dry_run_setups": None,
}
_semaphore: Optional[asyncio.Semaphore] = None
_ticker_cache: dict = {}  # ticker → (timestamp: float, df: Optional[pd.DataFrame])


# ────────────────────────────────────────────────────────────────────────────
# App lifecycle
# ────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _semaphore
    _semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    await init_db(DB_PATH)
    log.info("SQLite DB initialised at %s", DB_PATH)
    yield


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

async def _fetch(ticker: str, retry_count: int = 0) -> Optional[pd.DataFrame]:
    """
    Download daily OHLCV for one ticker with retry logic and exponential backoff.

    Returns a cached DataFrame if a fresh entry exists in _ticker_cache:
      - Successful fetches are cached for CACHE_TTL_SUCCESS seconds (4 h).
      - Failed fetches are negatively cached for CACHE_TTL_FAILURE seconds (15 min)
        so transient errors do not cause repeated retries within the same session.

    Semaphore is acquired per-attempt (not held across retries) to prevent
    deadlock when multiple tasks retry simultaneously.
    """
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
        async with _semaphore:
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
                if attempt < FETCH_MAX_RETRIES:
                    backoff_delay = FETCH_BACKOFF_BASE * (2 ** attempt)
                    log.warning(
                        "Fetch %s: failed with %s (attempt %d/%d), retrying in %.1fs...",
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
# Background scan worker
# ────────────────────────────────────────────────────────────────────────────

async def _run_scan(scan_ts: str, tickers: List[str], force: bool = False, dry_run: bool = False) -> None:
    """
    Full scan pipeline:
      Engine 0 → (if bullish) Engine 1 → Engine 2 + Engine 3
    Results written to SQLite; frontend reads from DB.
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
            "e2": {"vcp": 0, "watchlist": 0},
            "e3": {"pullback": 0, "relaxed": 0},
            "e5": {"cup_handle": 0, "flat_base": 0},
            "e6": {"res_breakout": 0},
            "e7": {"options_catalyst": 0},
            "total_tickers": 0,
            "total_duration_s": 0.0,
            "forced": force,
            "dry_run": dry_run,
        },
        dry_run_setups=None,
    )

    try:
        if not dry_run:
            await save_scan_run(DB_PATH, scan_ts)

        # ── Engine 0: Market regime ───────────────────────────────────────
        loop = asyncio.get_event_loop()
        regime_start = time.time()
        regime = await loop.run_in_executor(None, check_market_regime)
        regime_time = time.time() - regime_start
        if not dry_run:
            await save_regime(DB_PATH, scan_ts, regime)
        log.info(
            "Engine 0: %s  (SPY=%.2f  EMA20=%.2f)  [%.1fs]",
            regime["regime"],
            regime["spy_close"],
            regime["spy_20ema"],
            regime_time,
        )
        _scan_state["engine_stats"]["e0"] = {
            "spy_close": round(regime["spy_close"], 2),
            "spy_ema20": round(regime["spy_20ema"], 2),
            "is_bullish": regime["is_bullish"],
            "duration_s": round(regime_time, 1),
        }

        if not regime["is_bullish"] and not force:
            log.info("Market is BEARISH — RS calculations + Engines 2 & 3 disabled (0s saved)")
            _scan_state["engine_stats"]["total_tickers"] = 0
            _scan_state["engine_stats"]["total_duration_s"] = round(time.time() - scan_start_time, 1)
            if not dry_run:
                await complete_scan_run(DB_PATH, scan_ts, 0)
            _scan_state["last_completed"] = scan_ts
            return

        if not regime["is_bullish"] and force:
            log.info("Market is BEARISH — force=True, overriding halt gate")

        # ── SPY data (consolidated single fetch for 3m return + RS Line) ──
        # Only fetched when market is bullish; conditional RS calculation optimizes cycles
        spy_3m_return = 0.0
        spy_df_full = None
        spy_fetch_start = time.time()
        try:
            spy_df_full = await _fetch("SPY")
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

        # ── Per-ticker processing ─────────────────────────────────────────
        # Collect setups instead of saving individually for batch optimization
        collected_setups: List[Dict] = []
        dropped_tickers: List[str] = []  # Track tickers that failed all retries
        vcp_count = 0
        pb_count = 0
        base_count = 0
        res_count  = 0
        opt_count  = 0
        process_start_time = time.time()

        async def _process(ticker: str, idx: int) -> None:
            nonlocal vcp_count, pb_count, base_count, res_count, opt_count, dropped_tickers

            try:
                # ── Data Integrity Check ────────────────────────────────────
                # Skip tickers with empty/delisted data immediately
                df = await _fetch(ticker)
                if df is None or len(df) < MIN_CANDLES_FOR_ANALYSIS:
                    if df is None:
                        dropped_tickers.append(ticker)  # Record as dropped
                    log.debug("Skipped %s: insufficient data", ticker)
                    return

                # Deduplicate columns (belt-and-suspenders after _fetch)
                if df.columns.duplicated().any():
                    df = df.loc[:, ~df.columns.duplicated()]

                # Check for empty Close column or all-NaN values
                close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
                if close_col not in df.columns:
                    log.debug("Skipped %s: no valid price data", ticker)
                    return
                close_series = df[close_col]
                if isinstance(close_series, pd.DataFrame):
                    close_series = close_series.iloc[:, 0]
                if close_series.isna().all():
                    log.debug("Skipped %s: all-NaN price data", ticker)
                    return

                # ── Price Action Vitality — skip zombie / buyout-flatline stocks ──
                if not is_price_vital(df):
                    log.debug(
                        "Skipped %s: flatline/zombie stock "
                        "(10-day H-L range < 2%% of high)",
                        ticker,
                    )
                    return

                # ── Parallelize RS + S/R zone calculations (independent operations) ──
                rs_line = None
                rs_ratio = 0.0
                rs_52w_high = 0.0
                rs_blue_dot = False
                rs_score = 0.0
                zones: List[Dict] = []

                # Run RS and S/R zone calculations in parallel
                rs_task = None
                if spy_df_full is not None:
                    rs_task = loop.run_in_executor(None, calculate_rs_line, df, spy_df_full)

                sr_task = loop.run_in_executor(None, calculate_sr_zones, ticker, df)

                # Await both in parallel
                if rs_task:
                    try:
                        rs_line, zones = await asyncio.gather(rs_task, sr_task)
                    except Exception as exc:
                        log.warning("Parallel RS/SR calculation failed for %s: %s", ticker, exc)
                        rs_line = None
                        zones = await sr_task  # Fall back to SR-only
                else:
                    zones = await sr_task

                # Process RS results if available
                if rs_line and len(rs_line) >= MIN_CANDLES_FOR_RS:
                    try:
                        # Use .item() to safely convert numpy scalars to Python floats
                        rs_today = rs_line[-1]
                        rs_ratio = float(rs_today.item() if hasattr(rs_today, 'item') else rs_today)

                        rs_max = max(rs_line)
                        rs_52w_high = float(rs_max.item() if hasattr(rs_max, 'item') else rs_max)

                        rs_blue_dot = await loop.run_in_executor(
                            None, detect_rs_blue_dot, rs_line
                        )
                    except Exception as rs_exc:
                        log.warning("RS processing failed for %s: %s", ticker, rs_exc)
                        rs_ratio = 0.0
                        rs_52w_high = 0.0
                        rs_blue_dot = False
                if zones:
                    if not dry_run:
                        await save_sr_zones(DB_PATH, scan_ts, ticker, zones)
                    # engine_stats increments below are safe: _process() is an asyncio
                    # coroutine and never yields (no await) between the read and write
                    # of += 1, so there is no interleaving with other ticker coroutines.
                    _scan_state["engine_stats"]["e1"]["zones_saved"] += 1

                # Composite RS score (O'Neil formula)
                if spy_df_full is not None:
                    rs_score = await loop.run_in_executor(
                        None, calculate_rs_score, df, spy_df_full
                    )

                # Detect trendline early (used by VCP follow-up, near-breakout, and pullback)
                tl = await loop.run_in_executor(None, detect_trendline, ticker, df)

                # Engine 2: VCP breakout (with RS parameters for Path E)
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

                else:
                    # Only check near-breakout if not already a full setup
                    # Wrap entire near-breakout logic in try-except for robustness
                    try:
                        near = await loop.run_in_executor(
                            None, scan_near_breakout, ticker, df, zones, tl
                        )
                        if near:
                            # Sanitize near-breakout output: ensure numeric fields are proper floats
                            try:
                                near["entry"] = float(near.get("entry", 0.0))
                                near["distance_pct"] = float(near.get("distance_pct", 0.0))
                            except (ValueError, TypeError) as conv_err:
                                log.warning("Near-breakout conversion failed for %s: %s", ticker, conv_err)
                                return

                            near["sector"] = SECTORS.get(ticker, "Unknown")
                            near["rs_blue_dot"] = rs_blue_dot
                            collected_setups.append(near)
                            _scan_state["engine_stats"]["e2"]["watchlist"] += 1
                            log.info("  NEAR     %-6s  dist=%.1f%%", ticker, near["distance_pct"])
                    except Exception as near_exc:
                        log.warning("Near-breakout check failed for %s: %s", ticker, near_exc)
                        # Continue to pullback checks even if near-breakout fails

                # Engine 3: Tactical pullback (strict, then relaxed)
                pb = await loop.run_in_executor(None, scan_pullback, ticker, df, zones, tl)
                if pb:
                    # Sanitize pullback output
                    try:
                        pb["entry"] = float(pb.get("entry", 0.0))
                        pb["stop_loss"] = float(pb.get("stop_loss", 0.0))
                        pb["take_profit"] = float(pb.get("take_profit", 0.0))
                        pb["rr"] = float(pb.get("rr", 2.0))
                    except (ValueError, TypeError) as conv_err:
                        log.warning("Pullback conversion failed for %s: %s", ticker, conv_err)
                        return

                    pb["sector"] = SECTORS.get(ticker, "Unknown")
                    collected_setups.append(pb)
                    pb_count += 1
                    _scan_state["engine_stats"]["e3"]["pullback"] += 1
                    log.info("  PULLBACK %-6s  entry=%.2f", ticker, pb["entry"])
                else:
                    # Only check relaxed if no strict pullback found
                    try:
                        pb_relaxed = await loop.run_in_executor(
                            None, scan_relaxed_pullback, ticker, df, zones, tl
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

                            pb_relaxed["sector"] = SECTORS.get(ticker, "Unknown")
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
                        spy_3m_return, rs_ratio, rs_52w_high, rs_blue_dot, rs_score
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
                            base["sector"] = SECTORS.get(ticker, "Unknown")
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

                # Engine 6: Resistance breakout
                if zones:
                    try:
                        res_brk = await loop.run_in_executor(
                            None, scan_resistance_breakout, ticker, df, zones
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
                                res_brk["sector"] = SECTORS.get(ticker, "Unknown")
                                collected_setups.append(res_brk)
                                res_count += 1
                                _scan_state["engine_stats"]["e6"]["res_breakout"] += 1
                                log.info("  RES_BRK  %-6s  level=%.2f  vol=×%.1f",
                                         ticker, res_brk.get("resistance_level", 0),
                                         res_brk.get("volume_ratio", 0))
                    except Exception as res_exc:
                        log.warning("ResBreakout check failed for %s: %s", ticker, res_exc)

                # Engine 7: Options Catalyst (not gated by market regime)
                try:
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

        # Gather all ticker tasks; semaphore handles concurrency internally
        await asyncio.gather(*[_process(t, i) for i, t in enumerate(tickers)])

        process_time = time.time() - process_start_time
        log.info(
            "Per-ticker processing completed  [%.1fs]  vcp=%d  pb=%d  base=%d  res=%d  opt=%d  total_setups=%d",
            process_time,
            vcp_count,
            pb_count,
            base_count,
            res_count,
            opt_count,
            len(collected_setups),
        )

        # ── Sector Clustering — inject hot_sector flag before saving ─────────
        try:
            _inject_hot_sector(collected_setups)
        except Exception as exc:
            log.warning("Sector clustering failed: %s", exc)

        # ── Batch Save All Setups (5-10x faster than individual saves) ──────
        if collected_setups and not dry_run:
            db_save_start = time.time()
            await batch_save_setups(DB_PATH, scan_ts, collected_setups)
            db_save_time = time.time() - db_save_start
            log.info("Batch saved %d setups to database  [%.1fs]", len(collected_setups), db_save_time)

        if dry_run:
            _scan_state["dry_run_setups"] = {
                "vcp":               [s for s in collected_setups if s.get("setup_type") == "VCP"],
                "pullback":          [s for s in collected_setups if s.get("setup_type") == "PULLBACK"],
                "base":              [s for s in collected_setups if s.get("setup_type") == "BASE"],
                "res_breakout":      [s for s in collected_setups if s.get("setup_type") == "RES_BREAKOUT"],
                "watchlist":         [s for s in collected_setups if s.get("setup_type") == "WATCHLIST"],
                "options_catalyst":  [s for s in collected_setups if s.get("setup_type") == "OPTIONS_CATALYST"],
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

        _scan_state["engine_stats"]["total_tickers"] = len(tickers)
        _scan_state["engine_stats"]["total_duration_s"] = round(time.time() - scan_start_time, 1)
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

        total_scan_time = time.time() - scan_start_time
        log.info(
            "✔ Scan complete  VCP=%d  Pullbacks=%d  Base=%d  ResBreakout=%d  Options=%d  Processed=%d/%d  Total=%.1fs  (Regime=%.1fs, SPY=%.1fs, Process=%.1fs)",
            vcp_count,
            pb_count,
            base_count,
            res_count,
            opt_count,
            processed_tickers,
            len(tickers),
            total_scan_time,
            regime_time,
            spy_fetch_time,
            process_time,
        )

    except Exception as exc:
        log.error("Scan worker crashed: %s", exc)
        _scan_state["last_error"] = str(exc)
    finally:
        _scan_state["in_progress"] = False


# ────────────────────────────────────────────────────────────────────────────
# Scan helpers
# ────────────────────────────────────────────────────────────────────────────

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


# ────────────────────────────────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/api/run-scan")
async def trigger_scan(
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Bypass bearish halt gate"),
    dry_run: bool = Query(False, description="Run pipeline without saving to DB"),
):
    """
    Trigger a full market scan.  Returns immediately; scan runs in background.
    Poll /api/scan-status to track progress.
    """
    if _scan_state["in_progress"]:
        return {
            "status": "already_running",
            "progress": _scan_state["progress"],
            "total": _scan_state["total"],
        }

    scan_ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    background_tasks.add_task(_run_scan, scan_ts, ACTIVE_UNIVERSE, force, dry_run)

    return {
        "status": "started",
        "scan_timestamp": scan_ts,
        "tickers": len(ACTIVE_UNIVERSE),
        "forced": force,
        "dry_run": dry_run,
        "message": f"Scanning {len(ACTIVE_UNIVERSE)} tickers in background",
    }


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
    return {"setups": setups, "count": len(setups)}


@app.get("/api/setups/vcp")
async def get_vcp_setups():
    """VCP breakout setups from the latest scan."""
    setups = await get_latest_setups(DB_PATH, setup_type="VCP")
    return {"setups": setups, "count": len(setups)}


@app.get("/api/setups/pullback")
async def get_pullback_setups():
    """Tactical pullback setups from the latest scan."""
    setups = await get_latest_setups(DB_PATH, setup_type="PULLBACK")
    return {"setups": setups, "count": len(setups)}


@app.get("/api/setups/base")
async def get_base_setups():
    """Cup & Handle and Flat Base setups from the latest scan."""
    setups = await get_latest_setups(DB_PATH, setup_type="BASE")
    setups.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    return {"setups": setups, "count": len(setups)}


@app.get("/api/setups/res-breakout")
async def get_res_breakout_setups():
    """Resistance breakout setups (fresh break above KDE zone, last 3 days)."""
    setups = await get_latest_setups(DB_PATH, setup_type="RES_BREAKOUT")
    setups.sort(key=lambda x: x.get("days_since_breakout", 99))
    return {"setups": setups, "count": len(setups)}


@app.get("/api/setups/options-catalyst")
async def get_options_catalyst_setups():
    """Options Catalyst setups — unusual near-term call activity (Engine 7)."""
    setups = await get_latest_setups(DB_PATH, setup_type="OPTIONS_CATALYST")
    setups.sort(key=lambda x: x.get("options_score", 0), reverse=True)
    return {"setups": setups, "count": len(setups)}


@app.get("/api/watchlist")
async def get_watchlist():
    """Near-breakout tickers from the latest scan (within 1.5% of KDE/TDL level)."""
    items = await get_latest_setups(DB_PATH, setup_type="WATCHLIST")
    # Sort by distance_pct ascending (closest first)
    items.sort(key=lambda x: x.get("distance_pct", 99))
    return {"items": items, "count": len(items)}


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

    # Engine 2 — VCP
    e2 = await loop.run_in_executor(
        None, _run_engine, scan_vcp,
        sym, df, zones, 0.0, rs_ratio, rs_52w_high, rs_blue_dot, rs_score
    )
    # Engine 3 — Pullback (strict then relaxed)
    e3 = await loop.run_in_executor(None, _run_engine, scan_pullback, sym, df, zones, tl)
    e3_relaxed = False
    if e3 is None:
        e3 = await loop.run_in_executor(None, _run_engine, scan_relaxed_pullback, sym, df, zones, tl)
        if e3 is not None:
            e3_relaxed = True
    # Engine 5 — Base pattern
    e5 = await loop.run_in_executor(
        None, _run_engine, scan_base_pattern,
        sym, df, 0.0, rs_ratio, rs_52w_high, rs_blue_dot, rs_score
    )
    # Engine 6 — Resistance breakout
    e6 = await loop.run_in_executor(
        None, _run_engine, scan_resistance_breakout, sym, df, zones
    ) if zones else None

    def _eng(result, extra_keys=()):
        """Build a per-engine debug block.

        Keys:
          triggered  – bool: whether the engine fired
          result     – string setup_type/base_type or None when skipped
          rejection  – always None (engines don't surface rejection strings)
          + any extra_keys extracted from the result dict
        """
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

    # Engine 2 block: derive path (A=DRY, B=BRK) from is_breakout; normalise vol_surge
    e2_out = _eng(e2, ("is_breakout", "is_vol_surge", "is_rs_lead"))
    if e2 is not None:
        e2_out["path"]      = "B" if e2.get("is_breakout") else "A"
        e2_out["vol_surge"] = e2.get("is_vol_surge", False)
        e2_out.pop("is_vol_surge", None)  # remove raw key; exposed as vol_surge

    # Engine 3 block: flag relaxed variant
    e3_out = _eng(e3, ())
    if e3 is not None and e3_relaxed:
        e3_out["is_relaxed"] = True

    # Engine 5 block: use base_type as the result value (more specific than "BASE")
    e5_out = _eng(e5, ("base_type", "quality_score"))
    if e5 is not None and e5.get("base_type"):
        e5_out["result"] = e5["base_type"]

    # Engine 6 block
    e6_out = _eng(e6, ("days_since_breakout", "volume_ratio"))

    return {
        "ticker": sym,
        "regime": {
            "is_bullish": regime_row.get("is_bullish"),
            "spy_close":  regime_row.get("spy_close"),
            "spy_20ema":  regime_row.get("spy_20ema"),
        },
        "rs": {
            "ratio":    rs_ratio,
            "blue_dot": rs_blue_dot,
            "rs_score": rs_score,
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

    return {
        "ticker": sym,
        "candles": candles,
        "ema8": _series(df.index, ema8),
        "ema20": _series(df.index, ema20),
        "sma50": _series(df.index, sma50),
        "sma200": _series(df.index, sma200),
        "cci": _series(df.index, cci20, dec=1),
        "sr_zones": zones,
        "trendline": trendline,
        "base_setup": base_setup,
        "ticker_info": ticker_info,
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

        # Trailing stop: rises with EMA20 when in profit; stays at original SL otherwise
        trailing_stop = max(float(trade["stop_loss"]), l20) if lc > trade["entry_price"] else float(trade["stop_loss"])
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


@app.delete("/api/trades/{trade_id}", status_code=200)
async def delete_trade(trade_id: int):
    """Close (soft-delete) an active trade by id."""
    ok = await close_trade(DB_PATH, trade_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found or already closed")
    return {"id": trade_id, "status": "closed"}
