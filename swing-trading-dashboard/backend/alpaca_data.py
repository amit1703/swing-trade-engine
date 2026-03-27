"""
alpaca_data.py — Alpaca Market Data wrapper that returns DataFrames
in the same format as yfinance auto_adjust=False.

Column contract (matches yfinance output):
    Open, High, Low, Close, Adj Close, Volume, Dividends, Stock Splits
    Index: pd.DatetimeIndex (timezone-naive dates, daily frequency)

Free-tier note: Alpaca free plan provides 15-min delayed data.
That is fine for end-of-day scans and backtesting.

Keys are loaded from the .env file via python-dotenv (already in requirements).
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Dict, List, Optional

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

log = logging.getLogger(__name__)

_API_KEY    = os.getenv("ALPACA_API_KEY", "")
_API_SECRET = os.getenv("ALPACA_API_SECRET", "")
_BASE_URL   = "https://data.alpaca.markets/v2"

# Alpaca free tier: 15-min delayed data feed
_DATA_FEED  = "iex"   # "iex" = free/delayed; "sip" = paid/real-time

_HEADERS = {
    "APCA-API-KEY-ID":     _API_KEY,
    "APCA-API-SECRET-KEY": _API_SECRET,
    "Accept":              "application/json",
}

# ── Columns that must be present in every returned DataFrame ──────────────────
_REQUIRED_COLS = ["Open", "High", "Low", "Close", "Adj Close", "Volume",
                  "Dividends", "Stock Splits"]


def _bars_to_df(bars: list) -> Optional[pd.DataFrame]:
    """Convert a list of Alpaca bar dicts to a yfinance-compatible DataFrame."""
    if not bars:
        return None
    df = pd.DataFrame(bars)
    # Rename Alpaca fields → yfinance column names
    df = df.rename(columns={"t": "Date", "o": "Open", "h": "High",
                             "l": "Low",  "c": "Close", "v": "Volume"})
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None).dt.normalize()
    df = df.set_index("Date").sort_index()
    # Alpaca adjustment=all means Close IS the fully-adjusted close
    df["Adj Close"] = df["Close"]
    # Placeholder columns so downstream code never KeyErrors
    df["Dividends"]    = 0.0
    df["Stock Splits"] = 0.0
    # Drop any Alpaca-only columns (vw, n, etc.)
    keep = [c for c in _REQUIRED_COLS if c in df.columns]
    return df[keep].copy()


def fetch_bars(
    ticker: str,
    start: Optional[date] = None,
    end: Optional[date]   = None,
    period_days: int       = 365,
) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV for a single ticker from Alpaca.

    Parameters
    ----------
    ticker      : ticker symbol
    start       : first date (inclusive); if None, uses today − period_days
    end         : last  date (exclusive);  if None, uses tomorrow
    period_days : fallback window when start is None (default 365 = ~1y)

    Returns yfinance-compatible DataFrame or None on failure.
    """
    if not _API_KEY or not _API_SECRET:
        log.warning("[alpaca_data] API key/secret not set — check .env file")
        return None

    if start is None:
        start = date.today() - timedelta(days=period_days)
    if end is None:
        end = date.today() + timedelta(days=1)

    params = {
        "timeframe":  "1Day",
        "start":      start.isoformat(),
        "end":        end.isoformat(),
        "adjustment": "all",          # fully split + dividend adjusted
        "feed":       _DATA_FEED,
        "limit":      10000,
    }

    all_bars: list = []
    url = f"{_BASE_URL}/stocks/{ticker}/bars"
    try:
        while url:
            resp = requests.get(url, headers=_HEADERS, params=params, timeout=15)
            if resp.status_code == 422:
                # Alpaca returns 422 for unknown symbols — treat as empty
                return None
            resp.raise_for_status()
            data = resp.json()
            all_bars.extend(data.get("bars") or [])
            # Alpaca paginates via next_page_token
            next_token = data.get("next_page_token")
            if next_token:
                params = {"page_token": next_token, "limit": 10000,
                          "feed": _DATA_FEED}
                url = f"{_BASE_URL}/stocks/{ticker}/bars"
            else:
                url = None
    except requests.RequestException as exc:
        log.debug("[alpaca_data] fetch_bars(%s) failed: %s", ticker, exc)
        return None

    return _bars_to_df(all_bars)


def fetch_bars_batch(
    tickers: List[str],
    period_days: int = 365,
) -> Dict[str, pd.DataFrame]:
    """
    Fetch daily OHLCV for multiple tickers in one Alpaca request.
    Returns dict {ticker: DataFrame}. Tickers with no data are omitted.

    Alpaca's multi-symbol endpoint accepts up to ~1000 symbols per request.
    We batch in groups of 100 to stay well under limits.
    """
    if not tickers or not _API_KEY or not _API_SECRET:
        return {}

    start = (date.today() - timedelta(days=period_days)).isoformat()
    end   = (date.today() + timedelta(days=1)).isoformat()
    result: Dict[str, pd.DataFrame] = {}

    BATCH = 100
    for i in range(0, len(tickers), BATCH):
        chunk = tickers[i: i + BATCH]
        bars_by_ticker: Dict[str, list] = {t: [] for t in chunk}

        params: dict = {
            "symbols":    ",".join(chunk),
            "timeframe":  "1Day",
            "start":      start,
            "end":        end,
            "adjustment": "all",
            "feed":       _DATA_FEED,
            "limit":      10000,
        }
        url = f"{_BASE_URL}/stocks/bars"
        try:
            while url:
                resp = requests.get(url, headers=_HEADERS, params=params, timeout=30)
                resp.raise_for_status()
                data  = resp.json()
                bars  = data.get("bars") or {}
                for ticker, ticker_bars in bars.items():
                    if ticker in bars_by_ticker:
                        bars_by_ticker[ticker].extend(ticker_bars)
                next_token = data.get("next_page_token")
                if next_token:
                    params = {"page_token": next_token, "limit": 10000,
                              "feed": _DATA_FEED}
                    url = f"{_BASE_URL}/stocks/bars"
                else:
                    url = None
        except requests.RequestException as exc:
            log.warning("[alpaca_data] fetch_bars_batch chunk failed: %s", exc)
            continue

        for ticker, bars in bars_by_ticker.items():
            df = _bars_to_df(bars)
            if df is not None and not df.empty:
                result[ticker] = df

    return result
