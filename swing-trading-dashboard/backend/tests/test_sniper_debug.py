"""Tests for Sniper Debug Mode — verifies debug=True prints rejection reasons."""
import random

import pandas as pd
import pytest

# ── Shared DataFrame helpers ──────────────────────────────────────────────

def _flatline_df(n: int = 15) -> pd.DataFrame:
    """A zombie stock: 10-day H-L range < 2% → fails is_price_vital."""
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open":      [100.0] * n,
        "High":      [100.5] * n,   # range = 0.5 / 100.5 ≈ 0.5% < 2%
        "Low":       [100.0] * n,
        "Close":     [100.0] * n,
        "Adj Close": [100.0] * n,
        "Volume":    [1_000_000] * n,
    }, index=dates)


def _trend_fail_df(n: int = 80) -> pd.DataFrame:
    """
    Downtrend stock: gradual linear decline from 100 to 60 over n bars,
    with slight random noise so CCI mean-deviation is never zero.
    Result: lc≈60, SMA50 > lc, EMA8 < EMA20
    → l8 NOT > l20  AND  lc < l50  → trend filter fails in all engines.
    The noise keeps CCI non-NaN so scan_pullback reaches the trend gate.
    """
    rng = random.Random(0)
    prices = [
        round(100.0 - (40.0 * i / (n - 1)) + rng.uniform(-0.5, 0.5), 4)
        for i in range(n)
    ]
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open":      prices,
        "High":      [p + 1.0 for p in prices],
        "Low":       [p - 1.0 for p in prices],
        "Close":     prices,
        "Adj Close": prices,
        "Volume":    [1_000_000] * n,
    }, index=dates)


# ── Task 1: is_price_vital ────────────────────────────────────────────────

from validation import is_price_vital


def test_vitality_debug_prints_rejection(capsys):
    """debug=True on a flatline stock prints a Vitality REJECTED message."""
    df = _flatline_df()
    result = is_price_vital(df, debug=True)
    assert result is False
    out = capsys.readouterr().out
    assert "Vitality: REJECTED" in out
    assert "Zombie" in out


def test_vitality_debug_false_no_output(capsys):
    """debug=False (default) produces no stdout even when stock is rejected."""
    df = _flatline_df()
    result = is_price_vital(df, debug=False)
    assert result is False
    assert capsys.readouterr().out == ""


# ── Task 2: scan_resistance_breakout ─────────────────────────────────────

from engines.engine6 import scan_resistance_breakout


def test_engine6_debug_below_sma50(capsys):
    """debug=True when close < SMA50 prints Engine 6 REJECTED – Below 50 SMA."""
    df = _trend_fail_df()   # lc=60, SMA50≈84 → rejected immediately
    result = scan_resistance_breakout("TEST", df, [], debug=True)
    assert result is None
    out = capsys.readouterr().out
    assert "Engine 6 Breakout: REJECTED" in out
    assert "50 SMA" in out


def test_engine6_debug_false_no_output(capsys):
    """debug=False produces no stdout on a rejected ticker."""
    df = _trend_fail_df()
    scan_resistance_breakout("TEST", df, [], debug=False)
    assert capsys.readouterr().out == ""


def test_engine6_debug_no_zones(capsys):
    """debug=True with uptrend but empty zone list prints 'No KDE resistance zones'."""
    # 70 bars all at 100 → passes uptrend filter, then hits empty zone check
    prices = [100.0] * 70
    dates  = pd.date_range("2022-01-01", periods=70, freq="B")
    df_up = pd.DataFrame({
        "Open": prices, "High": [p + 1 for p in prices],
        "Low":  [p - 1 for p in prices], "Close": prices,
        "Adj Close": prices, "Volume": [1_000_000] * 70,
    }, index=dates)
    result = scan_resistance_breakout("TEST", df_up, [], debug=True)
    assert result is None
    out = capsys.readouterr().out
    assert "Engine 6 Breakout: REJECTED" in out
    assert "No KDE resistance zones" in out


# ── Task 3: scan_pullback ────────────────────────────────────────────────

from engines.engine3 import scan_pullback


def test_pullback_debug_trend_filter(capsys):
    """debug=True prints trend filter rejection for a downtrending stock."""
    df = _trend_fail_df()
    result = scan_pullback("TEST", df, [], None, debug=True)
    assert result is None
    out = capsys.readouterr().out
    assert "Engine 3 Pullback: REJECTED" in out
    assert "Trend filter" in out


def test_pullback_debug_false_no_output(capsys):
    """debug=False produces no stdout."""
    df = _trend_fail_df()
    scan_pullback("TEST", df, [], None, debug=False)
    assert capsys.readouterr().out == ""


# ── Task 4: scan_relaxed_pullback ────────────────────────────────────────

from engines.engine3 import scan_relaxed_pullback


def test_rlx_pullback_debug_trend_filter(capsys):
    """debug=True prints trend filter rejection for a downtrending stock."""
    df = _trend_fail_df()
    result = scan_relaxed_pullback("TEST", df, [], None, debug=True)
    assert result is None
    out = capsys.readouterr().out
    assert "Engine 3 RLX Pullback: REJECTED" in out
    assert "Trend filter" in out


def test_rlx_pullback_debug_false_no_output(capsys):
    """debug=False produces no stdout."""
    df = _trend_fail_df()
    scan_relaxed_pullback("TEST", df, [], None, debug=False)
    assert capsys.readouterr().out == ""


# ── Task 5: scan_vcp ─────────────────────────────────────────────────────

from engines.engine2 import scan_vcp


def test_vcp_debug_trend_filter(capsys):
    """debug=True prints trend filter rejection for a downtrending stock."""
    df = _trend_fail_df()
    result = scan_vcp("TEST", df, [], debug=True)
    assert result is None
    out = capsys.readouterr().out
    assert "Engine 2 VCP: REJECTED" in out
    assert "Trend filter" in out


def test_vcp_debug_false_no_output(capsys):
    """debug=False produces no stdout."""
    df = _trend_fail_df()
    scan_vcp("TEST", df, [], debug=False)
    assert capsys.readouterr().out == ""
