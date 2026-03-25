"""
validate_pass1_adaptive.py — Validate adaptive below-SMA50 thresholds.

Run from backend/:
    python docs/validate_pass1_adaptive.py
"""
from __future__ import annotations
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.WARNING, format="%(message)s")

from constants import (
    PASS1_MIN_PRICE, PASS1_MIN_AVG_VOLUME, PASS1_MIN_DOLLAR_VOLUME,
    PASS1_MIN_RS_RANK, PASS1_MIN_RS_RANK_WARM,
    PASS1_MIN_52W_HIGH_PCT,
    PASS1_BELOW_SMA50_MIN_52W_PCT, PASS1_BELOW_SMA50_VOL_RATIO, PASS1_BELOW_SMA50_MIN_RS,
    PASS1_BELOW_SMA50_VOL_PERCENTILE, PASS1_BELOW_SMA50_VOL_FLOOR, PASS1_BELOW_SMA50_VOL_CEIL,
    PASS1_BELOW_SMA50_PROX_PERCENTILE, PASS1_BELOW_SMA50_PROX_FLOOR, PASS1_BELOW_SMA50_PROX_CEIL,
    PASS1_BELOW_SMA50_MIN_SAMPLE,
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


def compute_adaptive_thresholds(tickers, meta_map):
    """Mirror of _compute_below_sma50_thresholds() logic."""
    vol_vals  = []
    prox_vals = []
    for t in tickers:
        meta = meta_map.get(t)
        if meta is None:
            continue
        vr = meta.get("vol_ratio_5d")
        if vr is not None:
            vol_vals.append(vr)
        lc  = meta.get("last_close", 0)
        h52 = meta.get("high_52w",   0)
        if not meta.get("above_sma50", True) and h52 > 0 and lc > 0:
            prox_vals.append(lc / h52)

    if len(vol_vals) >= PASS1_BELOW_SMA50_MIN_SAMPLE:
        sv = sorted(vol_vals)
        idx = int(len(sv) * PASS1_BELOW_SMA50_VOL_PERCENTILE / 100)
        raw_vol = sv[min(idx, len(sv) - 1)]
        vol_thr = max(PASS1_BELOW_SMA50_VOL_FLOOR, min(PASS1_BELOW_SMA50_VOL_CEIL, raw_vol))
        vol_src = "adaptive"
    else:
        raw_vol = None
        vol_thr = PASS1_BELOW_SMA50_VOL_RATIO
        vol_src = "fixed fallback"

    if len(prox_vals) >= PASS1_BELOW_SMA50_MIN_SAMPLE:
        sp = sorted(prox_vals)
        idx = int(len(sp) * PASS1_BELOW_SMA50_PROX_PERCENTILE / 100)
        raw_prox = sp[min(idx, len(sp) - 1)]
        prox_thr = max(PASS1_BELOW_SMA50_PROX_FLOOR, min(PASS1_BELOW_SMA50_PROX_CEIL, raw_prox))
        prox_src = "adaptive"
    else:
        raw_prox = None
        prox_thr = PASS1_BELOW_SMA50_MIN_52W_PCT
        prox_src = "fixed fallback"

    return vol_thr, prox_thr, vol_vals, prox_vals, raw_vol, raw_prox, vol_src, prox_src


def apply_filter(tickers, meta_map, excluded_set, rs_cache, vol_thr, prox_thr):
    """Apply Pass 1 with given below-SMA50 thresholds."""
    rs_floor = PASS1_MIN_RS_RANK_WARM if rs_cache else PASS1_MIN_RS_RANK
    survivors = []
    cnt = {"cold": 0, "excl": 0, "price": 0, "vol": 0, "sma50_blocked": 0,
           "prox52": 0, "rs": 0, "pass": 0}
    for t in tickers:
        meta = meta_map.get(t)
        if meta is None:
            cnt["cold"] += 1; survivors.append(t); continue
        if t in excluded_set:
            cnt["excl"] += 1; continue
        if meta.get("last_close", 0) < PASS1_MIN_PRICE:
            cnt["price"] += 1; continue
        if (meta.get("avg_vol_20d", 0) < PASS1_MIN_AVG_VOLUME
                or meta.get("dollar_vol", 0) < PASS1_MIN_DOLLAR_VOLUME):
            cnt["vol"] += 1; continue
        lc  = meta.get("last_close", 0)
        h52 = meta.get("high_52w",   0)
        vr  = meta.get("vol_ratio_5d", 0)
        if meta.get("above_sma50", True):
            if h52 > 0 and lc / h52 < PASS1_MIN_52W_HIGH_PCT:
                cnt["prox52"] += 1; continue
        else:
            near_high = h52 > 0 and lc / h52 >= prox_thr
            vol_ok    = vr  >= vol_thr
            rs_v      = rs_cache.get(t)
            rs_ok     = rs_v is not None and rs_v >= PASS1_BELOW_SMA50_MIN_RS
            if not (near_high and (vol_ok or rs_ok)):
                cnt["sma50_blocked"] += 1; continue
        rs = rs_cache.get(t)
        if rs is not None and rs < rs_floor:
            cnt["rs"] += 1; continue
        cnt["pass"] += 1; survivors.append(t)
    return survivors, cnt


def main():
    print()
    print(SEP)
    print("  Pass 1 adaptive thresholds — validation")
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
        print("  RS cache: NOT VALID (empty -- RS filter skipped)")

    print(f"  Metadata: {meta_count}/{len(tickers)} tickers  |  Cold: {cold_count}")

    # ── Compute adaptive thresholds ──────────────────────────────────────────
    vol_thr, prox_thr, vol_vals, prox_vals, raw_vol, raw_prox, vol_src, prox_src = \
        compute_adaptive_thresholds(tickers, meta_map)

    print()
    print(SEP)
    print("  Threshold computation")
    print(SEP)
    print(f"\n  Vol ratio distribution ({len(vol_vals)} tickers with metadata):")
    if vol_vals:
        sv = sorted(vol_vals)
        n = len(sv)
        for p in [50, 60, 70, 75, 80]:
            idx = int(n * p / 100)
            print(f"    P{p:2d} = {sv[min(idx, n-1)]:.3f}")
    raw_vol_s = f"{raw_vol:.3f}" if raw_vol is not None else "n/a"
    print(f"\n  ADAPTIVE vol_thr  = {vol_thr:.3f}  [{vol_src}]"
          f"  (P{PASS1_BELOW_SMA50_VOL_PERCENTILE}, raw={raw_vol_s}, "
          f"clamp=[{PASS1_BELOW_SMA50_VOL_FLOOR}, {PASS1_BELOW_SMA50_VOL_CEIL}])")
    print(f"  FIXED    vol_thr  = {PASS1_BELOW_SMA50_VOL_RATIO:.3f}")

    print(f"\n  52w-prox distribution below-SMA50 ({len(prox_vals)} tickers):")
    if prox_vals:
        sp = sorted(prox_vals)
        n = len(sp)
        for p in [50, 60, 70, 75, 80]:
            idx = int(n * p / 100)
            print(f"    P{p:2d} = {sp[min(idx, n-1)]:.3f}")
    raw_prox_s = f"{raw_prox:.3f}" if raw_prox is not None else "n/a"
    print(f"\n  ADAPTIVE prox_thr = {prox_thr:.3f}  [{prox_src}]"
          f"  (P{PASS1_BELOW_SMA50_PROX_PERCENTILE}, raw={raw_prox_s}, "
          f"clamp=[{PASS1_BELOW_SMA50_PROX_FLOOR}, {PASS1_BELOW_SMA50_PROX_CEIL}])")
    print(f"  FIXED    prox_thr = {PASS1_BELOW_SMA50_MIN_52W_PCT:.3f}")

    # ── Compare fixed vs adaptive ────────────────────────────────────────────
    print()
    print(SEP)
    print("  Survivor comparison: FIXED vs ADAPTIVE thresholds")
    print(SEP)

    fixed_surv, fixed_cnt = apply_filter(
        tickers, meta_map, excl_set, rs_cache,
        PASS1_BELOW_SMA50_VOL_RATIO, PASS1_BELOW_SMA50_MIN_52W_PCT
    )
    adapt_surv, adapt_cnt = apply_filter(
        tickers, meta_map, excl_set, rs_cache,
        vol_thr, prox_thr
    )

    fixed_meta = [t for t in fixed_surv if meta_map.get(t) is not None]
    adapt_meta = [t for t in adapt_surv if meta_map.get(t) is not None]
    n = meta_count if meta_count > 0 else 1

    print(f"\n  FIXED    (vol>={PASS1_BELOW_SMA50_VOL_RATIO:.2f}, prox>={PASS1_BELOW_SMA50_MIN_52W_PCT:.2f}):")
    print(f"    Survivors (meta): {len(fixed_meta)}/{meta_count} ({len(fixed_meta)/n*100:.0f}%)")
    print(f"    sma50_blocked: {fixed_cnt['sma50_blocked']}  prox52: {fixed_cnt['prox52']}  rs: {fixed_cnt['rs']}")

    print(f"\n  ADAPTIVE (vol>={vol_thr:.3f}, prox>={prox_thr:.3f}):")
    print(f"    Survivors (meta): {len(adapt_meta)}/{meta_count} ({len(adapt_meta)/n*100:.0f}%)")
    print(f"    sma50_blocked: {adapt_cnt['sma50_blocked']}  prox52: {adapt_cnt['prox52']}  rs: {adapt_cnt['rs']}")

    delta = len(adapt_meta) - len(fixed_meta)
    print(f"\n  Delta: {delta:+d} tickers (adaptive vs fixed)")

    # Tickers that differ
    fixed_set = set(fixed_surv)
    adapt_set = set(adapt_surv)
    newly_allowed  = [t for t in adapt_set - fixed_set if meta_map.get(t) is not None]
    newly_blocked  = [t for t in fixed_set - adapt_set if meta_map.get(t) is not None]

    if newly_allowed:
        print(f"\n  Newly ALLOWED by adaptive ({len(newly_allowed)}):")
        for t in sorted(newly_allowed):
            meta = meta_map[t]
            lc  = meta.get("last_close", 0)
            h52 = meta.get("high_52w",   0)
            vr  = meta.get("vol_ratio_5d", 0)
            rs  = rs_cache.get(t)
            prox = lc/h52 if h52 > 0 else 0
            print(f"    {t:6s}  close={lc:7.2f}  prox={prox:.3f}  vol={vr:.3f}  RS={rs if rs is not None else 'n/a'}")
    else:
        print("\n  Newly ALLOWED by adaptive: (none)")

    if newly_blocked:
        print(f"\n  Newly BLOCKED by adaptive ({len(newly_blocked)}):")
        for t in sorted(newly_blocked):
            meta = meta_map[t]
            lc  = meta.get("last_close", 0)
            h52 = meta.get("high_52w",   0)
            vr  = meta.get("vol_ratio_5d", 0)
            rs  = rs_cache.get(t)
            prox = lc/h52 if h52 > 0 else 0
            print(f"    {t:6s}  close={lc:7.2f}  prox={prox:.3f}  vol={vr:.3f}  RS={rs if rs is not None else 'n/a'}")
    else:
        print("\n  Newly BLOCKED by adaptive: (none)")

    # Projected full-warm impact
    print()
    print(SEP)
    print("  Projected full-warm-scan impact")
    print(SEP)
    if meta_count > 0:
        for label, surv in [("FIXED", fixed_meta), ("ADAPTIVE", adapt_meta)]:
            rate = len(surv) / meta_count
            proj = round(len(tickers) * rate)
            in_range = 200 <= proj <= 400
            print(f"  {label:8s}  rate={rate*100:.0f}%  projected={proj}  "
                  f"{'IN RANGE [200-400]' if in_range else 'OUTSIDE RANGE'}")

    # Checks
    print()
    print(SEP)
    print("  CHECKS")
    print(SEP)
    checks = [
        ("Adaptive vol_thr within bounds",
         PASS1_BELOW_SMA50_VOL_FLOOR <= vol_thr <= PASS1_BELOW_SMA50_VOL_CEIL),
        ("Adaptive prox_thr within bounds",
         PASS1_BELOW_SMA50_PROX_FLOOR <= prox_thr <= PASS1_BELOW_SMA50_PROX_CEIL),
        ("Adaptive survivors within target range (projected 200-400)",
         meta_count == 0 or 200 <= round(len(tickers) * len(adapt_meta) / meta_count) <= 400),
        ("Cold pass-throughs unchanged (both filters)",
         fixed_cnt["cold"] == adapt_cnt["cold"] == cold_count),
        ("Minimum sample met for vol (adaptive active)",
         len(vol_vals) >= PASS1_BELOW_SMA50_MIN_SAMPLE),
        ("Minimum sample met for prox (adaptive active)",
         len(prox_vals) >= PASS1_BELOW_SMA50_MIN_SAMPLE),
    ]
    print()
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}]  {desc}")
    print()


if __name__ == "__main__":
    main()
