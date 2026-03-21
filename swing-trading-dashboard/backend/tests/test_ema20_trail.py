import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_meta_keys_include_support_level():
    """support_level must be captured from signal into _setup_meta."""
    from backtest_engine import _BACKTEST_META_KEYS
    assert "support_level" in _BACKTEST_META_KEYS

def test_meta_keys_include_geometry():
    """geometry must be captured for BASE base_high lookup."""
    from backtest_engine import _BACKTEST_META_KEYS
    assert "geometry" in _BACKTEST_META_KEYS


def test_extract_ref_level_res_breakout():
    from backtest_engine import _extract_ref_level
    meta = {"resistance_level": 150.0, "zone_upper": 150.0}
    assert _extract_ref_level(meta, "RES_BREAKOUT") == 150.0


def test_extract_ref_level_vcp():
    from backtest_engine import _extract_ref_level
    meta = {"resistance_level": 200.0}
    assert _extract_ref_level(meta, "VCP") == 200.0


def test_extract_ref_level_pullback():
    from backtest_engine import _extract_ref_level
    meta = {"support_level": 95.0, "support_source": "KDE_SUPPORT"}
    assert _extract_ref_level(meta, "PULLBACK") == 95.0


def test_extract_ref_level_base():
    from backtest_engine import _extract_ref_level
    meta = {"geometry": {"base_high": 180.0, "base_low": 160.0}}
    assert _extract_ref_level(meta, "BASE") == 180.0


def test_extract_ref_level_htf_returns_none():
    """HTF has no reference level — returns None to trigger EMA20 from day 1."""
    from backtest_engine import _extract_ref_level
    meta = {"volume_ratio": 1.5}
    assert _extract_ref_level(meta, "HTF") is None


def test_extract_ref_level_missing_key_returns_none():
    """Graceful fallback when setup_meta doesn't have the expected key."""
    from backtest_engine import _extract_ref_level
    assert _extract_ref_level({}, "PULLBACK") is None
    assert _extract_ref_level({}, "VCP") is None
