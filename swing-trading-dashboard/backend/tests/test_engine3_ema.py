"""Tests for Engine 3 pure EMA pullback path (scan_ema_pullback)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd

from engines.engine3 import scan_ema_pullback


def make_ema_pullback_df(n=80):
    """
    Build a synthetic OHLCV DataFrame that satisfies all scan_ema_pullback
    criteria by default:

    - Clean uptrend: EMA8 > EMA20 > SMA50 (steady upward trend).
    - Four-bar dip ending at bar -2 drives CCI well below -30 (cci_prev < -30).
    - Last candle (bar -1) low is pinned to EMA20 (within 0.5%).
    - Last candle close is at or above EMA20 (pin-bar rejection).
    - CCI today > CCI yesterday (hook from oversold).
    - Volume today < 50-day average volume (dry-up).
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    # Steady uptrend baseline
    close = np.linspace(60.0, 100.0, n)

    # Multi-bar dip: bars -5 to -2 pull back sharply, bar -1 recovers
    # This drives CCI[yesterday] well below -30 while keeping EMA8 > EMA20 > SMA50
    close[-5] = 97.0
    close[-4] = 95.0
    close[-3] = 93.0
    close[-2] = 91.0   # yesterday: deep oversold → CCI << -30
    close[-1] = 96.0   # today: recovery — will be adjusted to touch EMA20

    high   = close + 0.5
    low    = close - 0.5

    # Volume: constant 1 000 000; today well below avg → volume dry
    volume = np.full(n, 1_000_000.0)
    volume[-1] = 600_000.0   # below 50-day avg → passes dry-up gate

    df = pd.DataFrame(
        {"Close": close, "Adj Close": close, "High": high,
         "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )

    # Pin the last candle so that low touches EMA20 and close is just above it.
    # Use pandas ewm to compute EMA20 (mirrors _ema() internal logic).
    ema20_series = df["Adj Close"].ewm(span=20, adjust=False).mean()
    l20 = float(ema20_series.iloc[-1])

    df.at[dates[-1], "Low"]       = round(l20 * 0.999, 4)   # low just below EMA20
    df.at[dates[-1], "High"]      = round(l20 * 1.015, 4)   # high above EMA20
    df.at[dates[-1], "Close"]     = round(l20 * 1.005, 4)   # close above EMA20 ✓
    df.at[dates[-1], "Adj Close"] = df.at[dates[-1], "Close"]

    return df


def test_ema_pullback_passes():
    """Baseline: all criteria met → should return a valid setup dict."""
    df = make_ema_pullback_df()
    result = scan_ema_pullback("TEST", df, sr_zones=[], rs_score=0.0)
    assert result is not None, "Expected a setup but got None"
    assert result["ticker"] == "TEST"
    assert result["setup_type"] == "PULLBACK"
    assert result.get("is_ema_path") is True
    assert result["entry"] > result["stop_loss"], "Entry must be above stop loss"
    assert result["stop_loss"] > 0


def test_ema_pullback_rejects_downtrend():
    """EMA8 < EMA20 — trend filter must reject."""
    n = 80
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    # Downtrend: prices fall steadily → EMA8 < EMA20
    close = np.linspace(100.0, 60.0, n)
    high  = close + 0.5
    low   = close - 0.5
    volume = np.full(n, 1_000_000.0)

    df = pd.DataFrame(
        {"Close": close, "Adj Close": close, "High": high,
         "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )
    result = scan_ema_pullback("TEST", df, sr_zones=[])
    assert result is None, "Downtrend: EMA8 < EMA20 must be rejected"


def test_ema_pullback_rejects_no_ema_touch():
    """Low stays well above EMA20 (no touch) → must return None."""
    df = make_ema_pullback_df()

    # Recompute EMA20 after all adjustments, then push last bar's low far above it
    ema20_series = df["Adj Close"].ewm(span=20, adjust=False).mean()
    l20 = float(ema20_series.iloc[-1])

    last_date = df.index[-1]
    # Low is 3% above EMA20 → violates ll <= l20 * 1.005
    df.at[last_date, "Low"]       = round(l20 * 1.03, 4)
    df.at[last_date, "High"]      = round(l20 * 1.04, 4)
    df.at[last_date, "Close"]     = round(l20 * 1.035, 4)
    df.at[last_date, "Adj Close"] = df.at[last_date, "Close"]

    result = scan_ema_pullback("TEST", df, sr_zones=[])
    assert result is None, "Low well above EMA20: no touch, must be rejected"


def test_ema_pullback_rejects_no_cci_hook():
    """CCI is not hooking from oversold → must return None."""
    n = 80
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    # Steady uptrend with no dip → CCI stays near +100 (no hook from oversold)
    close = np.linspace(60.0, 100.0, n)
    # Final two bars are flat/gently rising → CCI prev will NOT be < -30
    close[-2] = 99.5
    close[-1] = 100.0

    high  = close + 0.5
    low   = close - 0.5
    volume = np.full(n, 1_000_000.0)
    volume[-1] = 600_000.0

    df = pd.DataFrame(
        {"Close": close, "Adj Close": close, "High": high,
         "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )

    # Pin last bar's low to touch EMA20 and close above it
    ema20_series = df["Adj Close"].ewm(span=20, adjust=False).mean()
    l20 = float(ema20_series.iloc[-1])
    df.at[dates[-1], "Low"]       = round(l20 * 0.999, 4)
    df.at[dates[-1], "High"]      = round(l20 * 1.015, 4)
    df.at[dates[-1], "Close"]     = round(l20 * 1.005, 4)
    df.at[dates[-1], "Adj Close"] = df.at[dates[-1], "Close"]

    result = scan_ema_pullback("TEST", df, sr_zones=[])
    # CCI[yesterday] should be strongly positive (or near 0), not < -30
    assert result is None, "CCI not hooking from oversold: must be rejected"


def test_ema_pullback_rejects_high_volume():
    """Volume today >= avg_vol_50d → volume-dry gate must reject."""
    df = make_ema_pullback_df()

    # Override today's volume to 1.5× the 50-day avg (avg = 1 000 000)
    last_date = df.index[-1]
    df.at[last_date, "Volume"] = 1_500_000.0

    result = scan_ema_pullback("TEST", df, sr_zones=[])
    assert result is None, "High volume today: must be rejected by volume-dry gate"


def test_ema_pullback_rejects_bad_rs():
    """RS score below -0.05 → RS gate must reject."""
    df = make_ema_pullback_df()
    result = scan_ema_pullback("TEST", df, sr_zones=[], rs_score=-0.10)
    assert result is None, "Weak RS score (-0.10): must be rejected by RS quality gate"
