"""
universe_builder.py — SEC fetch + pattern filter + save/load

Builds a tradeable universe by fetching tickers from SEC,
filtering out warrants/preferred/ETFs, and persisting results.
"""

import argparse
import json
import logging
import os
import re
import ssl
import sys
import time
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

from constants import (
    UNIVERSE_MIN_PRICE as DEFAULT_MIN_PRICE,
    UNIVERSE_MIN_AVG_VOLUME as DEFAULT_MIN_AVG_VOLUME,
    UNIVERSE_MIN_DOLLAR_VOL as _DEFAULT_MIN_DOLLAR_VOL,
    RS_RANK_CACHE_FILE,
    UNIVERSE_RS_FLOOR,
)

UNIVERSE_FILE = "active_universe.json"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_USER_AGENT = "SwingTradingDashboard admin@example.com"
BATCH_SIZE = 250        # larger batches → fewer sleeps → ~2min vs ~8min for 5000 tickers
BATCH_DELAY = 1.0       # reduced from 2.0s
SECTOR_BATCH_SIZE = 50
SECTOR_BATCH_DELAY = 3.0

KNOWN_ETFS = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "IVV", "VEA", "VWO", "EFA",
    "AGG", "BND", "TLT", "GLD", "SLV", "USO", "XLF", "XLK", "XLE", "XLV",
    "XLY", "XLP", "XLI", "XLB", "XLRE", "XLU", "XLC", "ARKK", "ARKW",
    "ARKF", "ARKG", "ARKQ", "SQQQ", "TQQQ", "SPXU", "SOXL", "SOXS",
    "UVXY", "SVXY", "VXX", "VIXY", "HYG", "LQD", "IEMG", "EEM",
})

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SEC fetch helpers
# ---------------------------------------------------------------------------


def _fetch_sec_json() -> dict:
    """Fetch company tickers JSON from the SEC EDGAR API.

    Returns a dict with ``fields`` and ``data`` arrays as provided by the SEC.
    Uses certifi CA bundle when available to fix macOS Python SSL issues.
    """
    req = urllib.request.Request(
        SEC_TICKERS_URL,
        headers={"User-Agent": SEC_USER_AGENT},
    )
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_sec_tickers() -> pd.DataFrame:
    """Return a DataFrame of NYSE/Nasdaq tickers from the SEC.

    Columns: ``[cik, name, ticker, exchange]``.
    On any failure an empty DataFrame with those columns is returned.
    """
    columns = ["cik", "name", "ticker", "exchange"]
    try:
        raw = _fetch_sec_json()
        df = pd.DataFrame(raw["data"], columns=raw["fields"])
        # Rename columns to our standard names if needed
        # SEC JSON fields are: [cik, name, ticker, exchange]
        df.columns = columns
        df = df[df["exchange"].isin({"NYSE", "Nasdaq"})]
        df = df.drop_duplicates(subset="ticker", keep="first")
        df = df.reset_index(drop=True)
        return df
    except Exception:
        logger.exception("Failed to fetch SEC tickers")
        return pd.DataFrame(columns=columns)


# ---------------------------------------------------------------------------
# Ticker pattern filtering
# ---------------------------------------------------------------------------


def filter_ticker_patterns(tickers: List[str]) -> List[str]:
    """Filter out warrants, preferred shares, rights/units, ETFs, and long tickers.

    Also normalises dots to dashes (e.g. ``BRK.B`` becomes ``BRK-B``).
    """
    # Regex for preferred shares: contains -P optionally followed by one letter
    preferred_re = re.compile(r"-P[A-Z]?$")
    # Regex for rights/units: ends with -R, -RT, or -U
    rights_units_re = re.compile(r"-(R|RT|U)$")

    result: List[str] = []
    for raw_ticker in tickers:
        # Normalise dots to dashes
        ticker = raw_ticker.replace(".", "-")

        # Exclude known ETFs
        if ticker in KNOWN_ETFS:
            continue

        # Exclude warrants: multi-char tickers ending with W or WS
        if len(ticker) > 1 and (ticker.endswith("WS") or ticker.endswith("W")):
            # But check WS first so that e.g. "FOOWS" is caught by WS branch
            # and "FOOW" is caught by W branch.  Single-letter "W" is preserved.
            continue

        # Exclude preferred shares
        if preferred_re.search(ticker):
            continue

        # Exclude rights / units
        if rights_units_re.search(ticker):
            continue

        # Exclude long tickers: base length (without dashes) > 5
        base = ticker.replace("-", "")
        if len(base) > 5:
            continue

        result.append(ticker)
    return result


