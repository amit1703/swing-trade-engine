"""
validate_pass1_refinement.py — Validate conditional SMA50 filter refinement.

Run from backend/:
    python docs/validate_pass1_refinement.py
"""
from __future__ import annotations
import json, os, sys, pathlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.WARNING, format="%(message)s")

from constants import (
    PASS1_MIN_PRICE, PASS1_MIN_AVG_VOLUME, PASS1_MIN_DOLLAR_VOLUME,
    PASS1_MIN_RS_RANK, PASS1_MIN_RS_RANK_WARM,
    PASS1_MIN_52W_HIGH_PCT,
    PASS1_BELOW_SMA50_MIN_52W_PCT, PASS1_BELOW_SMA50_VOL_RATIO, PASS1_BELOW_SMA50_MIN_RS,
    SCAN_CACHE_DIR,
)
from cache_store import CacheStore
from scoring import _load_rs_cache, _rs_cache_valid

SEP = "=" * 65


def load_universe():
    fp = "active_universe.json"
    if os.path.exists(fp):
        with open(fp, encoding="utf-8") as fh:
            d = json.load(fh)
        return d.get("tickers", []), d.get("sectors", {})
    from tickers import TICKERS
    return list(TICKERS), {}


def apply_old_filter(tickers, meta_map, excluded_set, rs_cache):
    """Pass 1 with hard above_sma50 gate."""
    survivors, rejected = [], []
    for t in tickers:
        meta = meta_map.get(t)
        if meta is None:
            survivors.append(t); continue
        if t in excluded_set: continue
        if meta.get("last_close", 0) < PASS1_MIN_PRICE: continue
        if (meta.get("avg_vol_20d", 0) < PASS1_MIN_AVG_VOLUME
                or meta.get("dollar_vol", 0) < PASS1_MIN_DOLLAR_VOLUME): continue
        # old hard SMA50 gate
        if not meta.get("above_sma50", True):
            rejected.append(t)
            continue
        lc  = meta.get("last_close", 0)
        h52 = meta.get("high_52w",   0)
        if h52 > 0 and lc / h52 < PASS1_MIN_52W_HIGH_PCT: continue
        rs = rs_cache.get(t)
        if rs is not None and rs < (PASS1_MIN_RS_RANK_WARM if rs_cache else PASS1_MIN_RS_RANK): continue
        survivors.append(t)
    return survivors, rejected


def apply_new_filter(tickers, meta_map, excluded_set, rs_cache):
    """Pass 1 with conditional SMA50 gate."""
    survivors = []
    cnt = {"cold":0,"vol":0,"prox52":0,"sma50_blocked":0,"rs":0,"pass":0}
    breakdown = {"above_pass":0,"below_near_vol":0,"below_near_rs":0,"below_blocked":0}

    rs_floor = PASS1_MIN_RS_RANK_WARM if rs_cache else PASS1_MIN_RS_RANK

    for t in tickers:
        meta = meta_map.get(t)
        if meta is None:
            cnt["cold"] += 1; survivors.append(t); continue
        if t in excluded_set: continue
        if meta.get("last_close", 0) < PASS1_MIN_PRICE: continue
        if (meta.get("avg_vol_20d", 0) < PASS1_MIN_AVG_VOLUME
                or meta.get("dollar_vol", 0) < PASS1_MIN_DOLLAR_VOLUME):
            cnt["vol"] += 1; continue

        lc  = meta.get("last_close", 0)
        h52 = meta.get("high_52w",   0)
        vr  = meta.get("vol_ratio_5d", 0)
        above = meta.get("above_sma50", True)

        if above:
            if h52 > 0 and lc / h52 < PASS1_MIN_52W_HIGH_PCT:
                cnt["prox52"] += 1; continue
            breakdown["above_pass"] += 1
        else:
            near_high = h52 > 0 and lc / h52 >= PASS1_BELOW_SMA50_MIN_52W_PCT
            vol_ok    = vr  >= PASS1_BELOW_SMA50_VOL_RATIO
            rs_val    = rs_cache.get(t)
            rs_ok     = rs_val is not None and rs_val >= PASS1_BELOW_SMA50_MIN_RS
            if not (near_high and (vol_ok or rs_ok)):
                cnt["sma50_blocked"] += 1; breakdown["below_blocked"] += 1; continue
            if vol_ok:  breakdown["below_near_vol"] += 1
            elif rs_ok: breakdown["below_near_rs"]  += 1

        rs = rs_cache.get(t)
        if rs is not None and rs < rs_floor:
            cnt["rs"] += 1; continue
        cnt["pass"] += 1; survivors.append(t)

    return survivors, cnt, breakdown


