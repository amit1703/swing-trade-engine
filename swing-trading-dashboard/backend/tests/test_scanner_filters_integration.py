"""Verify scanner's earnings check delegates to filters.in_earnings_blackout."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_scanner_earnings_blackout_uses_filters_module():
    """filters.in_earnings_blackout works correctly for scanner use cases."""
    import filters
    # Within 7 days → blocked
    assert filters.in_earnings_blackout("2024-01-10", ["2024-01-15"]) is True
    # More than 7 days → not blocked
    assert filters.in_earnings_blackout("2024-01-10", ["2024-02-01"]) is False
    # Day before earnings → still blocked
    assert filters.in_earnings_blackout("2024-01-10", ["2024-01-09"]) is True
    # Empty list → not blocked
    assert filters.in_earnings_blackout("2024-01-10", []) is False


# ── Integration: new scan state timing fields ─────────────────────────────────
def test_scan_state_has_new_timing_fields():
    import main as m
    state = m._scan_state
    timing = state["engine_stats"]["timing"]
    for field in ("pass1_filter_s", "fetch_s", "rs_cache_s", "pass2_s"):
        assert field in timing, f"missing timing field: {field}"

def test_scan_state_has_pass1_survivors():
    import main as m
    state = m._scan_state
    assert "pass1_survivors" in state["engine_stats"]

def test_cache_store_module_level_singleton_exists():
    import main as m
    assert hasattr(m, "_cache_store")
    from cache_store import CacheStore
    assert isinstance(m._cache_store, CacheStore)
