"""Tests for Sniper Debug Mode — verifies debug=True prints rejection reasons."""
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


def _trend_fail_df(n: int = 70) -> pd.DataFrame:
    """
    Downtrend stock: first 50 bars at 100, last 20 at 60.
    Result: lc=60, SMA50≈84, EMA8≈60.3, EMA20≈65.1
    → l8 NOT > l20  AND  lc < l50  → trend filter fails in all engines.
    """
    prices = [100.0] * 50 + [60.0] * 20
    dates  = pd.date_range("2022-01-01", periods=n, freq="B")
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
    is_price_vital(df, debug=False)
    assert capsys.readouterr().out == ""
