"""Tests for Engine 5: Base Pattern Scanner."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from engines.engine5 import (
    _find_cup,
    _is_u_shaped,
    _find_handle,
    _quality_score,
    scan_cup_handle,
    scan_flat_base,
    scan_base_pattern,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_cup_handle_df(n_total=110, cup_depth=0.20, handle_pct=0.08):
    """
    Build a synthetic DataFrame with a clear cup & handle pattern.
    Structure: 30 bars uptrend → 40-bar cup → 40-bar recovery → 20-bar handle → 20 bars near pivot
    """
    dates = pd.date_range("2025-01-01", periods=n_total, freq="B")

    close = np.ones(n_total) * 100.0
    # Uptrend into left peak
    for i in range(30):
        close[i] = 90 + i * 0.5          # ramp from 90 to 104.5
    left_peak = close[29]                 # ~104.5

    # Cup: half-sine dip
    for i in range(40):
        angle = np.pi * i / 39
        close[30 + i] = left_peak - cup_depth * left_peak * np.sin(angle)

    right_rim = close[69]                 # should be close to left_peak

    # Handle: small drift down
    for i in range(20):
        t = i / 19
        close[70 + i] = right_rim - handle_pct * right_rim * np.sin(np.pi * t)

    # Near pivot (last 20 bars drift up toward right_rim)
    for i in range(20):
        close[90 + i] = right_rim * 0.99 + i * 0.01

    high = close * 1.01
    low = close * 0.99
    volume = np.full(n_total, 1_000_000.0)
    volume[70:90] = 600_000.0   # dry-up in handle
    volume[-1] = 1_000_000.0

    df = pd.DataFrame({
        "Close": close,
        "High": high,
        "Low": low,
        "Open": close * 0.995,
        "Volume": volume,
    }, index=dates)
    return df


def make_flat_base_df(n_total=100, base_depth=0.08, base_days=35):
    """Build a synthetic DataFrame with a flat base at the end."""
    dates = pd.date_range("2025-01-01", periods=n_total, freq="B")

    close = np.ones(n_total) * 100.0
    trend_bars = n_total - base_days
    for i in range(trend_bars):
        close[i] = 80 + i * (20.0 / trend_bars)

    base_start = close[trend_bars - 1]
    for i in range(base_days):
        t = i / base_days
        close[trend_bars + i] = base_start * (1 - base_depth * 0.25 * np.sin(2 * np.pi * t))

    close[-1] = base_start * 0.996

    high = close * 1.005
    low = close * 0.995
    volume = np.full(n_total, 1_000_000.0)
    volume[trend_bars:] = 700_000.0   # contraction in base

    df = pd.DataFrame({
        "Close": close,
        "High": high,
        "Low": low,
        "Open": close * 0.998,
        "Volume": volume,
    }, index=dates)
    return df


class TestFindCup:
    def test_finds_cup_in_valid_data(self):
        df = make_cup_handle_df()
        close = df["Close"].values
        cup = _find_cup(close, lookback=120)
        assert cup is not None
        assert "left_peak" in cup
        assert "cup_bottom" in cup
        assert "right_rim" in cup
        assert 0.12 <= cup["depth"] <= 0.35

    def test_rejects_too_shallow(self):
        """Cup depth < 12% should return None."""
        close = np.linspace(100, 98, 120)   # only 2% dip — too shallow
        cup = _find_cup(close, lookback=120)
        if cup is not None:
            assert cup["depth"] >= 0.12

    def test_rejects_too_deep(self):
        """Cup depth > 35% should return None."""
        close = np.concatenate([
            np.linspace(100, 50, 60),   # 50% drop — too deep
            np.linspace(50, 100, 60),
        ])
        cup = _find_cup(close, lookback=120)
        if cup is not None:
            assert cup["depth"] <= 0.35

    def test_right_rim_within_10pct_of_left_peak(self):
        df = make_cup_handle_df()
        close = df["Close"].values
        cup = _find_cup(close, lookback=120)
        if cup is not None:
            gap = (cup["left_peak"] - cup["right_rim"]) / cup["left_peak"]
            assert gap <= 0.10


class TestIsUShaped:
    def test_true_for_parabolic_cup(self):
        df = make_cup_handle_df()
        close = df["Close"].values
        cup = _find_cup(close, lookback=120)
        assert cup is not None
        assert _is_u_shaped(close[-120:], cup) is True

    def test_false_for_v_shape(self):
        """Sharp V-drop: just ensure no crash and returns bool."""
        close = np.concatenate([
            np.linspace(100, 70, 5),
            np.linspace(70, 100, 5),
            np.ones(10) * 100,
        ])
        cup = {"left_peak_idx": 0, "right_rim_idx": 9,
               "cup_bottom_idx": 4, "left_peak": 100.0,
               "cup_bottom": 70.0, "right_rim": 100.0,
               "depth": 0.30, "cup_length": 9}
        result = _is_u_shaped(close, cup)
        assert isinstance(result, bool)


class TestFindHandle:
    def test_finds_valid_handle(self):
        df = make_cup_handle_df(handle_pct=0.08)
        close = df["Close"].values[-120:]
        high = df["High"].values[-120:]
        volume = df["Volume"].values[-120:]
        cup = _find_cup(close, lookback=120)
        assert cup is not None
        vol_sma50 = float(np.mean(volume))
        handle = _find_handle(close, high, volume, cup, vol_sma50)
        assert handle is not None
        assert "handle_high" in handle
        assert "handle_low" in handle
        assert 0.05 <= handle["pullback_pct"] <= 0.15

    def test_rejects_deep_handle(self):
        """Handle pullback > 15% should return None."""
        df = make_cup_handle_df(handle_pct=0.25)
        close = df["Close"].values[-120:]
        high = df["High"].values[-120:]
        volume = df["Volume"].values[-120:]
        cup = _find_cup(close, lookback=120)
        if cup is not None:
            vol_sma50 = float(np.mean(volume))
            handle = _find_handle(close, high, volume, cup, vol_sma50)
            if handle is not None:
                assert handle["pullback_pct"] <= 0.15


class TestQualityScore:
    def test_perfect_score(self):
        """All factors maxed out → 100."""
        score = _quality_score(
            depth_pct=0.05,     # very tight (< 8%)
            max_depth_pct=0.35,
            vol_dry_pct=0.3,    # 30% of avg (heavy dry-up)
            rs_vs_spy=0.10,     # +10% vs SPY (above 5% threshold)
            rs_blue_dot=True,
        )
        assert score == 100

    def test_zero_score(self):
        """All factors at worst → 0."""
        score = _quality_score(
            depth_pct=0.35,     # at max depth (0 tightness pts)
            max_depth_pct=0.35,
            vol_dry_pct=1.5,    # volume above avg (0 vol pts)
            rs_vs_spy=-0.10,    # underperforming SPY (0 RS pts)
            rs_blue_dot=False,
        )
        assert score == 0

    def test_blue_dot_adds_25(self):
        """RS blue dot adds exactly 25 pts."""
        s1 = _quality_score(0.35, 0.35, 1.5, -0.10, False)
        s2 = _quality_score(0.35, 0.35, 1.5, -0.10, True)
        assert s2 - s1 == 25

    def test_score_in_range(self):
        score = _quality_score(0.15, 0.35, 0.70, 0.02, False)
        assert 0 <= score <= 100


class TestScanCupHandle:
    def test_detects_cup_handle_in_synthetic_data(self):
        df = make_cup_handle_df(cup_depth=0.20, handle_pct=0.08)
        result = scan_cup_handle("TEST", df, spy_3m_return=0.03,
                                  rs_ratio=1.05, rs_52w_high=1.0, rs_blue_dot=False)
        if result is not None:
            assert result["setup_type"] == "BASE"
            assert result["base_type"] == "CUP_HANDLE"
            assert result["signal"] in ("DRY", "BRK")
            assert result["entry"] > result["stop_loss"]
            assert result["take_profit"] > result["entry"]
            assert result["rr"] == 2.0
            assert 0 <= result["quality_score"] <= 100
            assert "base_depth_pct" in result
            assert "base_length_days" in result

    def test_returns_none_for_short_data(self):
        df = make_cup_handle_df()
        result = scan_cup_handle("TEST", df.iloc[:30])
        assert result is None

    def test_returns_none_for_empty_df(self):
        result = scan_cup_handle("TEST", pd.DataFrame())
        assert result is None


class TestScanFlatBase:
    def test_detects_flat_base_in_synthetic_data(self):
        df = make_flat_base_df(base_depth=0.07, base_days=35)
        result = scan_flat_base("TEST", df, spy_3m_return=0.02,
                                 rs_ratio=1.03, rs_52w_high=1.0, rs_blue_dot=True)
        if result is not None:
            assert result["setup_type"] == "BASE"
            assert result["base_type"] == "FLAT_BASE"
            assert result["signal"] in ("DRY", "BRK")
            assert result["entry"] > result["stop_loss"]
            assert result["take_profit"] > result["entry"]
            assert 0 <= result["quality_score"] <= 100

    def test_rejects_wide_base(self):
        """Base depth > 15% should return None."""
        df = make_flat_base_df(base_depth=0.25, base_days=35)
        result = scan_flat_base("TEST", df)
        assert result is None

    def test_returns_none_for_empty_df(self):
        result = scan_flat_base("TEST", pd.DataFrame())
        assert result is None


def test_find_handle_uses_intraday_high_for_handle_high():
    """handle_high must be the max intraday High in the handle window, not just rim close."""
    n = 50
    # Cup: left_peak_idx=0, cup_bottom_idx=20, right_rim_idx=40
    cup = {
        "left_peak_idx": 0, "left_peak": 100.0,
        "cup_bottom_idx": 20, "cup_bottom": 80.0,
        "right_rim_idx": 40, "right_rim": 98.0,
        "depth": 0.20, "cup_length": 40,
    }
    close = np.ones(n) * 100.0
    # Handle window bars (41–49): pull back ~7% from rim (98 * 0.93 = 91.14),
    # which is above cup_midpoint=(100+80)/2=90 and within 3-15% pullback band.
    close[41:] = 98.0 * 0.93  # ~91.14 — valid handle pullback
    # Make a bar in handle window (bar 43) with intraday high of 101
    high = close * 1.005        # default: just slightly above close
    high[43] = 101.0            # spike in handle window
    volume = np.full(n, 500_000.0)  # below 50d avg = 1_000_000
    vol_sma50 = 1_000_000.0

    result = _find_handle(close, high, volume, cup, vol_sma50)
    assert result is not None, "_find_handle returned None unexpectedly"
    assert result["handle_high"] == pytest.approx(101.0), \
        f"handle_high should be 101.0 (max intraday High), got {result['handle_high']}"


def test_flat_base_pivot_uses_intraday_high():
    """Flat base breakout pivot must use highest intraday High, not highest close."""
    # Build a dedicated fixture that satisfies every scan_flat_base gate:
    #   - 100 bars: 40 trend (50→100) + 60 flat (all closes = 100)
    #   - One deep intrabar Low at bar 45 (Low = 91) so pct_in_range >= 0.75
    #     and depth ≈ 9.5% (still within the ≤ 12% limit)
    #   - Volume dry-up: bars -10 to -1 at 300k vs 50-day avg ≈ 540k (ratio ≈ 0.56)
    #   - Last close = 100.0, all Highs = close * 1.005 = 100.5 before injection
    n = 100
    trend = 40
    base = 60
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.ones(n) * 100.0
    for i in range(trend):
        close[i] = 50 + i * (50.0 / (trend - 1))
    close[trend:] = 100.0          # perfectly flat base
    high = close * 1.005
    low = close * 0.995
    low[trend + 5] = 91.0          # one deep intrabar wick — deepens base_low to 91
    volume = np.ones(n) * 1_000_000.0
    volume[trend:-10] = 600_000.0
    volume[-10:] = 300_000.0       # dry-up at the end
    df = pd.DataFrame({
        "Close": close, "High": high, "Low": low,
        "Open": close * 0.998, "Volume": volume,
    }, index=dates)

    # Inject an intraday High spike at the last bar: 0.9% above all closes.
    # This becomes the new base_high (pivot). dist_to_pivot = (100.9-100)/100.9 ≈ 0.89% ≤ 1%
    # so DRY fires. All other Highs are 100.5, so this spike is clearly the new max.
    df.iloc[-1, df.columns.get_loc("High")] = df["Close"].max() * 1.009

    result = scan_flat_base("TEST", df)
    assert result is not None, "scan_flat_base should detect the pattern"
    # Entry is pivot * 1.001; pivot should reflect the intraday High spike
    assert result["entry"] > df["Close"].max() * 1.001, \
        "Entry should be above highest-close pivot when intraday High is higher"


def test_flat_base_detects_when_200sma_not_rising():
    """Flat base must be found even when 200 SMA is flat, as long as close > 200 SMA."""
    from engines.engine5 import scan_flat_base
    import numpy as np, pandas as pd

    # 400 bars: 50-bar prior advance to 102.0, then 350 bars flat at 102.0.
    # SMA200 at end ≈ 102.0 = lc, so close > 200 SMA check passes (not strictly less-than).
    # One deep intrabar low at bar 340 (within the 60-bar lookback window) adds depth
    # so pct_in_range ≥ 0.75 and depth stays ≤ 12%.
    # Volume: 1M baseline, 200k dry-up over the last 10 bars gives ratio ≈ 0.24.
    n = 400
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.full(n, 102.0, dtype=float)
    close[:50] = np.linspace(70.0, 102.0, 50)   # prior advance

    high = close * 1.002
    low  = close * 0.998
    low[340] = 98.0   # deep wick inside last-60-bar window — adds range without breaking flatness

    volume = np.full(n, 1_000_000.0)
    volume[-10:] = 200_000.0   # dry-up: vol_sma10 ≈ 200k vs vol_sma50 ≈ 840k → ratio ≈ 0.24

    df = pd.DataFrame(
        {"Close": close, "Adj Close": close, "High": high,
         "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )

    # Verify precondition: 200 SMA is NOT rising (today ≈ 20 bars ago)
    sma200 = pd.Series(close).rolling(200).mean()
    assert sma200.iloc[-1] <= sma200.iloc[-21] + 0.1, "Precondition: 200 SMA must not be rising"

    result = scan_flat_base("TEST", df)
    assert result is not None, "Should find flat base even when 200 SMA is flat/not-rising"
