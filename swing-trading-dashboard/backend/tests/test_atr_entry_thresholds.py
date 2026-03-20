"""Tests that ATR entry quality constants exist and are ordered correctly."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_constants_exist():
    from constants import ATR_ENTRY_EARLY_THRESHOLD, ATR_ENTRY_EXTENDED_THRESHOLD
    assert isinstance(ATR_ENTRY_EARLY_THRESHOLD, (int, float))
    assert isinstance(ATR_ENTRY_EXTENDED_THRESHOLD, (int, float))

def test_constants_ordered():
    from constants import ATR_ENTRY_EARLY_THRESHOLD, ATR_ENTRY_EXTENDED_THRESHOLD
    assert ATR_ENTRY_EARLY_THRESHOLD < ATR_ENTRY_EXTENDED_THRESHOLD
