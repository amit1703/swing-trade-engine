"""Tests for services/narrative.py — run with: pytest backend/tests/test_narrative.py -v"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "services"))

from narrative import generate_narrative


def _vcp_setup(extra=None):
    base = {"ticker": "NVDA", "setup_type": "VCP", "entry": 800.0, "stop_loss": 780.0, "take_profit": 840.0}
    if extra:
        base.update(extra)
    return base


def test_narrative_returns_string():
    """generate_narrative always returns a non-empty string."""
    result = generate_narrative(_vcp_setup(), "BULLISH")
    assert isinstance(result, str)
    assert len(result) > 20


def test_narrative_includes_ticker():
    """Narrative contains the ticker symbol."""
    result = generate_narrative(_vcp_setup(), "BULLISH")
    assert "NVDA" in result


def test_narrative_includes_entry_price():
    """Narrative mentions the entry price."""
    result = generate_narrative(_vcp_setup(), "BULLISH")
    assert "800.00" in result


def test_narrative_includes_stop():
    """Narrative mentions the stop price."""
    result = generate_narrative(_vcp_setup(), "BULLISH")
    assert "780.00" in result


def test_narrative_bearish_regime():
    """Bearish regime warning appears in narrative."""
    result = generate_narrative(_vcp_setup(), "BEARISH")
    assert "downtrend" in result.lower() or "caution" in result.lower() or "bearish" in result.lower()


def test_narrative_vcp_breakout():
    """BRK VCP narrative mentions breakout."""
    result = generate_narrative(_vcp_setup({"is_breakout": True, "volume_ratio": 2.3}), "BULLISH")
    assert "break" in result.lower() or "breakout" in result.lower()


def test_narrative_pullback():
    """PULLBACK narrative mentions EMA support."""
    setup = {"ticker": "AAPL", "setup_type": "PULLBACK", "entry": 175.0, "stop_loss": 170.0,
             "take_profit": 185.0, "cci_today": -110.0}
    result = generate_narrative(setup, "BULLISH")
    assert "AAPL" in result
    assert "pullback" in result.lower() or "ema" in result.lower()


def test_narrative_base_cup_handle():
    """BASE C&H narrative mentions cup."""
    setup = {"ticker": "TSLA", "setup_type": "BASE", "entry": 250.0, "stop_loss": 238.0,
             "take_profit": 274.0, "base_type": "CUP_HANDLE", "signal": "BRK", "quality_score": 72}
    result = generate_narrative(setup, "BULLISH")
    assert "Cup" in result or "cup" in result.lower()


def test_narrative_never_raises():
    """generate_narrative never raises even with empty/null input."""
    result = generate_narrative({}, "BULLISH")
    assert isinstance(result, str)
    assert len(result) > 0


def test_narrative_res_breakout_today():
    """RES_BREAKOUT today narrative says 'today'."""
    setup = {"ticker": "AMD", "setup_type": "RES_BREAKOUT", "entry": 120.0, "stop_loss": 115.0,
             "take_profit": 130.0, "days_since_breakout": 0, "volume_ratio": 2.1}
    result = generate_narrative(setup, "BULLISH")
    assert "today" in result.lower() or "breaking" in result.lower()
