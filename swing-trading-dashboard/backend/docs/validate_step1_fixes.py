"""
validate_step1_fixes.py — Validation for Step 1 fixes (RS cache + scan_cache).

Run from backend/:
    python docs/validate_step1_fixes.py

What it checks:
  Task 1 — Cold start: Pass 1 survivors, I/O phase writes parquet + metadata.json,
            RS gate pass rate, number of final scoring candidates.
  Task 2 — Warm run: cache hit counts, runtime delta vs cold run.
  Task 3 — RS cache recomputation: ticker_count after run, 5 example RS values.
  Task 4 — Inefficiency: tickers fetched but killed at RS gate.

Uses a 60-ticker sample for the I/O phase (keeps runtime ~1-2 min).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import sys
import time
from datetime import date
from typing import Dict, List, Optional, Tuple

# ── Setup ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("validate")

# Silence noisy sub-loggers
for _noisy in ("yfinance", "urllib3", "peewee", "apscheduler"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import (
    DISCOVERY_RS_MAX,
    DISCOVERY_RS_MIN,
    PASS1_MAX_SURVIVORS,
    PASS1_MIN_AVG_VOLUME,
    PASS1_MIN_DOLLAR_VOLUME,
    PASS1_MIN_PRICE,
    PASS1_MIN_RS_RANK,
    PRICE_CACHE_FRESH_DAYS,
    RS_RANK_CACHE_FILE,
    RS_RANK_CACHE_MIN_TICKERS,
    RS_RANK_MIN_PERCENTILE,
    SCAN_CACHE_DIR,
)
from cache_store import CacheStore, _biz_days_since
from scoring import (
    _load_rs_cache,
    _rs_cache_valid,
    compute_rs_rank_map,
)

SAMPLE_N      = 60    # tickers for I/O phase sample (keep test fast)
IO_WORKERS    = 12    # concurrent yfinance connections
IO_SEMAPHORE  = 12    # same — no artificial throttle for test

SEP = "=" * 65


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_universe() -> Tuple[List[str], Dict[str, str]]:
    """Load active universe from active_universe.json, fall back to tickers.py."""
    fp = "active_universe.json"
    if os.path.exists(fp):
        with open(fp, encoding="utf-8") as fh:
            data = json.load(fh)
        tickers = data.get("tickers", [])
        sectors = data.get("sectors", {})
        log.info("Universe loaded from %s: %d tickers", fp, len(tickers))
        return tickers, sectors
    from tickers import TICKERS
    log.info("Universe loaded from tickers.py: %d tickers", len(TICKERS))
    return list(TICKERS), {}


def _identify_discovery_candidates(
    universe: List[str],
    cache_store: CacheStore,
    rs_cache: dict,
) -> set:
    candidates: set = set()
    for ticker in universe:
        rs = rs_cache.get(ticker)
        if rs is None or not (DISCOVERY_RS_MIN <= rs < DISCOVERY_RS_MAX):
            continue
        meta = cache_store.get_meta(ticker)
        if not meta:
            continue
        lc  = meta.get("last_close", 0)
        h52 = meta.get("high_52w", 0)
        vr  = meta.get("vol_ratio_5d", 0)
        from constants import DISCOVERY_52WK_HIGH_PCT, DISCOVERY_VOL_RATIO
        near_high = h52 > 0 and lc / h52 >= (1 - DISCOVERY_52WK_HIGH_PCT)
        vol_surge = vr >= DISCOVERY_VOL_RATIO
        if near_high and vol_surge:
            candidates.add(ticker)
    return candidates


def _pass1_filter(
    universe: List[str],
    cache_store: CacheStore,
    rs_cache: dict,
) -> Tuple[List[str], set]:
    """Replicates main._pass1_filter logic — no FastAPI import needed."""
    discovery = _identify_discovery_candidates(universe, cache_store, rs_cache)

    cold_count = meta_count = excluded_count = price_fail = vol_fail = rs_fail = 0

    def _apply_filters(univ, rs_floor):
        nonlocal cold_count, meta_count, excluded_count, price_fail, vol_fail, rs_fail
        result = []
        for ticker in univ:
            is_disc = ticker in discovery
            meta = cache_store.get_meta(ticker)
            if meta is None:
                cold_count += 1
                result.append(ticker)
                continue
            meta_count += 1
            if cache_store.is_excluded(ticker):
                excluded_count += 1
                continue
            if meta.get("last_close", 0) < PASS1_MIN_PRICE:
                price_fail += 1
                continue
            if (meta.get("avg_vol_20d", 0) < PASS1_MIN_AVG_VOLUME
                    or meta.get("dollar_vol", 0) < PASS1_MIN_DOLLAR_VOLUME):
                vol_fail += 1
                continue
            rs = rs_cache.get(ticker)
            if rs is not None and not is_disc and rs < rs_floor:
                rs_fail += 1
                continue
            result.append(ticker)
        return result

    survivors = _apply_filters(universe, PASS1_MIN_RS_RANK)

    # Adaptive tightening
    tighten_steps = 0
    if len(survivors) > PASS1_MAX_SURVIVORS:
        for rs_step, dv_mult in [(50, 1.0), (50, 1.6), (55, 1.6)]:
            new = [
                t for t in survivors
                if t in discovery
                or cache_store.get_meta(t) is None
                or (
                    (rs_cache.get(t) or 0) >= rs_step
                    and (cache_store.get_meta(t) or {}).get("dollar_vol", 0) >= PASS1_MIN_DOLLAR_VOLUME * dv_mult
                )
            ]
            tighten_steps += 1
            survivors = new
            if len(survivors) <= PASS1_MAX_SURVIVORS:
                break

    return survivors, discovery, {
        "cold": cold_count,
        "meta": meta_count,
        "excluded": excluded_count,
        "price_fail": price_fail,
        "vol_fail": vol_fail,
        "rs_fail": rs_fail,
        "tighten_steps": tighten_steps,
        "discovery": len(discovery),
    }


def _cache_status_for_tickers(
    tickers: List[str],
    cache_store: CacheStore,
) -> Dict[str, int]:
    """Classify tickers as fresh / incremental (stale) / cold."""
    fresh = incremental = cold = 0
    for t in tickers:
        meta = cache_store.get_meta(t)
        if meta is None:
            cold += 1
            continue
        lu = meta.get("last_updated")
        if lu is None:
            cold += 1
            continue
        biz = _biz_days_since(date.fromisoformat(lu))
        if biz <= PRICE_CACHE_FRESH_DAYS:
            fresh += 1
        else:
            incremental += 1
    return {"fresh": fresh, "incremental": incremental, "cold": cold}


def _count_parquet(scan_dir: str) -> Tuple[int, bool]:
    p = pathlib.Path(scan_dir)
    parquet_count = len(list(p.rglob("*.parquet")))
    meta_exists   = (p / "metadata.json").exists()
    return parquet_count, meta_exists


def _fetch_spy() -> Optional[object]:
    try:
        import yfinance as yf
        df = yf.Ticker("SPY").history(period="1y", interval="1d", auto_adjust=False)
        if df is not None and not df.empty:
            log.info("SPY fetched: %d bars", len(df))
            return df
    except Exception as exc:
        log.warning("SPY fetch failed: %s", exc)
    return None


# ── Main validation ───────────────────────────────────────────────────────────

async def run_validation() -> None:
    print()
    print(SEP)
    print("  VALIDATION — Step 1 fixes")
    print(SEP)

    # ── Load universe ──────────────────────────────────────────────────────────
    tickers, sectors = load_universe()

    # ── TASK 3: RS cache state BEFORE scan ─────────────────────────────────────
    print()
    print("  TASK 3: RS cache — state before scan")
    print()
    raw_cache_before = _load_rs_cache()
    if raw_cache_before is None:
        print("  RS cache:  MISSING  (no file at", RS_RANK_CACHE_FILE + ")")
        print("  -> Will be recomputed after I/O phase.")
    else:
        m = raw_cache_before.get("_meta", {})
        valid = _rs_cache_valid(raw_cache_before)
        print(f"  RS cache exists:  ticker_count={m.get('ticker_count',0)}"
              f"  version={m.get('logic_version')}  valid={valid}")
        if not valid:
            print(f"  -> INVALID (min required: {RS_RANK_CACHE_MIN_TICKERS}). "
                  "Will recompute after I/O phase.")

    # ── TASK 1: Cold start ─────────────────────────────────────────────────────
    print()
    print("  TASK 1: Cold start scan")
    print()

    # Init cache store
    cs_cold = CacheStore(cache_dir=SCAN_CACHE_DIR)
    cs_cold.preload_index()

    meta_before = sum(1 for t in tickers if cs_cold.get_meta(t) is not None)
    print(f"  Metadata in cache (before):  {meta_before} / {len(tickers)} tickers")

    status_before = _cache_status_for_tickers(tickers[:SAMPLE_N], cs_cold)
    print(f"  Sample ({SAMPLE_N} tickers) — fresh: {status_before['fresh']}  "
          f"incremental: {status_before['incremental']}  cold: {status_before['cold']}")

    # Pass 1
    survivors, discovery, p1_stats = _pass1_filter(tickers, cs_cold, {})
    print()
    print(f"  Pass 1 result:")
    print(f"    Universe:      {len(tickers)}")
    print(f"    Cold (meta=None, pass-through): {p1_stats['cold']}")
    print(f"    With metadata: {p1_stats['meta']}")
    print(f"      Excluded (stale): {p1_stats['excluded']}")
    print(f"      Price fail:       {p1_stats['price_fail']}")
    print(f"      Volume fail:      {p1_stats['vol_fail']}")
    print(f"      RS fail:          {p1_stats['rs_fail']}")
    print(f"    Tighten steps: {p1_stats['tighten_steps']}")
    print(f"    Discovery:     {p1_stats['discovery']}")
    print(f"    SURVIVORS:     {len(survivors)}")

    # I/O phase — sample only (SAMPLE_N tickers)
    sample = survivors[:SAMPLE_N]
    print()
    print(f"  I/O phase: fetching {len(sample)} tickers (sample)...")
    parquet_before, _ = _count_parquet(SCAN_CACHE_DIR)
    t_io_start = time.time()
    sem = asyncio.Semaphore(IO_SEMAPHORE)
    await cs_cold.bulk_fetch_incremental(sample, sem, workers=IO_WORKERS)
    cold_io_time = time.time() - t_io_start
    parquet_after, meta_json_exists = _count_parquet(SCAN_CACHE_DIR)
    print(f"    I/O time:           {cold_io_time:.1f}s")
    print(f"    Parquet files:      {parquet_before} before  ->  {parquet_after} after")
    print(f"    metadata.json:      {'EXISTS' if meta_json_exists else 'MISSING'}")

    if meta_json_exists:
        meta_path = pathlib.Path(SCAN_CACHE_DIR) / "metadata.json"
        with open(meta_path, encoding="utf-8") as fh:
            meta_content = json.load(fh)
        print(f"    metadata.json entries: {len(meta_content)}")

    # Build ticker_cache from cache_store
    now_ts = time.time()
    ticker_cache: Dict = {}
    for t in sample:
        df = cs_cold.get(t)
        if df is not None:
            ticker_cache[t] = (now_ts, df)
    print(f"    Ticker cache built: {len(ticker_cache)} / {len(sample)} tickers")

    # Fetch SPY for RS computation
    print()
    print("  Fetching SPY for RS computation...")
    spy_df = _fetch_spy()

    # Compute RS rank map
    rs_map = compute_rs_rank_map(ticker_cache, sample, spy_df, sample_size=len(sample))
    print(f"  RS rank map: {len(rs_map)} tickers ranked")

    # RS gate simulation
    rs_passed   = [t for t in sample if rs_map.get(t, -1) >= RS_RANK_MIN_PERCENTILE]
    rs_dropped  = [t for t in sample if rs_map.get(t, -1) < RS_RANK_MIN_PERCENTILE]
    rs_no_data  = [t for t in sample if t not in rs_map]
    print(f"  RS gate (>={RS_RANK_MIN_PERCENTILE}):")
    print(f"    Pass:         {len(rs_passed)}")
    print(f"    Drop (< {RS_RANK_MIN_PERCENTILE}): {len(rs_dropped)}")
    print(f"    No data:      {len(rs_no_data)}")

    # Cache hit rate from store
    print(f"  Cache hit rate:  {cs_cold.cache_hit_rate():.1%}")

    # ── TASK 3: RS cache after cold scan ───────────────────────────────────────
    print()
    print("  TASK 3: RS cache — state after cold scan")
    print()
    raw_cache_after = _load_rs_cache()
    if raw_cache_after is None:
        print(f"  RS cache: MISSING  (sample={SAMPLE_N} < min={RS_RANK_CACHE_MIN_TICKERS}  — expected, guard working)")
    else:
        m2 = raw_cache_after.get("_meta", {})
        v2 = _rs_cache_valid(raw_cache_after)
        print(f"  RS cache:  ticker_count={m2.get('ticker_count',0)}  "
              f"version={m2.get('logic_version')}  valid={v2}")

    print()
    print("  5 example RS values from this run:")
    for ticker, rs_val in list(rs_map.items())[:5]:
        gate = "PASS" if rs_val >= RS_RANK_MIN_PERCENTILE else "DROP"
        print(f"    {ticker:6s}  RS={rs_val:5.1f}  {gate}")

    # ── TASK 2: Warm run ───────────────────────────────────────────────────────
    print()
    print(SEP)
    print("  TASK 2: Warm run (same sample, immediately after cold)")
    print(SEP)
    print()

    cs_warm = CacheStore(cache_dir=SCAN_CACHE_DIR)
    cs_warm.preload_index()

    status_warm = _cache_status_for_tickers(sample, cs_warm)
    print(f"  Pre-warm cache status ({len(sample)} tickers):")
    print(f"    Fresh:       {status_warm['fresh']}")
    print(f"    Incremental: {status_warm['incremental']}")
    print(f"    Cold:        {status_warm['cold']}")

    print()
    print(f"  Running warm I/O phase for {len(sample)} tickers...")
    t_warm_start = time.time()
    sem2 = asyncio.Semaphore(IO_SEMAPHORE)
    await cs_warm.bulk_fetch_incremental(sample, sem2, workers=IO_WORKERS)
    warm_io_time = time.time() - t_warm_start
    print(f"    Warm I/O time:  {warm_io_time:.1f}s  (cold was {cold_io_time:.1f}s)")
    print(f"    Speedup:        {cold_io_time/max(warm_io_time,0.01):.1f}x")
    print(f"    Cache hit rate: {cs_warm.cache_hit_rate():.1%}")

    survivors_warm, _, p1_warm = _pass1_filter(tickers, cs_warm, {})
    print()
    print(f"  Pass 1 warm result:")
    print(f"    Cold (meta=None): {p1_warm['cold']}")
    print(f"    With metadata:    {p1_warm['meta']}")
    print(f"      Price fail:     {p1_warm['price_fail']}")
    print(f"      Volume fail:    {p1_warm['vol_fail']}")
    print(f"    SURVIVORS:        {len(survivors_warm)}")
    print()
    if p1_warm['cold'] < p1_stats['cold']:
        reduction = p1_stats['cold'] - p1_warm['cold']
        print(f"  Cold pass-throughs reduced by {reduction} "
              f"(those tickers now have metadata and are properly filtered)")

    # ── TASK 4: Inefficiency report ────────────────────────────────────────────
    print()
    print(SEP)
    print("  TASK 4: Inefficiency analysis")
    print(SEP)
    print()
    print(f"  Universe:              {len(tickers)} tickers")
    print(f"  Pass 1 survivors:      {len(survivors)} (cold)  /  {len(survivors_warm)} (warm)")
    print(f"  I/O phase (sample):    {len(sample)} fetched")
    print(f"  Ticker cache built:    {len(ticker_cache)}")
    print(f"  RS map computed:       {len(rs_map)}")
    print(f"  RS gate pass:          {len(rs_passed)} / {len(sample)}")
    print(f"  RS gate drop:          {len(rs_dropped) + len(rs_no_data)} / {len(sample)}")
    print()
    waste_pct = (len(rs_dropped) + len(rs_no_data)) / max(len(sample), 1) * 100
    print(f"  WASTE (fetched but killed at RS gate): "
          f"{len(rs_dropped)+len(rs_no_data)} tickers  ({waste_pct:.0f}% of sample)")
    print()
    print("  Cold start waste is expected — Pass 1 has no metadata to pre-filter.")
    print("  On warm runs, Pass 1 will filter on price/vol before fetch,")
    print("  and the RS gate applies only to survivors that clear price+vol.")
    print()
    print("  FULL scan warm-run estimate:")
    print(f"    Pass 1 cold survivors (all meta=None): {p1_stats['cold']}")
    print(f"    Pass 1 warm survivors (price+vol filtered): {len(survivors_warm)}")
    reduction_full = p1_stats['cold'] - len(survivors_warm)
    print(f"    Tickers eliminated by warm metadata: ~{reduction_full}")
    print()

    # Final verdict
    print(SEP)
    print("  RESULT SUMMARY")
    print(SEP)
    print()
    checks = [
        ("RS cache rejects stale/partial maps",
         raw_cache_before is None or not _rs_cache_valid(raw_cache_before)),
        ("RS cache NOT saved with partial data",
         raw_cache_after is None or raw_cache_after.get("_meta",{}).get("ticker_count",0) >= RS_RANK_CACHE_MIN_TICKERS or raw_cache_after is None),
        ("Parquet files created in scan_cache",
         parquet_after > parquet_before),
        ("metadata.json exists and is populated",
         meta_json_exists and len(meta_content) > 0),
        ("RS rank map has real values",
         len(rs_map) > 0),
        ("Warm run faster than cold run",
         warm_io_time < cold_io_time),
    ]
    for desc, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}]  {desc}")
    print()


if __name__ == "__main__":
    asyncio.run(run_validation())
