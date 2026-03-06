"""Tests for engine4.get_rs_signals() — run with: pytest backend/tests/test_rs_signals.py -v"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engines.engine4 import get_rs_signals


def _flat_line(n=100, value=1.0):
    return [value] * n


def test_rs_improving_true_when_trending_up():
    rs_line = list(range(1, 101))   # rs[-1]=100 > rs[-10]=91 → improving
    result = get_rs_signals(rs_line)
    assert result["rs_improving"] is True


def test_rs_improving_false_when_flat():
    result = get_rs_signals(_flat_line())
    assert result["rs_improving"] is False


def test_rs_improving_false_when_declining():
    rs_line = list(range(100, 0, -1))  # rs[-1]=1 < rs[-10]=10
    result = get_rs_signals(rs_line)
    assert result["rs_improving"] is False


def test_rs_near_high_true_when_at_peak():
    rs_line = [1.0] * 59 + [1.5]   # last value = max = near high
    result = get_rs_signals(rs_line)
    assert result["rs_near_high"] is True


def test_rs_near_high_false_when_far_from_peak():
    rs_line = [1.5] * 59 + [1.0]   # current 1.0 < 0.9 * 1.5 = 1.35
    result = get_rs_signals(rs_line)
    assert result["rs_near_high"] is False


def test_rs_acceleration_positive_on_strong_rise():
    # rs[-10]=1.0, rs[-1]=1.15 → accel = (1.15-1.0)/1.0 = 0.15 > 0.10
    rs_line = [1.0] * 90 + [1.0] * 9 + [1.15]
    result = get_rs_signals(rs_line)
    assert result["rs_acceleration"] > 0.10


def test_rs_acceleration_negative_on_decline():
    rs_line = [1.1] * 90 + [1.1] * 9 + [1.0]
    result = get_rs_signals(rs_line)
    assert result["rs_acceleration"] < 0


def test_short_line_returns_safe_defaults():
    result = get_rs_signals([1.0, 1.1])   # too short for 10-bar lookback
    assert result["rs_improving"] is False
    assert result["rs_near_high"] is False
    assert result["rs_acceleration"] == 0.0


def test_empty_line_returns_safe_defaults():
    result = get_rs_signals([])
    assert result["rs_improving"] is False
    assert result["rs_near_high"] is False
    assert result["rs_acceleration"] == 0.0