# ---------------------------------------------------------------------------
# Universe persistence
# ---------------------------------------------------------------------------


def save_universe(universe: dict, filepath: str = UNIVERSE_FILE) -> None:
    """Write *universe* dict to *filepath* as pretty-printed JSON."""
    with open(filepath, "w", encoding="utf-8") as fh:
        json.dump(universe, fh, indent=2)


def load_universe(
    filepath: str = UNIVERSE_FILE,
) -> Optional[Tuple[List[str], Dict[str, str]]]:
    """Load a previously saved universe file.

    Returns ``(tickers, sectors)`` on success, or ``None`` when the file is
    missing or contains invalid JSON.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return (data["tickers"], data["sectors"])
    except FileNotFoundError:
        logger.warning("Universe file not found: %s", filepath)
        return None
    except json.JSONDecodeError:
        logger.warning("Corrupt universe file: %s", filepath)
        return None


# ---------------------------------------------------------------------------
# Stub functions (to be implemented in later tasks)
# ---------------------------------------------------------------------------


def filter_price_volume(
    tickers: List[str],
    min_price: float = DEFAULT_MIN_PRICE,
    min_avg_volume: int = DEFAULT_MIN_AVG_VOLUME,
    min_atr_pct: float = 0.0,
    min_dollar_volume: float = 0.0,
) -> List[str]:
    """Filter tickers by minimum price, average daily volume, and optional ATR%.

    Downloads 3 months of daily data from yfinance in batches of
    ``BATCH_SIZE``, then checks each ticker's last close price and
    50-day average volume against the supplied thresholds.

    Returns the subset of *tickers* that pass both filters.
    """
    passed: List[str] = []
    total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(total_batches):
        start = batch_idx * BATCH_SIZE
        batch = tickers[start : start + BATCH_SIZE]
        logger.info(
            "filter_price_volume: batch %d/%d (%d tickers)",
            batch_idx + 1,
            total_batches,
            len(batch),
        )

        try:
            df = yf.download(
                " ".join(batch),
                period="3mo",
                interval="1d",
                auto_adjust=False,
                prepost=False,
                progress=False,
                threads=True,
                group_by="ticker",
            )
        except Exception:
            logger.exception("yf.download failed for batch %d", batch_idx + 1)
            continue

        if df is None or df.empty:
            logger.warning("Empty result for batch %d — skipping", batch_idx + 1)
            if batch_idx < total_batches - 1:
                time.sleep(BATCH_DELAY)
            continue

        for ticker in batch:
            try:
                # --- extract per-ticker sub-DataFrame ---
                if len(batch) == 1:
                    # Single ticker: yfinance may return flat columns or
                    # a MultiIndex with one ticker at level 0.
                    if isinstance(df.columns, pd.MultiIndex):
                        ticker_df = df[ticker].copy()
                    else:
                        ticker_df = df.copy()
                else:
                    # Multiple tickers: group_by="ticker" gives MultiIndex
                    if ticker not in df.columns.get_level_values(0):
                        continue
                    ticker_df = df[ticker].copy()

                # Drop rows that are entirely NaN (non-trading days / missing)
                ticker_df = ticker_df.dropna(how="all")

                if ticker_df.empty or len(ticker_df) < 10:
                    continue

                # --- last close price ---
                if "Adj Close" in ticker_df.columns:
                    last_close = float(ticker_df["Adj Close"].dropna().iloc[-1])
                elif "Close" in ticker_df.columns:
                    last_close = float(ticker_df["Close"].dropna().iloc[-1])
                else:
                    continue

                if last_close < min_price:
                    continue

                # --- 50-day average volume ---
                if "Volume" not in ticker_df.columns:
                    continue
                vol_series = ticker_df["Volume"].dropna()
                avg_volume = float(vol_series.tail(50).mean())

                if avg_volume < min_avg_volume:
                    continue

                # --- dollar volume gate (optional — skipped when min_dollar_volume == 0) ---
                if min_dollar_volume > 0:
                    dollar_volume = last_close * avg_volume
                    if dollar_volume < min_dollar_volume:
                        continue

                # --- ATR% filter (optional — skipped when min_atr_pct == 0) ---
                if min_atr_pct > 0:
                    if "High" not in ticker_df.columns or "Low" not in ticker_df.columns:
                        continue
                    high = ticker_df["High"].dropna()
                    low  = ticker_df["Low"].dropna()
                    close_s = ticker_df["Close"].dropna() if "Close" in ticker_df.columns \
                              else ticker_df["Adj Close"].dropna()
                    prev_close = close_s.shift(1)
                    tr = pd.concat([
                        high - low,
                        (high - prev_close).abs(),
                        (low  - prev_close).abs(),
                    ], axis=1).max(axis=1)
                    atr14 = tr.rolling(14).mean()
                    if atr14.empty or pd.isna(atr14.iloc[-1]):
                        continue
                    atr_pct = float(atr14.iloc[-1]) / last_close * 100.0
                    if atr_pct < min_atr_pct:
                        continue

                passed.append(ticker)

            except Exception:
                logger.exception(
                    "Error processing ticker %s — skipping", ticker
                )

        # Sleep between batches, but not after the last one
        if batch_idx < total_batches - 1:
            time.sleep(BATCH_DELAY)

    logger.info(
        "filter_price_volume: %d / %d tickers passed", len(passed), len(tickers)
    )
    return passed


def build_sector_map(
    tickers: List[str],
    existing_sectors: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Build a mapping of ticker -> GICS sector.

    If *existing_sectors* is ``None``, tries to load ``sectors.json`` from the
    current directory as a base map.  Tickers already present in the map are
    reused; only genuinely new tickers are fetched from yfinance.

    ETFs (``quoteType == "ETF"``) get sector ``"ETF"``; tickers whose sector
    cannot be determined get ``"Unknown"``.
    """
    # Start from existing sectors or try loading sectors.json
    if existing_sectors is None:
        sectors_file = os.path.join(os.path.dirname(__file__), "sectors.json")
        try:
            with open(sectors_file, "r", encoding="utf-8") as fh:
                sector_map: Dict[str, str] = json.load(fh)
            logger.info("Loaded %d existing sectors from %s", len(sector_map), sectors_file)
        except (FileNotFoundError, json.JSONDecodeError):
            sector_map = {}
    else:
        sector_map = dict(existing_sectors)

    # Determine which tickers need fetching
    new_tickers = [t for t in tickers if t not in sector_map]

    if not new_tickers:
        logger.info("All %d tickers already have sectors — nothing to fetch", len(tickers))
        return sector_map

    logger.info(
        "Need to fetch sectors for %d new tickers (reusing %d existing)",
        len(new_tickers),
        len(tickers) - len(new_tickers),
    )

    total_batches = (len(new_tickers) + SECTOR_BATCH_SIZE - 1) // SECTOR_BATCH_SIZE
    for batch_idx in range(total_batches):
        start = batch_idx * SECTOR_BATCH_SIZE
        batch = new_tickers[start : start + SECTOR_BATCH_SIZE]
        logger.info(
            "build_sector_map: batch %d/%d (%d tickers)",
            batch_idx + 1,
            total_batches,
            len(batch),
        )

        for ticker in batch:
            try:
                info = yf.Ticker(ticker).info
                quote_type = info.get("quoteType", "")
                if quote_type == "ETF":
                    sector_map[ticker] = "ETF"
                else:
                    sector = info.get("sector", "")
                    sector_map[ticker] = sector if sector else "Unknown"
            except Exception:
                logger.exception("Failed to fetch sector for %s", ticker)
                sector_map[ticker] = "Unknown"

        # Sleep between batches, but not after the last one
        if batch_idx < total_batches - 1:
            time.sleep(SECTOR_BATCH_DELAY)

    return sector_map


