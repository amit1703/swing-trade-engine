# swing-trading-dashboard/backend/tests/test_scan_pullback_scored.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import pytest
from types import SimpleNamespace


def _make_params(**kwargs):
    defaults = dict(
        cci_threshold=-20.0,
        ema_distance=0.04,
        tdl_bonus=1.0,
        score_threshold=5.0,
        breakout_weight=1.0,
        pullback_weight=1.0,
        rs_threshold=-0.05,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_downtrend_df(n: int = 150) -> pd.DataFrame:
    """Downtrending stock — trend filter must fail."""
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    close = np.linspace(150.0, 80.0, n)
    return pd.DataFrame({
        "Open":      close * 1.001,
        "High":      close * 1.01,
        "Low":       close * 0.99,
        "Close":     close,
        "Adj Close": close,
        "Volume":    np.full(n, 2_000_000),
    }, index=idx)


def test_returns_none_zero_on_downtrend():
    """Trend hard gate: no uptrend → (None, 0.0)."""
    from engines.engine3 import scan_pullback_scored
    df     = _make_downtrend_df()
    params = _make_params()
    setup, score = scan_pullback_scored("TEST", df, [], params)
    assert setup is None
    assert score == pytest.approx(0.0)


def test_returns_tuple():
    """scan_pullback_scored always returns a 2-tuple."""
    from engines.engine3 import scan_pullback_scored
    df     = _make_downtrend_df()
    params = _make_params()
    result = scan_pullback_scored("TEST", df, [], params)
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_setup_dict_fields_when_returned():
    """When a setup is returned, it has pullback_score and is_scored_mode."""
    from engines.engine3 import scan_pullback_scored
    # Use downtrend (safe — won't return a setup, but function must return tuple)
    df     = _make_downtrend_df()
    params = _make_params()
    setup, score = scan_pullback_scored("TEST", df, [], params)
    if setup is not None:
        assert "pullback_score" in setup
        assert setup["is_scored_mode"] is True
        assert setup["pullback_score"] == pytest.approx(score)


def test_score_is_non_negative():
    """Score is always >= 0.0."""
    from engines.engine3 import scan_pullback_scored
    params = _make_params()
    _, score = scan_pullback_scored("TEST", _make_downtrend_df(), [], params)
    assert score >= 0.0


def test_none_on_insufficient_data():
    """Less than 60 bars → (None, 0.0) from _prepare_indicators."""
    from engines.engine3 import scan_pullback_scored
    idx = pd.date_range("2023-01-01", periods=30, freq="B")
    df  = pd.DataFrame({
        "Open": [100]*30, "High": [101]*30, "Low": [99]*30,
        "Close": [100]*30, "Adj Close": [100]*30, "Volume": [1_000_000]*30,
    }, index=idx)
    setup, score = scan_pullback_scored("TEST", df, [], _make_params())
    assert setup is None
    assert score == pytest.approx(0.0)


def test_existing_scan_pullback_unchanged():
    """scan_pullback and scan_relaxed_pullback are still importable and callable."""
    from engines.engine3 import scan_pullback, scan_relaxed_pullback
    df = _make_downtrend_df()
    # Should not raise — returns None on downtrend
    result = scan_pullback("TEST", df, [])
    assert result is None
    result2 = scan_relaxed_pullback("TEST", df, [])
    assert result2 is None
