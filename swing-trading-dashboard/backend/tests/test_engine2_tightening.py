import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pandas as pd
from engines.engine2 import _count_contractions


def test_equal_tr_values_not_progressive():
    """Equal TR values must NOT count as progressively tighter."""
    # Three contractions with equal TR — should NOT be progressive
    tr = pd.Series([2.0] * 25 + [1.0, 1.0, 1.0, 0.5, 0.5])
    count, pattern, is_progressive = _count_contractions(tr, lookback=25)
    assert count >= 3
    assert is_progressive is False, "Equal TR values should not be progressive"


def test_strictly_decreasing_tr_is_progressive():
    """Strictly decreasing TR values must be progressive."""
    tr = pd.Series([2.0] * 25 + [1.0, 0.9, 0.8, 0.7, 0.6])
    count, pattern, is_progressive = _count_contractions(tr, lookback=25)
    assert count >= 3
    assert is_progressive is True


def test_path_b_requires_min_contractions():
    """Path B blocked when contraction_count < 2, even with valid zone + vol surge."""
    import pandas as pd
    import numpy as np
    from engines.engine2 import scan_vcp

    n = 250
    dates = pd.date_range("2022-01-01", periods=n, freq="B")

    # Build a clean uptrend: EMA8 > EMA20, close > SMA50, close > SMA200
    close  = np.linspace(50.0, 102.0, n)   # gradual rise above all MAs
    # Absolutely flat high-low bands → TR is uniform → contraction_count = 0
    high   = close + 0.50   # fixed $0.50 range throughout — no contraction ever
    low    = close - 0.50
    volume = np.full(n, 500_000.0)

    # Last bar: big vol surge (is_vol_surge = True)
    volume[-1] = 2_000_000.0   # 4× avg → well above 1.5× threshold

    df = pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )

    # Resistance zone whose UPPER is just below the last close → Path B sees a cleared zone
    resistance_upper = 101.6
    zones = [{
        "level":  101.5,
        "upper":  resistance_upper,
        "lower":  101.0,
        "type":   "RESISTANCE",
    }]
    # last close = ~102.0, so pct_above_upper = (102.0 - 101.6) / 101.6 ≈ 0.39% → 0.003<= x <=0.03 ✓

    result = scan_vcp("TEST", df, sr_zones=zones)
    # With contraction_count=0 the gate blocks Path B.
    # Paths C/D also require vol/zone conditions that may or may not fire,
    # but Path A requires close>SMA200 AND ATR compressed AND U-shape AND vol dry-up
    # which won't all pass here (volume is high, not dry). So result should be None.
    assert result is None, (
        f"Expected None when contraction_count=0 (no structural coil); got {result}"
    )


def test_path_a_requires_progressive_contractions():
    """Path A blocked when contractions exist but are not progressive (oscillating)."""
    import pandas as pd
    import numpy as np
    from engines.engine2 import scan_vcp

    n = 252
    dates = pd.date_range("2021-01-01", periods=n, freq="B")

    # Rising trend throughout — ensures EMA8>EMA20, close>SMA50, close>SMA200
    close_base = np.linspace(60.0, 96.0, n)
    high  = close_base.copy()
    low   = close_base.copy()
    volume = np.full(n, 1_000_000.0)

    # Bars -25 to -6: moderate TR to establish prev20_tr baseline
    for i in range(-25, -5):
        high[i]  = close_base[i] + 1.2
        low[i]   = close_base[i] - 1.2
        volume[i] = 800_000.0

    # Bars -5 to -1: oscillating ranges — below baseline (passes TR contraction)
    # but NOT monotonically decreasing → is_progressive = False
    # Pattern: narrow, wide, narrow, wide, narrow (oscillates)
    osc_ranges = [0.4, 0.9, 0.3, 0.8, 0.25]
    for j, r in enumerate(osc_ranges):
        idx = n - 5 + j
        high[idx]   = close_base[idx] + r
        low[idx]    = close_base[idx] - r
        volume[idx] = 150_000.0   # dry-up

    df = pd.DataFrame(
        {"Close": close_base, "High": high, "Low": low, "Open": close_base, "Volume": volume},
        index=dates,
    )

    # Resistance zone 3-5% above current price (proximity for Path A)
    current_price = float(close_base[-1])  # ~96
    resistance = current_price * 1.03
    zones = [{
        "level":  resistance,
        "upper":  resistance * 1.005,
        "lower":  resistance * 0.995,
        "type":   "RESISTANCE",
    }]

    result = scan_vcp("TEST", df, sr_zones=zones)
    # Oscillating ranges → is_progressive=False → Path A gate blocks.
    # Paths B/C/D also shouldn't fire (no vol surge, no cleared zone, no trendline breakout).
    assert result is None, (
        f"Expected None when contractions are non-progressive (oscillating); got {result}"
    )
