"""Tests for _rs_quality_component scoring — pytest backend/tests/test_scoring_rs_quality.py -v"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from scoring import _rs_quality_component


def _setup(**kwargs):
    base = {
        "setup_type": "VCP",
        "rs_vs_spy": 0.0,
        "rs_score": 0.0,
        "rs_improving": False,
        "rs_near_high": False,
        "rs_acceleration": 0.0,
        "tight_range_5d": False,
    }
    base.update(kwargs)
    return base


def test_zero_score_when_all_signals_absent():
    assert _rs_quality_component(_setup()) == 0.0


def test_rs_vs_spy_positive_adds_points():
    pts = _rs_quality_component(_setup(rs_vs_spy=0.02))
    assert pts > 0


def test_rs_vs_spy_above_threshold_adds_more_points():
    pts_low  = _rs_quality_component(_setup(rs_vs_spy=0.02))
    pts_high = _rs_quality_component(_setup(rs_vs_spy=0.06))
    assert pts_high > pts_low


def test_rs_improving_adds_points():
    pts = _rs_quality_component(_setup(rs_improving=True))
    assert pts > 0


def test_rs_near_high_adds_points():
    pts = _rs_quality_component(_setup(rs_near_high=True))
    assert pts > 0


def test_rs_acceleration_low_threshold():
    pts = _rs_quality_component(_setup(rs_acceleration=0.06))
    assert pts > 0


def test_rs_acceleration_high_threshold_more_points():
    pts_low  = _rs_quality_component(_setup(rs_acceleration=0.06))
    pts_high = _rs_quality_component(_setup(rs_acceleration=0.12))
    assert pts_high > pts_low


def test_tight_range_adds_points():
    pts = _rs_quality_component(_setup(tight_range_5d=True))
    assert pts > 0


def test_all_signals_capped_at_max_weight():
    from constants import SCORE_WEIGHT_RS_QUALITY
    pts = _rs_quality_component(_setup(
        rs_vs_spy=0.10, rs_improving=True, rs_near_high=True,
        rs_acceleration=0.15, tight_range_5d=True
    ))
    assert pts <= float(SCORE_WEIGHT_RS_QUALITY)


def test_negative_rs_vs_spy_contributes_zero():
    pts = _rs_quality_component(_setup(rs_vs_spy=-0.05))
    assert pts == 0.0
