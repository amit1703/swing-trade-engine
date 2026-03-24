import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest

def test_new_constants_exist():
    from constants import (
        SCAN_CACHE_DIR,
        PRICE_CACHE_FRESH_DAYS,
        PRICE_CACHE_MAX_STALE_DAYS,
        SCAN_CACHE_METADATA_FILE,
        RS_RANK_CACHE_TTL,
        RS_RANK_CACHE_FILE,
        RS_RANK_CACHE_REFRESH_THRESHOLD,
        PASS1_MIN_PRICE,
        PASS1_MIN_AVG_VOLUME,
        PASS1_MIN_DOLLAR_VOLUME,
        PASS1_MIN_RS_RANK,
        PASS1_MAX_SURVIVORS,
        SCAN_IO_WORKERS,
        SCAN_COMPUTE_WORKERS,
        SCAN_QUEUE_MULTIPLIER,
        UNIVERSE_MIN_PRICE,
        UNIVERSE_MIN_AVG_VOLUME,
        UNIVERSE_MIN_DOLLAR_VOL,
        UNIVERSE_RS_FLOOR,
    )
    assert SCAN_CACHE_DIR == "data/scan_cache"
    assert PRICE_CACHE_FRESH_DAYS == 2
    assert PRICE_CACHE_MAX_STALE_DAYS == 5
    assert RS_RANK_CACHE_TTL == 86400
    assert RS_RANK_CACHE_REFRESH_THRESHOLD == 72000
    assert PASS1_MIN_PRICE == 12.0
    assert PASS1_MIN_AVG_VOLUME == 1_000_000
    assert PASS1_MIN_DOLLAR_VOLUME == 25_000_000
    assert PASS1_MIN_RS_RANK == 45
    assert PASS1_MAX_SURVIVORS == 400
    assert SCAN_IO_WORKERS == 48
    assert SCAN_COMPUTE_WORKERS == 32
    assert SCAN_QUEUE_MULTIPLIER == 2
    assert UNIVERSE_MIN_PRICE == 12.0
    assert UNIVERSE_MIN_AVG_VOLUME == 1_000_000
    assert UNIVERSE_MIN_DOLLAR_VOL == 25_000_000
    assert UNIVERSE_RS_FLOOR == 35
