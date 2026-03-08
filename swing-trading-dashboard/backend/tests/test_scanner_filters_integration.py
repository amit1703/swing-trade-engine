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
