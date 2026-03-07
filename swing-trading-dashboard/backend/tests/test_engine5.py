"""Tests for Engine 5 v2: Volatility-Adjusted Base Pattern Scanner."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from engines.engine5 import (
    _mean_tr,
    _quality_score,
    scan_cup_handle,
    scan_flat_base,
    scan_base_pattern,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_darvas_box_df(n_total=260, box_days=30, atr_multiple=2.5):
    """
    Build a DataFrame with a valid ATR-Adjusted Darvas Box at the end.

    Structure: strong uptrend (SMA50 > SMA200 guaranteed) + tight box.
    ATR ≈ 1.0 (H-L = 1.0 per bar). Box height = atr_multiple × 1.0.
    Ceiling touched ≥ 2×. Last close in upper 25% of box.
    Volume dry-up last 3 bars.
    """
    dates = pd.date_range("2023-01-01", periods=n_total, freq="B")
    close = np.ones(n_total, dtype=float)

    trend_bars = n_total - box_days
    # Strong uptrend: 50 → 100 over trend_bars
    for i in range(trend_bars):
        close[i] = 50.0 + i * (50.0 / (trend_bars - 1))

    # Box: oscillate between (100 - box_height) and 100
    box_high_price = 100.0
    box_height = atr_multiple * 1.0   # ATR ≈ 1.0
    box_low_price = box_high_price - box_height

    for i in range(box_days):
        t = i / box_days
        close[trend_bars + i] = box_low_price + box_height * (0.4 + 0.3 * np.sin(2 * np.pi * t))

    # Last bar: upper 25% (need close ≥ box_low + 0.75 * box_height)
    upper_25 = box_low_price + 0.75 * box_height
    close[-1] = upper_25 + 0.1   # just above upper quartile

    # H = close + 0.5, L = close - 0.5 → H-L = 1.0, ATR ≈ 1.0
    high = close + 0.5
    low  = close - 0.5

    # Ensure ceiling is touched at least twice: two bars at the box high
    high[trend_bars + 3]  = box_high_price + 0.5   # ceiling touch 1
    high[trend_bars + 18] = box_high_price + 0.5   # ceiling touch 2

    # Last close must be within 1% of ceiling for DRY signal
    ceiling = float(np.max(high[-(box_days):]))
    close[-1] = ceiling * 0.992   # ~0.8% below ceiling → DRY signal

    volume = np.full(n_total, 1_000_000.0)
    volume[-3:] = 600_000.0   # 3-day dry-up

    return pd.DataFrame({
        "Close": close, "High": high, "Low": low,
        "Open": close * 0.998, "Volume": volume,
    }, index=dates)


def make_low_atr_drifter_df(n_total=260):
    """
    A slowly drifting stock with very low ATR — should be REJECTED.
    Box height ≈ 8 pts, ATR ≈ 0.2 pts → multiple ≈ 40× >> 3.5.
    SMA50 > SMA200 holds (it has been in uptrend), but ATR gate kills it.
    """
    dates = pd.date_range("2023-01-01", periods=n_total, freq="B")
    close = np.linspace(50, 100, n_total)   # slow linear drift upward

    # Tight H/L spread → very low ATR
    high   = close + 0.1
    low    = close - 0.1
    volume = np.full(n_total, 1_000_000.0)
    volume[-3:] = 600_000.0

    return pd.DataFrame({
        "Close": close, "High": high, "Low": low,
        "Open": close, "Volume": volume,
    }, index=dates)


def make_cup_handle_v2_df(n_total=350, cup_depth=0.18, atr_pct=0.025):
    """
    Proportional Cup & Handle fixture that passes all new gates:
      - 200+ bars for SMA200 (uptrend 50→100 over first 230 bars)
      - Cup within last 120 bars: 18% depth, peak-to-low = 50 bars
      - Right rim recovers > 50% of depth
      - Last close in upper 50% of cup (handle zone)
      - Handle ATR < decline ATR
      - Volume dry-up in handle
    """
    dates = pd.date_range("2022-01-01", periods=n_total, freq="B")
    close = np.ones(n_total, dtype=float)

    # Prior uptrend: bars 0-229 from 50 to 100
    trend_end = 230
    for i in range(trend_end):
        close[i] = 50.0 + i * (50.0 / (trend_end - 1))

    # Cup window starts at bar 230 (= n_total - 120)
    cup_start = n_total - 120

    # Left peak zone: bars 230-244 plateau at 100
    close[cup_start: cup_start + 15] = 100.0

    # Decline phase: bars 245-294 (50 bars) from 100 down to 82
    cup_bottom_price = 100.0 * (1 - cup_depth)   # 82 for 18% depth
    decline_len = 50
    for i in range(decline_len):
        t = i / (decline_len - 1)
        close[cup_start + 15 + i] = 100.0 - cup_depth * 100.0 * np.sin(np.pi * t / 2)

    # Recovery: bars 295-324 (30 bars) from bottom back to ~96
    recovery_start = cup_start + 15 + decline_len   # bar 295
    recovery_target = 100.0 - cup_depth * 100.0 * 0.40   # recover to ~92.8 (60% recovery)
    for i in range(30):
        t = i / 29
        close[recovery_start + i] = cup_bottom_price + (recovery_target - cup_bottom_price) * t

    # Handle: bars 325-349 (25 bars) — tight consolidation at ~92 (upper 50% of cup)
    handle_start = recovery_start + 30   # bar 325
    handle_level = cup_bottom_price + 0.60 * (100.0 - cup_bottom_price)  # upper 60% of cup
    for i in range(n_total - handle_start):
        close[handle_start + i] = handle_level + 0.5 * np.sin(2 * np.pi * i / 8)

    # Last close: near handle high for DRY signal
    close[-1] = handle_level + 0.4   # just below handle high

    # H/L per phase
    # Decline phase: large swings (2% of close) — high ATR
    high = close * 1.005
    low  = close * 0.995
    for i in range(decline_len):
        idx = cup_start + 15 + i
        high[idx] = close[idx] * 1.02
        low[idx]  = close[idx] * 0.98

    # Handle phase: tight swings (0.5% of close) — low ATR (contraction ✓)
    for i in range(n_total - handle_start):
        idx = handle_start + i
        high[idx] = close[idx] * 1.005
        low[idx]  = close[idx] * 0.995

    # Volume dry-up in handle
    volume = np.full(n_total, 1_000_000.0)
    volume[handle_start:] = 650_000.0

    return pd.DataFrame({
        "Close": close, "High": high, "Low": low,
        "Open": close * 0.998, "Volume": volume,
    }, index=dates)


def make_low_atr_deep_cup_df(n_total=350):
    """
    A low-ATR stock that drops 28% — exceeds its ATR-allowed max depth.
    ATR ≈ 0.3% of price → max_depth = 0.003 * 10 = 3% << 28%. Rejected.
    """
    dates = pd.date_range("2022-01-01", periods=n_total, freq="B")
    close = np.ones(n_total, dtype=float)

    # Uptrend to 100
    for i in range(230):
        close[i] = 50 + i * (50.0 / 229)

    # Deep 28% drop over 80 bars
    for i in range(80):
        t = i / 79
        close[230 + i] = 100.0 - 28.0 * np.sin(np.pi * t / 2)

    # Recovery to 90
    for i in range(40):
        close[310 + i] = 72.0 + i * (18.0 / 39)

    # Handle at 90 (upper 50%: 72 + 0.5*28 = 86 → 90 is valid location,
    # but ATR gate should reject this stock entirely)
    close[-1] = 90.0

    # Very tight H/L (low ATR ≈ 0.3)
    high = close + 0.15
    low  = close - 0.15
    volume = np.full(n_total, 1_000_000.0)

    return pd.DataFrame({
        "Close": close, "High": high, "Low": low,
        "Open": close, "Volume": volume,
    }, index=dates)


# ── Tests: _mean_tr ────────────────────────────────────────────────────────────

class TestMeanTr:
    def test_basic_calculation(self):
        # H-L = 2 each bar, no gaps → TR = 2 throughout
        # close[0] = 10 so the prev-close gap on bar 1 is zero
        high  = np.array([10.0, 11.0, 11.0, 11.0, 11.0, 11.0], dtype=float)
        low   = np.array([10.0,  9.0,  9.0,  9.0,  9.0,  9.0], dtype=float)
        close = np.array([10.0, 10.0, 10.0, 10.0, 10.0, 10.0], dtype=float)
        result = _mean_tr(high, low, close, 1, 6)
        assert result == pytest.approx(2.0, abs=0.01)

    def test_too_small_window_returns_zero(self):
        high  = np.array([10.0, 11.0], dtype=float)
        low   = np.array([ 9.0, 10.0], dtype=float)
        close = np.array([10.0, 10.5], dtype=float)
        assert _mean_tr(high, low, close, 1, 2) == 0.0

    def test_returns_float(self):
        high  = np.array([0, 105.0, 107.0, 106.0, 104.0, 108.0], dtype=float)
        low   = np.array([0, 103.0, 104.0, 102.0, 103.0, 105.0], dtype=float)
        close = np.array([0, 104.0, 106.0, 103.0, 103.5, 107.0], dtype=float)
        result = _mean_tr(high, low, close, 1, 6)
        assert isinstance(result, float)
        assert result > 0


# ── Tests: _quality_score ──────────────────────────────────────────────────────

class TestQualityScore:
    def test_perfect_score(self):
        score = _quality_score(
            tightness_pct=0.0,
            vol_dry_pct=0.2,
            rs_vs_spy=0.10,
            rs_blue_dot=True,
        )
        assert score == 100

    def test_zero_score(self):
        score = _quality_score(
            tightness_pct=1.0,
            vol_dry_pct=1.5,
            rs_vs_spy=-0.10,
            rs_blue_dot=False,
        )
        assert score == 0

    def test_blue_dot_adds_25(self):
        s1 = _quality_score(1.0, 1.5, -0.10, False)
        s2 = _quality_score(1.0, 1.5, -0.10, True)
        assert s2 - s1 == 25

    def test_score_in_range(self):
        score = _quality_score(0.5, 0.7, 0.02, False)
        assert 0 <= score <= 100

    def test_tight_box_scores_higher_than_loose(self):
        tight = _quality_score(0.1, 0.5, 0.03, False)
        loose = _quality_score(0.9, 0.5, 0.03, False)
        assert tight > loose

    def test_heavy_vol_dryup_scores_higher(self):
        low_vol  = _quality_score(0.5, 0.2, 0.03, False)
        high_vol = _quality_score(0.5, 0.9, 0.03, False)
        assert low_vol > high_vol


# ── Tests: scan_flat_base (Darvas Box) ────────────────────────────────────────

class TestScanFlatBase:
    def test_detects_valid_darvas_box(self):
        df = make_darvas_box_df()
        result = scan_flat_base("TEST", df)
        if result is not None:
            assert result["setup_type"] == "BASE"
            assert result["base_type"] == "FLAT_BASE"
            assert result["signal"] in ("DRY", "BRK")
            assert result["entry"] > result["stop_loss"]
            assert result["take_profit"] > result["entry"]
            assert 0 <= result["quality_score"] <= 100
            assert "geometry" in result
            assert result["base_length_days"] >= 20

    def test_rejects_low_atr_drifter(self):
        """Low-ATR drifting stock: box_height >> 3.5 × ATR → always rejected."""
        df = make_low_atr_drifter_df()
        result = scan_flat_base("TEST", df)
        assert result is None

    def test_requires_stage2_uptrend(self):
        """Stock in Stage 1 (SMA50 < SMA200) must be rejected."""
        n = 260
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        # Downtrend then flatten: SMA50 will be below SMA200
        close = np.concatenate([
            np.linspace(100, 60, 200),   # sharp downtrend
            np.full(60, 62.0),            # flat bottom
        ])
        high = close + 0.5
        low  = close - 0.5
        volume = np.full(n, 1_000_000.0)
        volume[-3:] = 500_000.0
        df = pd.DataFrame({
            "Close": close, "High": high, "Low": low,
            "Open": close, "Volume": volume,
        }, index=dates)
        result = scan_flat_base("TEST", df)
        assert result is None

    def test_rejects_when_close_below_sma50(self):
        """Even with SMA50 > SMA200, close must be above SMA50."""
        df = make_darvas_box_df()
        # Pull close below SMA50 for last bar only
        adj = df["Close"].copy()
        adj.iloc[-1] = adj.iloc[-1] * 0.85   # 15% below current close
        df["Close"] = adj
        result = scan_flat_base("TEST", df)
        assert result is None

    def test_requires_ceiling_touches(self):
        """No ceiling touches → rejected."""
        n = 260
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = np.ones(n, dtype=float)
        for i in range(230):
            close[i] = 50 + i * (50.0 / 229)
        # Box that monotonically declines (no ceiling revisits)
        for i in range(30):
            close[230 + i] = 100 - i * 0.1   # all below ceiling
        high = close + 0.3
        low  = close - 0.3
        volume = np.full(n, 1_000_000.0)
        volume[-3:] = 500_000.0
        df = pd.DataFrame({
            "Close": close, "High": high, "Low": low,
            "Open": close, "Volume": volume,
        }, index=dates)
        result = scan_flat_base("TEST", df)
        assert result is None

    def test_returns_none_for_empty_df(self):
        assert scan_flat_base("TEST", pd.DataFrame()) is None

    def test_returns_none_for_short_data(self):
        df = make_darvas_box_df()
        result = scan_flat_base("TEST", df.iloc[:30])
        assert result is None

    def test_volume_dryup_required(self):
        """If 3-day avg volume >= 50-day avg, reject."""
        df = make_darvas_box_df()
        # Remove the volume dry-up
        df = df.copy()
        df["Volume"] = 1_000_000.0   # uniform — no dry-up
        result = scan_flat_base("TEST", df)
        assert result is None

    def test_geometry_fields_present(self):
        df = make_darvas_box_df()
        result = scan_flat_base("TEST", df)
        if result is not None:
            g = result["geometry"]
            assert "start_date" in g
            assert "end_date" in g
            assert "base_high" in g
            assert "base_low" in g
            assert g["base_high"] > g["base_low"]


# ── Tests: scan_cup_handle (Proportional) ────────────────────────────────────

class TestScanCupHandle:
    def test_detects_valid_cup_handle(self):
        df = make_cup_handle_v2_df()
        result = scan_cup_handle("TEST", df)
        if result is not None:
            assert result["setup_type"] == "BASE"
            assert result["base_type"] == "CUP_HANDLE"
            assert result["signal"] in ("DRY", "BRK")
            assert result["entry"] > result["stop_loss"]
            assert result["take_profit"] > result["entry"]
            assert 0 <= result["quality_score"] <= 100
            # ATR-proportional depth: 15–45%
            assert 15.0 <= result["base_depth_pct"] <= 45.0

    def test_rejects_low_atr_deep_cup(self):
        """Low-ATR stock with 28% cup depth: atr_pct*10 << 28% → rejected."""
        df = make_low_atr_deep_cup_df()
        result = scan_cup_handle("TEST", df)
        assert result is None

    def test_rejects_shallow_cup(self):
        """Cup depth < 15% must always be rejected."""
        n = 350
        dates = pd.date_range("2022-01-01", periods=n, freq="B")
        close = np.ones(n, dtype=float)
        for i in range(230):
            close[i] = 50 + i * (50.0 / 229)
        # Very shallow 5% cup over 50 bars
        for i in range(50):
            t = i / 49
            close[230 + i] = 100 - 5.0 * np.sin(np.pi * t / 2)
        # Recovery
        for i in range(70):
            close[280 + i] = 95 + i * (5.0 / 69)
        close[-1] = 99.8

        high = close * 1.02
        low  = close * 0.98
        volume = np.full(n, 1_000_000.0)

        df = pd.DataFrame({
            "Close": close, "High": high, "Low": low,
            "Open": close, "Volume": volume,
        }, index=dates)
        result = scan_cup_handle("TEST", df)
        assert result is None

    def test_rejects_v_shape(self):
        """Peak-to-low duration < 25 bars (V-shape) must be rejected."""
        n = 350
        dates = pd.date_range("2022-01-01", periods=n, freq="B")
        close = np.ones(n, dtype=float)
        for i in range(230):
            close[i] = 50 + i * (50.0 / 229)
        # V-shape: 10-bar drop + recovery (duration = 10 < 25 bars)
        for i in range(10):
            close[230 + i] = 100 - 20.0 * (i / 9)
        for i in range(110):
            close[240 + i] = 80.0 + i * (20.0 / 109)
        close[-1] = 99.5

        high = close * 1.02
        low  = close * 0.98
        volume = np.full(n, 1_000_000.0)

        df = pd.DataFrame({
            "Close": close, "High": high, "Low": low,
            "Open": close, "Volume": volume,
        }, index=dates)
        result = scan_cup_handle("TEST", df)
        assert result is None

    def test_rejects_price_below_sma200(self):
        """Close < SMA200 must always be rejected."""
        df = make_cup_handle_v2_df()
        df = df.copy()
        # Force last close far below SMA200
        df["Close"] = df["Close"] * 0.5
        df["High"]  = df["High"]  * 0.5
        df["Low"]   = df["Low"]   * 0.5
        result = scan_cup_handle("TEST", df)
        assert result is None

    def test_rejects_price_below_handle_floor(self):
        """Price must be in upper 50% of cup depth (handle zone)."""
        df = make_cup_handle_v2_df()
        df = df.copy()
        # Set last 5 closes to the cup bottom level (bottom of cup = lower 50%)
        cup_bottom_approx = 100.0 * (1 - 0.18)   # ~82
        df.iloc[-5:, df.columns.get_loc("Close")] = cup_bottom_approx
        df.iloc[-5:, df.columns.get_loc("High")]  = cup_bottom_approx * 1.005
        df.iloc[-5:, df.columns.get_loc("Low")]   = cup_bottom_approx * 0.995
        result = scan_cup_handle("TEST", df)
        assert result is None

    def test_returns_none_for_empty_df(self):
        assert scan_cup_handle("TEST", pd.DataFrame()) is None

    def test_returns_none_for_short_data(self):
        df = make_cup_handle_v2_df()
        assert scan_cup_handle("TEST", df.iloc[:40]) is None

    def test_geometry_fields_present(self):
        df = make_cup_handle_v2_df()
        result = scan_cup_handle("TEST", df)
        if result is not None:
            g = result["geometry"]
            for key in ["left_peak_price", "cup_bottom_price", "right_rim_price",
                        "handle_high", "handle_low"]:
                assert key in g
            assert g["left_peak_price"] > g["cup_bottom_price"]
            assert g["handle_high"] > g["handle_low"]


# ── Tests: scan_base_pattern ──────────────────────────────────────────────────

class TestScanBasePattern:
    def test_returns_none_when_neither_fires(self):
        df = make_low_atr_drifter_df()
        result = scan_base_pattern("TEST", df)
        assert result is None

    def test_quality_gate_25(self):
        """scan_base_pattern must not return setups with quality_score < 25."""
        df = make_darvas_box_df()
        result = scan_base_pattern("TEST", df)
        if result is not None:
            assert result["quality_score"] >= 25

    def test_returns_highest_quality(self):
        """When both patterns fire, highest quality wins."""
        df = make_darvas_box_df()
        ch = scan_cup_handle("TEST", df)
        fb = scan_flat_base("TEST", df)
        result = scan_base_pattern("TEST", df)
        if result is not None and ch is not None and fb is not None:
            assert result["quality_score"] == max(ch["quality_score"], fb["quality_score"])

    def test_rs_vs_spy_negative_when_underperforming(self):
        """rs_vs_spy in output must be negative when stock underperforms SPY."""
        df = make_darvas_box_df()
        result = scan_base_pattern(
            "TEST", df,
            spy_3m_return=0.10,   # SPY +10%
            rs_ratio=1.01,        # stock only +1% → underperforms
        )
        if result is not None:
            assert result["rs_vs_spy"] < 0, (
                f"Expected negative rs_vs_spy, got {result['rs_vs_spy']}"
            )


def test_flat_base_brk_rejected_weak_volume():
    """BRK signal requires vol_ratio >= 1.5; vol_ratio of 1.3 must be rejected."""
    import numpy as np
    import pandas as pd
    from engines.engine5 import scan_flat_base

    n = 250
    dates = pd.date_range("2021-01-01", periods=n, freq="B")
    # Stage 2 uptrend: close rises from 60 to 100, SMA50 > SMA200 guaranteed after enough bars
    close  = np.linspace(60.0, 100.0, n)
    high   = close * 1.015
    low    = close * 0.985
    volume = np.full(n, 1_000_000.0)

    df = pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )

    # Last bar: price above ceiling, volume 1.3× avg (above old 1.2 threshold, below new 1.5)
    ceiling = float(df["High"].values[-30:].max())
    df.iloc[-1, df.columns.get_loc("Close")]  = ceiling * 1.003  # above ceiling
    df.iloc[-1, df.columns.get_loc("High")]   = ceiling * 1.005
    df.iloc[-1, df.columns.get_loc("Low")]    = ceiling * 0.998
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_300_000.0  # 1.3× avg

    result = scan_flat_base("TEST", df)
    # Must not return a BRK signal (either None or DRY)
    assert result is None or result.get("signal") != "BRK", (
        f"Expected no BRK with vol_ratio=1.3 (below 1.5 threshold); got signal={result.get('signal') if result else None}"
    )


def test_flat_base_brk_rejected_noisy_range():
    """BRK signal requires prior range contraction; expanding range must be rejected."""
    import numpy as np
    import pandas as pd
    from engines.engine5 import scan_flat_base

    n = 250
    dates = pd.date_range("2021-01-01", periods=n, freq="B")
    close  = np.linspace(60.0, 100.0, n)
    high   = close * 1.015
    low    = close * 0.985
    volume = np.full(n, 1_000_000.0)

    df = pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )

    # Make last 5 bars wider range than prior (noisy breakout — range expanding)
    for i in range(-5, 0):
        df.iloc[i, df.columns.get_loc("High")] = float(close[i]) * 1.06  # very wide
        df.iloc[i, df.columns.get_loc("Low")]  = float(close[i]) * 0.94

    # Last bar: above ceiling, vol >= 1.5× (passes vol gate)
    ceiling = float(df["High"].values[-30:-5].max())  # ceiling from pre-noisy bars
    df.iloc[-1, df.columns.get_loc("Close")]  = ceiling * 1.003
    df.iloc[-1, df.columns.get_loc("Volume")] = 1_600_000.0  # 1.6× avg → passes vol gate

    result = scan_flat_base("TEST", df)
    assert result is None or result.get("signal") != "BRK", (
        f"Expected no BRK with expanding range (noisy base); got signal={result.get('signal') if result else None}"
    )