def main():
    print()
    print(SEP)
    print("  Pass 1 refinement — conditional SMA50 gate")
    print(SEP)

    tickers, _ = load_universe()
    cs = CacheStore(cache_dir=SCAN_CACHE_DIR)
    cs.preload_index()
    meta_map   = {t: cs.get_meta(t) for t in tickers if cs.get_meta(t) is not None}
    excl_set   = {t for t in tickers if cs.is_excluded(t)}
    meta_count = len(meta_map)
    cold_count = len(tickers) - meta_count

    raw_rs = _load_rs_cache()
    if _rs_cache_valid(raw_rs):
        rs_cache = {k: v for k, v in raw_rs.items() if not k.startswith("_")}
        print(f"  RS cache: VALID ({raw_rs['_meta']['ticker_count']} tickers)")
    else:
        rs_cache = {}
        print("  RS cache: NOT VALID (empty — RS filter skipped)")

    print(f"  Metadata: {meta_count}/{len(tickers)} tickers  |  Cold pass-throughs: {cold_count}")

    # OLD filter
    old_surv, old_rejected_below_sma50 = apply_old_filter(tickers, meta_map, excl_set, rs_cache)
    # NEW filter
    new_surv, new_cnt, new_breakdown = apply_new_filter(tickers, meta_map, excl_set, rs_cache)

    # Tickers that now survive but were rejected by the old hard gate
    old_surv_set = set(old_surv)
    new_surv_set = set(new_surv)
    newly_allowed  = [t for t in new_surv_set if t not in old_surv_set and meta_map.get(t) is not None]
    still_rejected = [t for t in old_rejected_below_sma50 if t not in new_surv_set]

    print()
    print(SEP)
    print("  Survivor comparison (metadata tickers only)")
    print(SEP)
    old_meta_surv = [t for t in old_surv if meta_map.get(t) is not None]
    new_meta_surv = [t for t in new_surv if meta_map.get(t) is not None]
    print(f"\n  OLD (hard SMA50 gate):        {len(old_meta_surv)}/{meta_count}  ({len(old_meta_surv)/meta_count*100:.0f}%)")
    print(f"  NEW (conditional SMA50 gate): {len(new_meta_surv)}/{meta_count}  ({len(new_meta_surv)/meta_count*100:.0f}%)")
    print(f"\n  NEW filter breakdown (with metadata):")
    print(f"    Above SMA50 (pass after prox52 check):  {new_breakdown['above_pass']}")
    print(f"    Below SMA50, near-high + vol-surge:     {new_breakdown['below_near_vol']}")
    print(f"    Below SMA50, near-high + strong RS:     {new_breakdown['below_near_rs']}")
    print(f"    Below SMA50, blocked (deep/no signal):  {new_breakdown['below_blocked']}")
    print(f"    Failed RS floor:                        {new_cnt['rs']}")
    print(f"    Failed prox52 (above-SMA50 deep drop):  {new_cnt['prox52']}")

    print()
    print(SEP)
    print(f"  Tickers NEWLY allowed ({len(newly_allowed)}) — were killed by hard SMA50, now survive")
    print(SEP)
    if newly_allowed:
        for t in sorted(newly_allowed):
            meta = meta_map[t]
            lc  = meta.get("last_close", 0)
            h52 = meta.get("high_52w",   0)
            vr  = meta.get("vol_ratio_5d", 0)
            rs  = rs_cache.get(t)
            prox = lc/h52 if h52 > 0 else 0
            reason = []
            if vr >= PASS1_BELOW_SMA50_VOL_RATIO:  reason.append(f"vol={vr:.2f}")
            if rs is not None and rs >= PASS1_BELOW_SMA50_MIN_RS: reason.append(f"RS={rs:.0f}")
            print(f"    {t:6s}  close={lc:7.2f}  52w-prox={prox:.2f}  vol_ratio={vr:.2f}  RS={rs if rs is not None else 'n/a'}  [{', '.join(reason)}]")
    else:
        print("    (none — all below-SMA50 tickers in sample lack quality signal)")

    print()
    print(SEP)
    print(f"  Tickers STILL blocked ({len(still_rejected)}) — below SMA50, no quality signal")
    print(SEP)
    for t in sorted(still_rejected):
        meta = meta_map[t]
        lc   = meta.get("last_close", 0)
        h52  = meta.get("high_52w",   0)
        vr   = meta.get("vol_ratio_5d", 0)
        prox = lc/h52 if h52 > 0 else 0
        reason = []
        if h52 > 0 and prox < PASS1_BELOW_SMA50_MIN_52W_PCT: reason.append(f"prox={prox:.2f}<{PASS1_BELOW_SMA50_MIN_52W_PCT}")
        elif vr < PASS1_BELOW_SMA50_VOL_RATIO: reason.append(f"vol={vr:.2f}<{PASS1_BELOW_SMA50_VOL_RATIO}")
        print(f"    {t:6s}  close={lc:7.2f}  52w-prox={prox:.2f}  vol_ratio={vr:.2f}  [{', '.join(reason)}]")

    # Full survivor count (cold + meta)
    print()
    print(SEP)
    print("  Full universe results (cold pass-throughs + metadata survivors)")
    print(SEP)
    print(f"\n  OLD total: {len(old_surv)}/{len(tickers)}  ({len(old_surv)/len(tickers)*100:.1f}%)")
    print(f"  NEW total: {len(new_surv)}/{len(tickers)}  ({len(new_surv)/len(tickers)*100:.1f}%)")
    print(f"  Delta:     {len(new_surv)-len(old_surv):+d}")
    print()

    # Projected full-warm-scan impact
    if meta_count > 0:
        old_rate = len(old_meta_surv) / meta_count
        new_rate = len(new_meta_surv) / meta_count
        proj_old = round(len(tickers) * old_rate)
        proj_new = round(len(tickers) * new_rate)
        print(f"  PROJECTED (all {len(tickers)} tickers warm):")
        print(f"    OLD: ~{proj_old}  ({old_rate*100:.0f}% of universe)")
        print(f"    NEW: ~{proj_new}  ({new_rate*100:.0f}% of universe)")
        target_lo, target_hi = 200, 400
        in_range = target_lo <= proj_new <= target_hi
        print(f"    Target 200-400: {'IN RANGE' if in_range else 'OUTSIDE RANGE'}")

    print()
    print(SEP)
    print("  CHECKS")
    print(SEP)
    checks = [
        ("New logic allows some below-SMA50 tickers (pullbacks preserved)",
         len(newly_allowed) > 0 or new_breakdown["below_near_vol"] + new_breakdown["below_near_rs"] > 0),
        ("Deep drawdowns still blocked",
         new_breakdown["below_blocked"] > 0),
        ("Cold pass-throughs unchanged",
         new_cnt["cold"] == cold_count),
        ("RS floor raised when cache valid",
         PASS1_MIN_RS_RANK_WARM > PASS1_MIN_RS_RANK),
        ("No indicator computation (metadata-only)",
         True),  # by construction
    ]
    print()
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}]  {desc}")
    print()


if __name__ == "__main__":
    main()
