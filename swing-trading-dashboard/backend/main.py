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
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()  # load .env file (EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO, etc.)

from apscheduler.schedulers.background import BackgroundScheduler

from indicators import ema as _ema, sma as _sma, cci as _cci, atr as _atr
from indicators.indicator_engine import compute_indicators, TickerIndicators
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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
    get_closed_trades,
)
from engines.engine0 import check_market_regime
from engines.engine1 import calculate_sr_zones
from engines.engine2 import scan_vcp, detect_trendline, scan_near_breakout
from engines.engine3 import scan_pullback, scan_relaxed_pullback, scan_ema_pullback
from engines.engine4 import calculate_rs_line, detect_rs_blue_dot, get_rs_stats, calculate_rs_score
from engines.engine5 import scan_base_pattern
from engines.engine6 import scan_resistance_breakout
from engines.engine7 import scan_options_catalyst
from tickers import SCAN_UNIVERSE
from validation import is_price_vital
from universe_builder import build_universe, load_universe, save_universe, UNIVERSE_FILE
from email_digest import send_digest

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

# In-memory price cache: {ticker: (timestamp, price)}
_price_cache: dict = {}
PRICE_CACHE_TTL = 60  # seconds

# In-memory earnings blackout cache: {ticker: {"blackout": bool, "cached_at": ISO str}}
_earnings_cache: dict = {}
_earnings_cache_lock = threading.Lock()

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
        "e3": {"pullback": 0, "relaxed": 0, "ema": 0},
        "e5": {"cup_handle": 0, "flat_base": 0},
        "e6": {"res_breakout": 0},
        "e7": {"options_catalyst": 0},
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
        },
        "filtered": {
            "liquidity": 0,
            "earnings": 0,
        },
    },
    "dry_run_setups": None,
}
_semaphore: Optional[asyncio.Semaphore] = None
_ticker_cache: dict = {}  # ticker → (timestamp: float, df: Optional[pd.DataFrame])

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

            for d in dates:
                try:
                    if hasattr(d, "to_pydatetime"):
                        d = d.to_pydatetime().replace(tzinfo=None)
                    elif isinstance(d, str):
                        d = datetime.fromisoformat(d)
                    days_until = (d - now).days
                    if -1 <= days_until <= EARNINGS_BLACKOUT_DAYS:
                        blackout = True
                        break
                except Exception:
                    pass
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
                }
            log.info(
                "[scheduler] Digest cache built: vcp=%d  dry=%d  res=%d  pb=%d  opt=%d",
                len(vcp_setups), len(watchlist), len(res_setups), len(pb_setups), len(opt_setups),
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
    _semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    await init_db(DB_PATH)
    log.info("SQLite DB initialised at %s", DB_PATH)

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
    _scheduler.start()
    log.info(
        "[scheduler] Started — scan at 07:30 ET, email at 08:00 ET"
    )

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
            "e2": {"vcp": 0, "watchlist": 0},
            "e3": {"pullback": 0, "relaxed": 0, "ema": 0},
            "e5": {"cup_handle": 0, "flat_base": 0},
            "e6": {"res_breakout": 0},
            "e7": {"options_catalyst": 0},
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
            },
            "filtered": {
                "liquidity": 0,
                "earnings": 0,
            },
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
            universe_dict = await loop.run_in_executor(
                None,
                lambda: build_universe(
                    min_atr_pct=MIN_ATR_PCT,
                ),
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

        loop = asyncio.get_event_loop()

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

        # ── Bulk pre-fetch all ticker data (single HTTP request per batch) ──
        # yf.download(200 tickers) is ~10× faster than 200 individual calls.
        # Results go straight into _ticker_cache so _fetch() calls below hit cache.
        uncached = [
            t for t in tickers
            if t not in _ticker_cache
            or time.time() - _ticker_cache[t][0] >= CACHE_TTL_SUCCESS
        ]
        prefetch_start = time.time()
        if uncached:
            prefetch_batches = [
                uncached[i: i + BULK_DOWNLOAD_BATCH_SIZE]
                for i in range(0, len(uncached), BULK_DOWNLOAD_BATCH_SIZE)
            ]
            _scan_state["prefetching"] = True
            log.info(
                "Pre-fetching %d/%d tickers in %d batches…",
                len(uncached), len(tickers), len(prefetch_batches),
            )
            for b_idx, batch in enumerate(prefetch_batches):
                try:
                    batch_data = await loop.run_in_executor(
                        None, lambda b=batch: _batch_download_sync(b)
                    )
                    for t, df in batch_data.items():
                        _ticker_cache[t] = (time.time(), df)
                    log.info(
                        "Pre-fetch %d/%d: %d/%d tickers OK",
                        b_idx + 1, len(prefetch_batches), len(batch_data), len(batch),
                    )
                except Exception as exc:
                    log.warning("Pre-fetch batch %d failed: %s", b_idx + 1, exc)
            _scan_state["prefetching"] = False
            log.info("Pre-fetch complete — %d tickers in cache", len(_ticker_cache))
        else:
            log.info("Pre-fetch skipped — all %d tickers already cached", len(tickers))
        prefetch_time = time.time() - prefetch_start
        _scan_state["engine_stats"]["timing"]["prefetch_s"] = round(prefetch_time, 2)
        log.info("Bulk prefetch phase  [%.1fs]", prefetch_time)

        # ── Compute universe breadth from prefetch cache ──────────────────
        breadth_pct, hl_ratio = compute_universe_breadth(_ticker_cache, tickers)
        log.info(
            "Breadth: %.1f%% above SMA50  H/L ratio: %.2f",
            breadth_pct * 100, hl_ratio,
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

        if not regime["is_bullish"] and not force:
            log.info(
                "Regime DEFENSIVE (score=%d < %d) — Engines 2 & 3 disabled",
                regime["regime_score"], REGIME_SELECTIVE_THRESHOLD,
            )
            _scan_state["engine_stats"]["total_tickers"] = 0
            _scan_state["engine_stats"]["total_duration_s"] = round(time.time() - scan_start_time, 1)
            if not dry_run:
                await complete_scan_run(DB_PATH, scan_ts, 0)
            _scan_state["last_completed"] = scan_ts
            return

        if not regime["is_bullish"] and force:
            log.info(
                "Regime DEFENSIVE (score=%d) — force=True, overriding halt gate",
                regime["regime_score"],
            )

        # ── Load earnings cache from disk (Task 1) ────────────────────────────
        global _earnings_cache
        _earnings_cache = _load_earnings_cache()
        log.info("Earnings cache loaded: %d entries", len(_earnings_cache))

        # ── Per-ticker processing ─────────────────────────────────────────
        # Collect setups instead of saving individually for batch optimization
        collected_setups: List[Dict] = []
        dropped_tickers: List[str] = []  # Track tickers that failed all retries
        vcp_count = 0
        pb_count = 0
        base_count = 0
        res_count  = 0
        opt_count  = 0
        liquidity_filtered = 0
        earnings_filtered  = 0
        process_start_time = time.time()

        async def _process(ticker: str, idx: int) -> None:
            nonlocal vcp_count, pb_count, base_count, res_count, opt_count, dropped_tickers, liquidity_filtered, earnings_filtered

            try:
                # ── Data Integrity Check ────────────────────────────────────
                # Skip tickers with empty/delisted data immediately
                df = await _fetch(ticker, semaphore=semaphore)
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

                # ── Centralized Indicator Engine (Task 6) ────────────────────────
                ind: Optional[TickerIndicators] = await loop.run_in_executor(
                    None, compute_indicators, df, spy_df_full
                )
                if ind is None:
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

                # ── Earnings Blackout (Task 1) ────────────────────────────────────
                blackout = await loop.run_in_executor(
                    None, _check_earnings_blackout_sync, ticker
                )
                if blackout:
                    earnings_filtered += 1
                    _scan_state["engine_stats"]["filtered"]["earnings"] += 1
                    log.debug("Skipped %s: earnings within %d days", ticker, EARNINGS_BLACKOUT_DAYS)
                    return

                # ── Use pre-computed RS values from indicator engine ───────────────
                rs_ratio    = ind.rs_ratio
                rs_52w_high = ind.rs_52w_high
                rs_blue_dot = ind.rs_blue_dot
                rs_score    = ind.rs_score

                # ── S/R Zone calculation (uses full weekly resample, stays separate) ──
                zones: List[Dict] = []
                try:
                    zones = await loop.run_in_executor(None, calculate_sr_zones, ticker, df)
                except Exception as exc:
                    log.warning("S/R zone calculation failed for %s: %s", ticker, exc)

                if zones:
                    if not dry_run:
                        await save_sr_zones(DB_PATH, scan_ts, ticker, zones)
                    # engine_stats increments are safe: asyncio coroutine — no await
                    # between read and write, so no interleaving with other tickers.
                    _scan_state["engine_stats"]["e1"]["zones_saved"] += 1

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
                pb = await loop.run_in_executor(None, scan_pullback, ticker, df, zones, tl, rs_score)
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
                            None, scan_relaxed_pullback, ticker, df, zones, tl, rs_score
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
                        else:
                            # Pure EMA path: no KDE zone required — clean uptrend + EMA20 rejection
                            try:
                                pb_ema = await loop.run_in_executor(
                                    None, scan_ema_pullback, ticker, df, zones, tl, rs_score
                                )
                                if pb_ema:
                                    try:
                                        pb_ema["entry"] = float(pb_ema.get("entry", 0.0))
                                        pb_ema["stop_loss"] = float(pb_ema.get("stop_loss", 0.0))
                                        pb_ema["take_profit"] = float(pb_ema.get("take_profit", 0.0))
                                        pb_ema["rr"] = float(pb_ema.get("rr", 2.0))
                                    except (ValueError, TypeError) as conv_err:
                                        log.warning("EMA pullback conversion failed for %s: %s", ticker, conv_err)
                                        return

                                    pb_ema["sector"] = SECTORS.get(ticker, "Unknown")
                                    collected_setups.append(pb_ema)
                                    pb_count += 1
                                    _scan_state["engine_stats"]["e3"]["ema"] += 1
                                    log.info("  PULLBACK %-6s  entry=%.2f (ema-path)", ticker, pb_ema["entry"])
                            except Exception as pb_ema_exc:
                                log.warning("EMA pullback check failed for %s: %s", ticker, pb_ema_exc)
                    except Exception as pb_rel_exc:
                        log.warning("Relaxed pullback check failed for %s: %s", ticker, pb_rel_exc)

                # Engine 5: Base pattern (Cup & Handle / Flat Base)
                try:
                    base = await loop.run_in_executor(
                        None, scan_base_pattern, ticker, df,
                        spy_3m_return, rs_ratio, rs_52w_high, rs_blue_dot, rs_score, zones
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
        _scan_state["engine_stats"]["timing"]["process_s"] = round(process_time, 2)
        log.info(
            "Per-ticker processing completed  [%.1fs]  vcp=%d  pb=%d  base=%d  res=%d  opt=%d  "
            "total_setups=%d  filtered(liq=%d  earn=%d)",
            process_time,
            vcp_count, pb_count, base_count, res_count, opt_count,
            len(collected_setups),
            liquidity_filtered, earnings_filtered,
        )

        # ── Sector Clustering — inject hot_sector flag before saving ─────────
        try:
            _inject_hot_sector(collected_setups)
        except Exception as exc:
            log.warning("Sector clustering failed: %s", exc)

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
            "✔ Scan complete  VCP=%d  Pullbacks=%d  Base=%d  ResBreakout=%d  Options=%d  "
            "Processed=%d/%d  filtered(liq=%d  earn=%d)  "
            "Total=%.1fs  [regime=%.1fs  spy=%.1fs  prefetch=%.1fs  process=%.1fs  db=%.1fs]",
            vcp_count, pb_count, base_count, res_count, opt_count,
            processed_tickers, len(tickers),
            liquidity_filtered, earnings_filtered,
            total_scan_elapsed,
            regime_time, spy_fetch_time, prefetch_time, process_time, db_save_time,
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
            if not pd.isna(sma50_val) and lc > float(sma50_val):
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

    # Fetch uncached tickers in one batch
    if uncached:
        try:
            loop = asyncio.get_event_loop()

            def _batch_download(tks=uncached):
                return yf.download(
                    tks,
                    period="1d",
                    interval="1m",
                    progress=False,
                    group_by="ticker" if len(tks) > 1 else None,
                )

            df = await loop.run_in_executor(None, _batch_download)

            if df is not None and not df.empty:
                fetch_ts = time.time()
                if len(uncached) == 1:
                    # Single ticker: df has simple column index
                    t = uncached[0]
                    try:
                        price = float(df["Close"].dropna().iloc[-1])
                        _price_cache[t] = (fetch_ts, price)
                        result[t] = price
                    except Exception:
                        pass
                else:
                    # Multiple tickers: df is MultiIndex (ticker, field)
                    for t in uncached:
                        try:
                            price = float(df["Close"][t].dropna().iloc[-1])
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
    # Engine 3 — Pullback (strict then relaxed then pure EMA path)
    e3 = await loop.run_in_executor(None, _run_engine, scan_pullback, sym, df, zones, tl, rs_score)
    e3_relaxed = False
    if e3 is None:
        e3 = await loop.run_in_executor(None, _run_engine, scan_relaxed_pullback, sym, df, zones, tl, rs_score)
        if e3 is not None:
            e3_relaxed = True
    if e3 is None:
        e3 = await loop.run_in_executor(None, _run_engine, scan_ema_pullback, sym, df, zones, tl, rs_score)
    # Engine 5 — Base pattern
    e5 = await loop.run_in_executor(
        None, _run_engine, scan_base_pattern,
        sym, df, 0.0, rs_ratio, rs_52w_high, rs_blue_dot, rs_score, zones
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
    if e3 is not None and e3.get("is_ema_path"):
        e3_out["is_ema_path"] = True

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
