import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from constants import (
    LIQUIDITY_MIN_AVG_VOLUME,
    LIQUIDITY_MIN_DOLLAR_VOLUME,
    TOP_SECTORS_N,
    UNIVERSE_MAX_AGE_DAYS,
    UNIVERSE_WARN_AGE_DAYS,
    UNIVERSE_MIN_SIZE,
    UNIVERSE_MAX_SIZE,
    RS_TIER1_THRESHOLD,
    RS_TIER1_MULTIPLIER,
    SECTOR_TIER1_N,
    SECTOR_TIER2_FACTOR,
    SECTOR_OUT_OF_TOP_FACTOR,
    DISCOVERY_RS_MIN,
    DISCOVERY_RS_MAX,
    DISCOVERY_52WK_HIGH_PCT,
    DISCOVERY_VOL_RATIO,
    DISCOVERY_MAX_PCT,
)


def test_liquidity_constants_tightened():
    assert LIQUIDITY_MIN_AVG_VOLUME == 750_000
    assert LIQUIDITY_MIN_DOLLAR_VOLUME == 25_000_000


def test_universe_age_size_constants():
    assert UNIVERSE_MAX_AGE_DAYS == 7
    assert UNIVERSE_WARN_AGE_DAYS == 5
    assert UNIVERSE_MIN_SIZE == 800
    assert UNIVERSE_MAX_SIZE == 2_500
    assert UNIVERSE_WARN_AGE_DAYS < UNIVERSE_MAX_AGE_DAYS  # warn fires before hard cutoff


def test_rs_tier_constants():
    assert RS_TIER1_THRESHOLD == 85
    assert RS_TIER1_MULTIPLIER == 1.15
    assert TOP_SECTORS_N == 8          # raised from 5
    assert SECTOR_TIER1_N == 5         # top 5 of 8 get full points
    assert SECTOR_TIER2_FACTOR == 0.8
    assert SECTOR_OUT_OF_TOP_FACTOR == 0.4
    assert SECTOR_TIER1_N < TOP_SECTORS_N  # ensures tier 2 is non-empty


def test_discovery_constants():
    assert DISCOVERY_RS_MIN == 60
    assert DISCOVERY_RS_MAX == 70
    assert DISCOVERY_52WK_HIGH_PCT == 0.03
    assert DISCOVERY_VOL_RATIO == 1.5
    assert DISCOVERY_MAX_PCT == 0.10
    assert DISCOVERY_RS_MIN < DISCOVERY_RS_MAX  # valid range
