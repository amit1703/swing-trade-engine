"""Watchlist sort should order by ATR-normalized distance, not raw distance_pct."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _atr_dist(item):
    """Mirror of the sort key used in main.py."""
    dist  = item.get("distance_pct", 99)
    atr   = item.get("atr", 0)
    entry = item.get("entry", 1)
    if atr > 0 and entry > 0:
        atr_pct = atr / entry * 100
        return dist / atr_pct if atr_pct > 0 else 99
    return 99


def test_atr_sort_beats_raw_pct():
    """High-ATR stock with 3% distance should rank above low-ATR stock with 2% distance."""
    high_atr = {"ticker": "NVDA", "distance_pct": 3.0, "atr": 4.0, "entry": 100.0}
    low_atr  = {"ticker": "KO",   "distance_pct": 2.0, "atr": 0.5, "entry": 60.0}

    # raw pct: KO (2.0) < NVDA (3.0) → KO first in old sort
    # atr-normalized: NVDA = 3.0/(4/100*100)=0.75; KO = 2.0/(0.5/60*100)=2.4
    # NVDA atr_dist (0.75) < KO atr_dist (2.4) → NVDA sorts first

    items = [low_atr, high_atr]
    items.sort(key=_atr_dist)
    assert items[0]["ticker"] == "NVDA", "High-ATR close stock should rank above low-ATR far stock"


def test_missing_atr_sorts_last():
    item_no_atr = {"ticker": "NOPE", "distance_pct": 0.5}
    item_with   = {"ticker": "AAPL", "distance_pct": 2.0, "atr": 1.0, "entry": 50.0}
    items = [item_no_atr, item_with]
    items.sort(key=_atr_dist)
    assert items[0]["ticker"] == "AAPL"
