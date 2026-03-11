"""Tests for centralized filter logic in filters.py."""
import sys, os
import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def _make_spy_df(n: int, trend: str) -> pd.DataFrame:
    dates = pd.date_range("2015-01-01", periods=n, freq="B")
    if trend == "bull":
        close = np.linspace(80.0, 200.0, n)
    else:
        close = np.linspace(200.0, 80.0, n)
    return pd.DataFrame({"Close": close, "Open": close, "High": close*1.01,
                         "Low": close*0.99, "Volume": np.full(n, 1_000_000)},
                        index=dates)


def test_regime_series_bullish_trend():
    from filters import compute_regime_series
    spy = _make_spy_df(300, "bull")
    series = compute_regime_series(spy)
    assert series.iloc[-1] is True or series.iloc[-1] == True
    assert isinstance(series, pd.Series)
    assert series.dtype == bool


def test_regime_series_bearish_trend():
    from filters import compute_regime_series
    spy = _make_spy_df(300, "bear")
    series = compute_regime_series(spy)
    assert series.iloc[-1] is False or series.iloc[-1] == False


def test_regime_series_aligned_with_spy_index():
    from filters import compute_regime_series
    spy = _make_spy_df(300, "bull")
    series = compute_regime_series(spy)
    assert series.index.equals(spy.index)


def test_regime_series_short_history_returns_false():
    from filters import compute_regime_series
    spy = _make_spy_df(50, "bull")
    series = compute_regime_series(spy)
    assert series.all() == False or not series.any()


def test_regime_series_none_input_returns_empty():
    """compute_regime_series(None) should return an empty Series, not crash."""
    from filters import compute_regime_series
    result = compute_regime_series(None)
    assert isinstance(result, pd.Series)
    assert len(result) == 0


def _make_df_with_volume(avg_vol: float, n: int = 60) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.full(n, 100.0)
    volume = np.full(n, avg_vol)
    return pd.DataFrame({"Close": close, "Volume": volume,
                         "Open": close, "High": close, "Low": close},
                        index=dates)


def test_passes_liquidity_high_volume():
    from filters import passes_liquidity
    df = _make_df_with_volume(1_000_000)
    assert passes_liquidity(df) is True


def test_passes_liquidity_low_volume():
    from filters import passes_liquidity
    df = _make_df_with_volume(100_000)
    assert passes_liquidity(df) is False


def test_passes_liquidity_uses_50d_rolling():
    from filters import passes_liquidity
    dates = pd.date_range("2024-01-01", periods=60, freq="B")
    vols = np.zeros(60)
    vols[-11:] = 5_000_000
    df = pd.DataFrame({"Close": np.full(60, 100.0), "Volume": vols,
                       "Open": np.full(60, 100.0), "High": np.full(60, 101.0),
                       "Low": np.full(60, 99.0)}, index=dates)
    assert passes_liquidity(df) is False


def test_passes_liquidity_empty_df():
    from filters import passes_liquidity
    df = pd.DataFrame({"Close": [], "Volume": [], "Open": [], "High": [], "Low": []})
    assert passes_liquidity(df) is False


def test_earnings_blackout_within_window():
    from filters import in_earnings_blackout
    assert in_earnings_blackout("2024-01-10", ["2024-01-15"]) is True


def test_earnings_blackout_outside_window():
    from filters import in_earnings_blackout
    assert in_earnings_blackout("2024-01-10", ["2024-02-15"]) is False


def test_earnings_blackout_day_before():
    from filters import in_earnings_blackout
    assert in_earnings_blackout("2024-01-10", ["2024-01-09"]) is True


def test_earnings_blackout_empty_list():
    from filters import in_earnings_blackout
    assert in_earnings_blackout("2024-01-10", []) is False


def test_earnings_blackout_multiple_dates():
    from filters import in_earnings_blackout
    assert in_earnings_blackout("2024-01-10", ["2024-06-01", "2024-01-14"]) is True


def test_regime_label_series_bull_is_aggressive():
    """Strong uptrend SPY → AGGRESSIVE labels at end."""
    from filters import compute_regime_label_series
    spy = _make_spy_df(300, "bull")
    labels = compute_regime_label_series(spy)
    assert labels.iloc[-1] == "AGGRESSIVE"
    assert isinstance(labels, pd.Series)
    assert labels.dtype == object


def test_regime_label_series_bear_is_defensive():
    """Bear trend → DEFENSIVE labels."""
    from filters import compute_regime_label_series
    spy = _make_spy_df(300, "bear")
    labels = compute_regime_label_series(spy)
    assert labels.iloc[-1] == "DEFENSIVE"


def test_regime_label_series_index_matches_spy():
    """Output index matches spy_df index."""
    from filters import compute_regime_label_series
    spy = _make_spy_df(300, "bull")
    labels = compute_regime_label_series(spy)
    assert labels.index.equals(spy.index)


def test_regime_label_series_short_history_defensive():
    """< 200 bars → all DEFENSIVE (insufficient SMA200)."""
    from filters import compute_regime_label_series
    spy = _make_spy_df(50, "bull")
    labels = compute_regime_label_series(spy)
    assert (labels == "DEFENSIVE").all()


def test_regime_label_series_none_returns_empty():
    """None input → empty Series."""
    from filters import compute_regime_label_series
    result = compute_regime_label_series(None)
    assert isinstance(result, pd.Series)
    assert len(result) == 0