def _apply_rs_prefilter(
    tickers: list,
    rs_cache_file: str,
    rs_floor: float,
    max_age_days: int = 7,
) -> list:
    """
    Exclude tickers with RS rank < rs_floor using the persisted RS cache.
    Returns the full ticker list unchanged if cache is missing or too old.
    """
    try:
        if not os.path.exists(rs_cache_file):
            return tickers
        with open(rs_cache_file, "r", encoding="utf-8") as fh:
            cache = json.load(fh)
        computed_at = datetime.fromisoformat(cache["_meta"]["computed_at"])
        age_days = (datetime.utcnow() - computed_at).total_seconds() / 86400
        if age_days > max_age_days:
            logger.info("RS pre-filter: cache is %.1f days old (> %d) — skipping", age_days, max_age_days)
            return tickers
        original_count = len(tickers)
        kept = [t for t in tickers if cache.get(t, rs_floor) >= rs_floor]
        logger.info(
            "RS pre-filter: %d → %d tickers (removed %d with RS < %.0f)",
            original_count, len(kept), original_count - len(kept), rs_floor,
        )
        return kept
    except Exception as exc:
        logger.warning("RS pre-filter failed (%s) — skipping", exc)
        return tickers


def build_universe(
    min_price: float = DEFAULT_MIN_PRICE,
    min_avg_volume: int = DEFAULT_MIN_AVG_VOLUME,
    min_atr_pct: float = 0.0,
    min_dollar_volume: float = _DEFAULT_MIN_DOLLAR_VOL,
) -> dict:
    """Orchestrate the full universe-building pipeline.

    1. Fetch SEC tickers (NYSE / Nasdaq only).
    2. Apply pattern filters (warrants, preferred, ETFs, etc.).
    3. Apply price & volume filters.
    4. Build sector map and remove any remaining ETFs.
    5. Return the final universe dict with metadata, tickers, and sectors.
    """
    start_time = time.time()

    # Step 1 — fetch SEC tickers
    sec_df = fetch_sec_tickers()
    if sec_df.empty:
        logger.warning("SEC ticker fetch returned empty — aborting build")
        return {
            "metadata": {},
            "tickers": [],
            "sectors": {},
        }

    # Step 2 — pattern filter
    candidates = filter_ticker_patterns(sec_df["ticker"].tolist())

    # Step 3 — price / volume filter
    filtered = filter_price_volume(candidates, min_price, min_avg_volume, min_atr_pct, min_dollar_volume)

    # RS pre-filter (uses cached rank map to exclude laggards early)
    filtered = _apply_rs_prefilter(filtered, RS_RANK_CACHE_FILE, UNIVERSE_RS_FLOOR)

    # Step 4 — sector map
    sectors = build_sector_map(filtered)

    # Step 5 — remove ETFs
    filtered_before_etf_removal = list(filtered)
    etf_tickers = {t for t in filtered if sectors.get(t) == "ETF"}
    etf_count = len(etf_tickers)
    final_tickers = [t for t in filtered if t not in etf_tickers]
    sectors_without_etfs = {t: s for t, s in sectors.items() if t in final_tickers}

    build_time = round(time.time() - start_time, 1)
    logger.info(
        "Universe build complete: %d final tickers in %.1fs",
        len(final_tickers),
        build_time,
    )

    return {
        "metadata": {
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            "ticker_count": len(final_tickers),
            "version": 1,
            "source": "SEC EDGAR + yfinance",
            "build_time_seconds": build_time,
            "filters": {
                "min_price": min_price,
                "min_avg_volume_50d": min_avg_volume,
                "min_atr_pct": min_atr_pct,
                "min_dollar_volume": min_dollar_volume,
                "exchanges": ["NYSE", "Nasdaq"],
            },
            "counts": {
                "sec_raw": len(sec_df),
                "after_pattern_filter": len(candidates),
                "after_price_volume_filter": len(filtered_before_etf_removal),
                "etfs_removed": etf_count,
                "final": len(final_tickers),
            },
        },
        "tickers": sorted(final_tickers),
        "sectors": sectors_without_etfs,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Build active ticker universe")
    parser.add_argument("--min-price", type=float, default=DEFAULT_MIN_PRICE)
    parser.add_argument("--min-volume", type=int, default=DEFAULT_MIN_AVG_VOLUME)
    parser.add_argument("--min-atr-pct", type=float, default=0.0)
    parser.add_argument("--min-dollar-volume", type=float, default=0.0)
    parser.add_argument("--output", type=str, default=UNIVERSE_FILE)
    args = parser.parse_args()

    universe = build_universe(
        min_price=args.min_price,
        min_avg_volume=args.min_volume,
        min_atr_pct=args.min_atr_pct,
        min_dollar_volume=args.min_dollar_volume,
    )
    save_universe(universe, args.output)

    print(f"\nDone. {len(universe['tickers'])} tickers saved to {args.output}")
    print(f"Build time: {universe['metadata'].get('build_time_seconds', '?')}s")
