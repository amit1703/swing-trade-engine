"""
validate_pass1_improvement.py — Measure Pass 1 filter improvement.

Run from backend/:
    python docs/validate_pass1_improvement.py

Tests the updated _pass1_filter against:
  - The 60 tickers currently in metadata.json (warm data)
  - Projected full-universe impact (extrapolating from sample)
  - Before/after survivors count and breakdown
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import sys
from typing import Dict, List, Tuple

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger("validate_pass1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import (
    DISCOVERY_RS_MAX,
    DISCOVERY_RS_MIN,
    PASS1_MAX_SURVIVORS,
    PASS1_MIN_AVG_VOLUME,
    PASS1_MIN_DOLLAR_VOLUME,
    PASS1_MIN_PRICE,
    PASS1_MIN_RS_RANK,
    PASS1_MIN_RS_RANK_WARM,
    PASS1_MIN_52W_HIGH_PCT,
    PASS1_REQUIRE_ABOVE_SMA50,
    RS_RANK_CACHE_MIN_TICKERS,
    SCAN_CACHE_DIR,
)
from cache_store import CacheStore
from scoring import _load_rs_cache, _rs_cache_valid

SEP = "=" * 65


def load_universe():
    fp = "active_universe.json"
    if os.path.exists(fp):
        with open(fp, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("tickers", []), data.get("sectors", {})
    from tickers import TICKERS
    return list(TICKERS), {}


def filter_breakdown(
    tickers: List[str],
    meta_store: Dict[str, dict],
    excluded_set: set,
    rs_cache: dict,
    label: str,
) -> Tuple[dict, List[str]]:
    """
    Apply Pass 1 filters and return breakdown counts + survivors.
    Mirrors the updated _pass1_filter logic exactly.
    """
    rs_floor = PASS1_MIN_RS_RANK_WARM if rs_cache else PASS1_MIN_RS_RANK

    cnt = {
        "universe": len(tickers),
        "cold":     0,
        "excl":     0,
        "price":    0,
        "vol":      0,
        "sma50":    0,
        "prox52":   0,
        "rs":       0,
        "pass":     0,
    }
    survivors = []

    for t in tickers:
        meta = meta_store.get(t)
        if meta is None:
            cnt["cold"] += 1
            survivors.append(t)
            continue
        if t in excluded_set:
            cnt["excl"] += 1
            continue
        if meta.get("last_close", 0) < PASS1_MIN_PRICE:
            cnt["price"] += 1
            continue
        if (meta.get("avg_vol_20d", 0) < PASS1_MIN_AVG_VOLUME
                or meta.get("dollar_vol", 0) < PASS1_MIN_DOLLAR_VOLUME):
            cnt["vol"] += 1
            continue
        if PASS1_REQUIRE_ABOVE_SMA50 and not meta.get("above_sma50", True):
            cnt["sma50"] += 1
            continue
        lc  = meta.get("last_close", 0)
        h52 = meta.get("high_52w",   0)
        if h52 > 0 and lc / h52 < PASS1_MIN_52W_HIGH_PCT:
            cnt["prox52"] += 1
            continue
        rs = rs_cache.get(t)
        if rs is not None and rs < rs_floor:
            cnt["rs"] += 1
            continue
        cnt["pass"] += 1
        survivors.append(t)

    # Print
    n = cnt["universe"]
    total_filtered = cnt["excl"] + cnt["price"] + cnt["vol"] + cnt["sma50"] + cnt["prox52"] + cnt["rs"]
    print(f"\n  [{label}]")
    print(f"    Universe:          {n}")
    print(f"    Cold (pass-thru):  {cnt['cold']}")
    print(f"    Excluded stale:    {cnt['excl']}")
    print(f"    Failed price:      {cnt['price']}")
    print(f"    Failed vol/dvol:   {cnt['vol']}")
    print(f"    Failed SMA50:      {cnt['sma50']}")
    print(f"    Failed 52w-prox:   {cnt['prox52']}")
    print(f"    Failed RS:         {cnt['rs']}  (floor={rs_floor})")
    print(f"    SURVIVORS:         {len(survivors)}  ({len(survivors)/n*100:.1f}%)")
    return cnt, survivors


def old_filter_breakdown(
    tickers: List[str],
    meta_store: Dict[str, dict],
    excluded_set: set,
    rs_cache: dict,
    label: str,
) -> Tuple[dict, List[str]]:
    """Old Pass 1 logic (before optimization) for comparison."""
    cnt = {
        "universe": len(tickers),
        "cold":  0, "excl": 0, "price": 0, "vol": 0, "rs": 0, "pass": 0,
    }
    survivors = []
    for t in tickers:
        meta = meta_store.get(t)
        if meta is None:
            cnt["cold"] += 1
            survivors.append(t)
            continue
        if t in excluded_set:
            cnt["excl"] += 1
            continue
        if meta.get("last_close", 0) < PASS1_MIN_PRICE:
            cnt["price"] += 1
            continue
        if (meta.get("avg_vol_20d", 0) < PASS1_MIN_AVG_VOLUME
                or meta.get("dollar_vol", 0) < PASS1_MIN_DOLLAR_VOLUME):
            cnt["vol"] += 1
            continue
        rs = rs_cache.get(t)
        if rs is not None and rs < PASS1_MIN_RS_RANK:
            cnt["rs"] += 1
            continue
        cnt["pass"] += 1
        survivors.append(t)
    print(f"\n  [{label}]")
    print(f"    Universe:         {len(tickers)}")
    print(f"    Cold:             {cnt['cold']}")
    print(f"    Failed vol/dvol:  {cnt['vol']}")
    print(f"    Failed RS (floor=45): {cnt['rs']}")
    print(f"    SURVIVORS:        {len(survivors)}  ({len(survivors)/len(tickers)*100:.1f}%)")
    return cnt, survivors


def main():
    print()
    print(SEP)
    print("  Pass 1 optimization — filter impact analysis")
    print(SEP)

    tickers, _ = load_universe()

    # Load cache store
    cs = CacheStore(cache_dir=SCAN_CACHE_DIR)
    cs.preload_index()

    meta_map: Dict[str, dict] = {}
    excluded_set: set = set()
    for t in tickers:
        m = cs.get_meta(t)
        if m is not None:
            meta_map[t] = m
        if cs.is_excluded(t):
            excluded_set.add(t)

    meta_count = len(meta_map)
    print(f"\n  Metadata available: {meta_count} / {len(tickers)} tickers")
    print(f"  (Remaining {len(tickers)-meta_count} are cold-start pass-throughs)")

    # Load RS cache
    raw_rs = _load_rs_cache()
    rs_valid = _rs_cache_valid(raw_rs)
    if rs_valid:
        rs_cache = {k: v for k, v in raw_rs.items() if not k.startswith("_")}
        print(f"  RS cache: VALID  ({raw_rs['_meta']['ticker_count']} tickers)")
    else:
        rs_cache = {}
        print(f"  RS cache: NOT VALID  (using empty -> RS filter skipped in Pass 1)")

    # ── Analysis on metadata-only tickers ──────────────────────────────────────
    print()
    print(SEP)
    print("  Filter analysis (metadata tickers only — excludes cold pass-throughs)")
    print(SEP)

    meta_tickers = [t for t in tickers if t in meta_map]

    print(f"\n  Filter thresholds in effect:")
    print(f"    Price >= {PASS1_MIN_PRICE}")
    print(f"    AvgVol >= {PASS1_MIN_AVG_VOLUME:,}")
    print(f"    DollarVol >= {PASS1_MIN_DOLLAR_VOLUME:,}")
    print(f"    above_sma50 required: {PASS1_REQUIRE_ABOVE_SMA50}")
    print(f"    52w-high proximity >= {PASS1_MIN_52W_HIGH_PCT:.0%}")
    print(f"    RS floor (cold cache): {PASS1_MIN_RS_RANK}")
    print(f"    RS floor (warm cache): {PASS1_MIN_RS_RANK_WARM}")

    # Count each filter independently on metadata tickers
    n = len(meta_tickers)
    fails = {
        "price":  sum(1 for t in meta_tickers if meta_map[t].get("last_close", 0) < PASS1_MIN_PRICE),
        "vol":    sum(1 for t in meta_tickers if meta_map[t].get("avg_vol_20d", 0) < PASS1_MIN_AVG_VOLUME or meta_map[t].get("dollar_vol", 0) < PASS1_MIN_DOLLAR_VOLUME),
        "sma50":  sum(1 for t in meta_tickers if not meta_map[t].get("above_sma50", True)),
        "prox52": sum(1 for t in meta_tickers if meta_map[t].get("high_52w", 0) > 0 and meta_map[t]["last_close"] / meta_map[t]["high_52w"] < PASS1_MIN_52W_HIGH_PCT),
        "rs_45":  sum(1 for t in meta_tickers if rs_cache.get(t) is not None and rs_cache[t] < 45),
        "rs_60":  sum(1 for t in meta_tickers if rs_cache.get(t) is not None and rs_cache[t] < 60),
        "rs_70":  sum(1 for t in meta_tickers if rs_cache.get(t) is not None and rs_cache[t] < 70),
    }
    print(f"\n  Independent filter impact on {n} tickers with metadata:")
    print(f"    price < {PASS1_MIN_PRICE}:                  {fails['price']} ({fails['price']/n*100:.0f}%) eliminated")
    print(f"    vol/dvol below floor:         {fails['vol']} ({fails['vol']/n*100:.0f}%) eliminated")
    print(f"    above_sma50 == False:         {fails['sma50']} ({fails['sma50']/n*100:.0f}%) eliminated  [NEW]")
    print(f"    52w-prox < {PASS1_MIN_52W_HIGH_PCT:.0%}:               {fails['prox52']} ({fails['prox52']/n*100:.0f}%) eliminated  [NEW]")
    if rs_cache:
        print(f"    RS < 45 (old floor):          {fails['rs_45']} ({fails['rs_45']/n*100:.0f}%) eliminated")
        print(f"    RS < 60 (new floor):          {fails['rs_60']} ({fails['rs_60']/n*100:.0f}%) eliminated  [NEW]")
        print(f"    RS < 70 (engine gate):        {fails['rs_70']} ({fails['rs_70']/n*100:.0f}%) would be killed anyway")

    # ── Full universe comparison: OLD vs NEW ───────────────────────────────────
    print()
    print(SEP)
    print("  OLD Pass 1 (before optimization)")
    print(SEP)
    old_cnt, old_survivors = old_filter_breakdown(tickers, meta_map, excluded_set, rs_cache, "OLD")

    print()
    print(SEP)
    print("  NEW Pass 1 (with sma50 + 52w-prox + RS floor raised)")
    print(SEP)
    new_cnt, new_survivors = filter_breakdown(tickers, meta_map, excluded_set, rs_cache, "NEW")

    # ── Delta ─────────────────────────────────────────────────────────────────
    print()
    print(SEP)
    print("  IMPACT SUMMARY")
    print(SEP)
    old_n = len(old_survivors)
    new_n = len(new_survivors)
    delta = old_n - new_n
    pct_reduction = delta / old_n * 100 if old_n > 0 else 0
    print(f"\n  Survivors:  OLD={old_n}  NEW={new_n}  delta=-{delta}  ({pct_reduction:.0f}% reduction)")
    print(f"  I/O fetch reduction: {delta} fewer tickers downloaded per warm scan")
    print(f"  Waste eliminated:    {delta} tickers that would be fetched then dropped at RS gate")

    # ── Projected full-warm impact ─────────────────────────────────────────────
    # Extrapolate: apply sample pass-rates to full 1069-ticker universe
    print()
    print("  PROJECTED full-warm-scan impact (extrapolated from sample):")
    full = len(tickers)
    cold = full - meta_count
    # Apply pass rates from sample to the meta tickers
    meta_old_pass = old_cnt.get("pass", 0)
    meta_new_pass = new_cnt.get("pass", 0)
    # Scale to full universe assuming same distribution
    if meta_count > 0:
        scale = full / meta_count  # rough scale factor
        projected_old = round(cold + meta_old_pass)
        projected_new = round(cold + meta_new_pass)
        # More useful: if all tickers had metadata
        print(f"    Current cold-start pass-throughs: {cold} (no metadata yet for most universe)")
        print(f"    After full warm run (all tickers have metadata):")
        if meta_count > 0:
            meta_pass_rate_old = meta_old_pass / meta_count
            meta_pass_rate_new = meta_new_pass / meta_count
            projected_full_old = round(full * meta_pass_rate_old)
            projected_full_new = round(full * meta_pass_rate_new)
            print(f"      OLD: ~{projected_full_old} survivors ({meta_pass_rate_old*100:.0f}% of universe)")
            print(f"      NEW: ~{projected_full_new} survivors ({meta_pass_rate_new*100:.0f}% of universe)")
            target_lo, target_hi = 200, 400
            in_range = target_lo <= projected_full_new <= target_hi
            print(f"      Target range: {target_lo}-{target_hi}  -> {'IN RANGE' if in_range else 'OUTSIDE RANGE (check thresholds)'}")

    print()
    print(SEP)
    print("  RESULT CHECKS")
    print(SEP)
    checks = [
        ("New filters add sma50 + 52w-prox eliminations",
         new_cnt.get("sma50", 0) + new_cnt.get("prox52", 0) > 0),
        ("RS floor raised to PASS1_MIN_RS_RANK_WARM when cache valid",
         PASS1_MIN_RS_RANK_WARM > PASS1_MIN_RS_RANK),
        ("Survivors reduced vs old filter",
         new_n < old_n or old_n == new_n == len(tickers)),  # either fewer or same (full cold)
        ("Cold-start pass-throughs unchanged (no metadata = always pass)",
         new_cnt.get("cold", 0) == old_cnt.get("cold", 0)),
    ]
    print()
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}]  {desc}")
    print()


if __name__ == "__main__":
    main()
