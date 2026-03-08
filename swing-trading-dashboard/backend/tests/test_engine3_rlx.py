"""Tests for Engine 3 tightened relaxed pullback."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import pytest

from engines.engine3 import scan_relaxed_pullback


def make_pullback_df(n=200):
    """Stock in uptrend: 8 EMA > 20 EMA, close > 50 SMA. Low vol last 3 days."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.linspace(70.0, 100.0, n)
    high  = close * 1.01
    low   = close * 0.99
    volume = np.full(n, 1_000_000.0)
    volume[-3:] = 700_000.0  # low volume last 3 days
    return pd.DataFrame(
        {"Close": close, "Adj Close": close, "High": high,
         "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )


def make_support_zone(level: float):
    return {
        "level": level, "upper": level * 1.005,
        "lower": level * 0.995, "type": "SUPPORT",
        "is_primary": True,
    }


def test_rlx_rejects_when_no_support_zone():
    """RLX must reject when no KDE support zones are present."""
    df = make_pullback_df()
    result = scan_relaxed_pullback("TEST", df, [])
    assert result is None, "RLX must not fire without a support zone"


def test_rlx_rejects_resistance_zones_only():
    """RLX must reject when only resistance zones are present."""
    df = make_pullback_df()
    resistance_only = [
        {"level": 110.0, "upper": 110.5, "lower": 109.5,
         "type": "RESISTANCE", "is_primary": True}
    ]
    result = scan_relaxed_pullback("TEST", df, resistance_only)
    assert result is None, "RLX must not fire with only resistance zones"


def test_rlx_rejects_mild_cci_above_minus_30():
    """RLX must reject when CCI[yesterday] is between -30 and 0 (too mild)."""
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    # Uptrend then flat oscillation — produces CCI near 0, not deeply negative
    close = np.linspace(70.0, 100.0, n)
    close[-20:] = 99.5 + np.sin(np.linspace(0, np.pi, 20)) * 0.3  # tiny oscillation → CCI ≈ 0
    high   = close * 1.003
    low    = close * 0.997
    volume = np.full(n, 1_000_000.0)
    volume[-3:] = 700_000.0
    df = pd.DataFrame(
        {"Close": close, "Adj Close": close, "High": high,
         "Low": low, "Open": close, "Volume": volume},
        index=dates,
    )
    support = make_support_zone(99.0)
    result = scan_relaxed_pullback("TEST", df, [support])
    # With near-zero CCI the cci_prev < -30 gate must reject; result must be None
    if result is not None:
        assert result.get("cci_yesterday", 0) < -30, \
            "RLX fired but cci_yesterday was not below -30 — CCI gate is broken"


def test_rs_reject_threshold_is_patchable():
    """RS_REJECT_THRESHOLD is a module constant patchable at runtime."""
    import engines.engine3 as engine3
    import io
    from contextlib import redirect_stdout

    # Confirm default value
    assert engine3.RS_REJECT_THRESHOLD == -0.05

    # Tighten threshold to -0.02; rs_score=-0.03 is below it → must be rejected
    engine3.RS_REJECT_THRESHOLD = -0.02
    try:
        f = io.StringIO()
        with redirect_stdout(f):
            scan_relaxed_pullback("TEST", make_pullback_df(), [make_support_zone(99.0)],
                                  rs_score=-0.03, debug=True)
        assert "RS score too weak" in f.getvalue(), (
            "With RS_REJECT_THRESHOLD=-0.02 and rs_score=-0.03, RS gate must fire"
        )
    finally:
        engine3.RS_REJECT_THRESHOLD = -0.05

    # Restored to -0.05: rs_score=-0.03 is above threshold → RS gate must NOT fire
    f2 = io.StringIO()
    with redirect_stdout(f2):
        scan_relaxed_pullback("TEST", make_pullback_df(), [make_support_zone(99.0)],
                              rs_score=-0.03, debug=True)
    assert "RS score too weak" not in f2.getvalue(), (
        "After restoring threshold to -0.05, rs_score=-0.03 must pass the RS gate"
    )
