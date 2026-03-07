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
    """Path B (confirmed KDE breakout) falls through if contraction_count < 2."""
    import pandas as pd
    import numpy as np
    from engines.engine2 import scan_vcp

    n = 200
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    # Steady uptrend — EMA8>EMA20, close>SMA50, close>SMA200
    close  = np.linspace(70.0, 100.5, n)
    high   = close * 1.005
    low    = close * 0.995
    # Perfectly flat volume — uniform TR → no contractions
    volume = np.full(n, 2_000_000.0)
    df = pd.DataFrame({"Close": close, "High": high, "Low": low,
                       "Open": close, "Volume": volume}, index=dates)

    # Put a resistance zone just below current close so Path B sees a cleared zone
    resistance = 99.8
    zones = [{"level": resistance, "upper": resistance + 0.1,
               "lower": resistance - 0.1, "type": "RESISTANCE"}]

    # With flat TR, _count_contractions returns contraction_count=0 → Path B blocked
    result = scan_vcp("TEST", df, sr_zones=zones)
    # Path B should be blocked; result is either None or not a fresh B breakout
    # (it may fall through to Path A and fail on SMA200/ATR/U-shape checks too)
    # The key assertion: we should not get a clean confirmed-breakout result
    if result is not None:
        # If any path fired, it must NOT be a clean vol-surge breakout without contractions
        assert result.get("contraction_count", 0) >= 2 or not result.get("is_vol_surge", False), \
            f"Path B fired without contractions: {result}"


def test_path_a_requires_progressive_contractions():
    """Path A (DRY) must not fire if is_progressive=False even with 3 contractions."""
    import pandas as pd
    import numpy as np
    from engines.engine2 import scan_vcp

    n = 200
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    # Uptrend well above 200 SMA
    close  = np.linspace(70.0, 98.0, n)
    high   = close.copy()
    low    = close.copy()
    volume = np.full(n, 1_000_000.0)

    # Last 5 bars: alternating wide/narrow ranges (not progressive — not tighter each time)
    ranges = [2.0, 0.5, 1.5, 0.4, 0.8]  # oscillates, not monotonically decreasing
    for i, r in enumerate(ranges):
        idx = n - 5 + i
        high[idx]   = close[idx] + r / 2
        low[idx]    = close[idx] - r / 2
        volume[idx] = 100_000.0   # dry-up vol

    df = pd.DataFrame({"Close": close, "High": high, "Low": low,
                       "Open": close, "Volume": volume}, index=dates)

    resistance = 100.0
    zones = [{"level": resistance, "upper": resistance * 1.005,
               "lower": resistance * 0.995, "type": "RESISTANCE"}]

    result = scan_vcp("TEST", df, sr_zones=zones)
    # Path A should be blocked due to non-progressive contractions
    # Other paths (B/C/D) also won't fire — no vol surge, no KDE breakout
    if result is not None:
        assert not result.get("is_progressive_tightening", True), \
            f"Path A fired with non-progressive contractions: {result}"
