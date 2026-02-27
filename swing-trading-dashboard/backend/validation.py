"""
Centralized data validation module.
Provides consistent validation for ticker data, dataframes, and setup results.
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from constants import (
    MIN_CANDLES_FOR_ANALYSIS,
    MIN_CANDLES_FOR_RS,
)

log = logging.getLogger(__name__)


def validate_ticker_dataframe(
    df: Optional[pd.DataFrame],
    ticker: str,
    min_rows: int = MIN_CANDLES_FOR_ANALYSIS,
) -> bool:
    """
    Validate that a ticker's dataframe has sufficient clean data.

    Args:
        df: DataFrame from yfinance
        ticker: Ticker symbol for logging
        min_rows: Minimum number of rows required

    Returns:
        True if dataframe is valid, False otherwise
    """
    if df is None:
        return False

    if len(df) < min_rows:
        log.debug("Ticker %s: insufficient rows (%d < %d)", ticker, len(df), min_rows)
        return False

    # Check for required columns
    close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    if close_col not in df.columns:
        log.debug("Ticker %s: missing %s column", ticker, close_col)
        return False

    # Check for all-NaN close values
    if df[close_col].isna().all():
        log.debug("Ticker %s: all NaN close values", ticker)
        return False

    return True


def validate_rs_dataframe(
    df: Optional[pd.DataFrame],
    ticker: str,
    min_rows: int = MIN_CANDLES_FOR_RS,
) -> bool:
    """
    Validate dataframe for RS Line calculation (stricter than standard validation).

    Args:
        df: DataFrame from yfinance
        ticker: Ticker symbol for logging
        min_rows: Minimum rows for RS (default 252 = 1 year)

    Returns:
        True if dataframe sufficient for RS calculation
    """
    return validate_ticker_dataframe(df, ticker, min_rows=min_rows)


def sanitize_numeric_value(
    value: Any,
    field_name: str = "value",
    default: float = 0.0,
    allow_negative: bool = True,
    max_value: Optional[float] = None,
) -> float:
    """
    Safely convert a value to float with validation.

    Args:
        value: Value to sanitize (could be numpy scalar, Series, or float)
        field_name: Name for logging purposes
        default: Default value if conversion fails
        allow_negative: Whether negative values are allowed
        max_value: Maximum allowed value (optional cap)

    Returns:
        Sanitized float value
    """
    try:
        # Handle numpy scalars and pandas Series
        if hasattr(value, "item"):
            result = float(value.item())
        else:
            result = float(value)

        # Validate range
        if not allow_negative and result < 0:
            log.warning("%s: negative value not allowed (%.2f), using default", field_name, result)
            return default

        if max_value is not None and result > max_value:
            log.warning("%s: exceeds maximum (%.2f > %.2f), capping", field_name, result, max_value)
            return max_value

        return result

    except (ValueError, TypeError, AttributeError) as exc:
        log.warning("%s: conversion failed (%s), using default", field_name, exc)
        return default


def validate_setup_result(setup: Dict[str, Any], ticker: str) -> bool:
    """
    Validate a setup dictionary has all required fields with valid data.

    Args:
        setup: Setup dictionary from scanner
        ticker: Ticker symbol for context

    Returns:
        True if setup is valid, False otherwise
    """
    if not isinstance(setup, dict):
        log.warning("Ticker %s: setup is not a dict", ticker)
        return False

    required_fields = ["ticker", "setup_type", "entry", "stop_loss", "take_profit", "rr", "setup_date"]

    for field in required_fields:
        if field not in setup:
            log.warning("Ticker %s: setup missing required field '%s'", ticker, field)
            return False

    # Validate numeric fields are sensible
    try:
        entry = float(setup["entry"])
        stop_loss = float(setup["stop_loss"])
        take_profit = float(setup["take_profit"])
        rr = float(setup["rr"])

        if entry <= 0:
            log.warning("Ticker %s: invalid entry price (%.2f)", ticker, entry)
            return False

        if stop_loss <= 0:
            log.warning("Ticker %s: invalid stop loss (%.2f)", ticker, stop_loss)
            return False

        if take_profit <= 0:
            log.warning("Ticker %s: invalid take profit (%.2f)", ticker, take_profit)
            return False

        if rr < 0:
            log.warning("Ticker %s: invalid R:R ratio (%.2f)", ticker, rr)
            return False

        return True

    except (ValueError, TypeError) as exc:
        log.warning("Ticker %s: numeric validation failed (%s)", ticker, exc)
        return False


def is_price_vital(
    df: pd.DataFrame,
    lookback: int = 10,
    min_range_pct: float = 0.02,
) -> bool:
    """
    Price Action Vitality check — filter zombie / buyout-flatline stocks.

    A stock is considered non-vital (return False) if the absolute range
    (High.max − Low.min) over the last `lookback` trading days is less than
    `min_range_pct` of the period's high.  A buyout target that gaps up and
    then trades in a $0.10 band for weeks will fail this check.

    Returns True if the stock is actively traded; True also when there is
    insufficient data to make a decision (do not filter on uncertainty).
    """
    if df is None or len(df) < lookback:
        return True   # not enough data — stay neutral

    if "High" not in df.columns or "Low" not in df.columns:
        return True   # missing columns — stay neutral

    recent_high = float(df["High"].iloc[-lookback:].max())
    recent_low  = float(df["Low"].iloc[-lookback:].min())

    if recent_high <= 0:
        return True

    range_pct = (recent_high - recent_low) / recent_high
    return range_pct >= min_range_pct


def validate_regime_dict(regime: Dict[str, Any]) -> bool:
    """
    Validate market regime dictionary has required fields.

    Args:
        regime: Regime dict from check_market_regime()

    Returns:
        True if regime is valid
    """
    required = ["is_bullish", "regime", "spy_close", "spy_20ema"]

    for field in required:
        if field not in regime:
            log.warning("Market regime: missing required field '%s'", field)
            return False

    try:
        float(regime["spy_close"])
        float(regime["spy_20ema"])
        bool(regime["is_bullish"])
        return True
    except (ValueError, TypeError):
        log.warning("Market regime: invalid data types")
        return False


def validate_sr_zones(zones: List[Dict[str, Any]], ticker: str) -> bool:
    """
    Validate S/R zones list has valid structure.

    Args:
        zones: List of zone dicts from calculate_sr_zones()
        ticker: Ticker symbol for context

    Returns:
        True if zones are valid
    """
    if not isinstance(zones, list):
        log.warning("Ticker %s: zones is not a list", ticker)
        return False

    for i, zone in enumerate(zones):
        if not isinstance(zone, dict):
            log.warning("Ticker %s: zone %d is not a dict", ticker, i)
            return False

        required = ["level", "upper", "lower", "type"]
        for field in required:
            if field not in zone:
                log.warning("Ticker %s: zone %d missing field '%s'", ticker, i, field)
                return False

        try:
            float(zone["level"])
            float(zone["upper"])
            float(zone["lower"])
            str(zone["type"])
        except (ValueError, TypeError):
            log.warning("Ticker %s: zone %d has invalid data types", ticker, i)
            return False

    return True
