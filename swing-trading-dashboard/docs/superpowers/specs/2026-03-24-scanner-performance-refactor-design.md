# Scanner Performance Refactor — Design Spec
**Date:** 2026-03-24
**Status:** Approved (post-review revision)
**Target runtime:** 2–3 minutes (from 10–15 minutes)

---

## 1. Problem Statement

The live scanner takes 10–15 minutes per run. The dominant bottlenecks are:
- Full 1-year OHLCV re-download for ~1600 tickers every scan (~5–8 min)
- All 1600 tickers processed through heavy indicator computation (no early exit)
- RS rank map recomputed from scratch every scan (~15–30s)
- `asyncio.gather` spawns ~1600 concurrent coroutines at once (memory + event-loop overhead)

**Constraints:** Result quality must not degrade. All existing engines, indicators, and scoring logic are unchanged.

---

## 2. Architecture Overview

### Files changed
```
cache_store.py          ← NEW: disk-persisted OHLCV + lightweight metadata + in-memory layer
main.py                 ← MODIFIED: two-pass scan, worker queues, metrics logging
scoring.py              ← MODIFIED: RS rank cache persistence + TTL + version hash
universe_builder.py     ← MODIFIED: tighter pre-filters
constants.py            ← MODIFIED: new constants for pass 1, cache, workers
```

### Cache directories — no collision with WFO

The existing WFO system uses `data/price_cache/` for flat, unsharded parquet files.
The new scanner cache uses a **separate directory** to avoid any collision:

```
data/scan_cache/              ← NEW: scanner OHLCV cache (sharded)
  metadata.json               ← lightweight per-ticker index
  A/
    AAPL.parquet
    AMZN.parquet
  B/
    BAC.parquet
  S/
    SPY.parquet               ← SPY cached same as any other ticker
  ...
data/price_cache/             ← UNCHANGED: WFO system (do not touch)
cache/
  rs_rank_cache.json          ← RS rank map with TTL + logic version
```

Sharding by first letter keeps each subdirectory to ~30–80 files (26 letters × ~30 files = ~800 tickers typical). If universe exceeds ~5000 tickers, shard by first two letters.

### High-level data flow

```
Server start
  └─ CacheStore.preload_index(): load metadata.json into memory (no parquet reads)

_run_scan():
  ├─ [cold start only] Full downloads for all tickers with no metadata,
  │   then metadata.json is written before Pass 1 proceeds
  │
  ├─ t0: PASS 1 — fast filter (~2–5s, zero network)
  │     For each ticker in ACTIVE_UNIVERSE:
  │       Read from in-memory metadata (last_close, avg_vol, above_sma50, rs_rank)
  │       Apply price / volume / RS / vitality filters → 200–400 survivors
  │       Identify discovery candidates (RS 60–70 + near-high + vol surge) → whitelist
  │       Compute breadth (% above SMA50) from full-universe metadata → passes to Engine 0
  │
  ├─ t1: Incremental fetch — I/O worker pool (48 workers)
  │     For each survivor + SPY: load parquet tail + fetch missing days only
  │     Batch fallback: 100 → 25 → individual on failure
  │
  ├─ t2: RS rank map — disk cache check
  │     If cache fresh (< 24h, logic_version matches): return cached map
  │     Else: full recompute over survivors' data + persist to disk
  │     (Note: Pass 1 uses the cache file directly; pass 2 uses the freshly verified map)
  │
  ├─ t3: Engine 0 — regime (uses breadth pre-computed at t0 from full metadata)
  │
  └─ t4: PASS 2 — compute worker pool (min(32, cpu_count×2) workers)
        Per-ticker pipeline (preserving live scanner order):
          1. vitality check        is_price_vital()
          2. RS rank gate          _rs_rank_map.get(ticker)  ← regime-specific threshold
          3. compute_indicators    compute_indicators()
          4. liquidity gate        passes_liquidity()        ← uses ind.avg_volume_50d
          5. earnings blackout     in_earnings_blackout()
          6. engines 1–9           (unchanged)
        → score + filter → batch DB save

  Log: pass1_filter_s, fetch_s, rs_s, pass2_s, cache_hit_rate, pass1_survivors
```

---

## 3. `cache_store.py` — New Module

### 3.1 Storage format

- **Directory:** `data/scan_cache/` (separate from WFO's `data/price_cache/`)
- **One file per ticker:** `data/scan_cache/{FIRST_LETTER}/{TICKER}.parquet`
- **Columns:** `Open, High, Low, Close, Adj Close, Volume`
- **Index:** timezone-naive `DatetimeIndex` (date-only, no time component)
- **Compression:** `snappy` (fast read/write)
- **Writes:** atomic via `tempfile.mkstemp()` + `os.replace()`

### 3.2 Metadata cache (`data/scan_cache/metadata.json`)

Lightweight per-ticker dict loaded entirely into memory at startup (single JSON load, ~2–3 MB for 1600 tickers). Used exclusively for Pass 1 — **no parquet reads in Pass 1**.

```json
{
  "AAPL": {
    "last_close":    213.50,
    "avg_vol_20d":   52_000_000,
    "dollar_vol":    11_126_000_000,
    "above_sma50":   true,
    "last_updated":  "2026-03-24",
    "stale":         false
  },
  "SPY": { ... },
  ...
}
```

**`above_sma50`** is stored in metadata to support breadth computation in Pass 1 without reading parquet files (see Section 4.3).

**Concurrent write safety:** An `asyncio.Lock` protects the in-memory metadata dict when multiple I/O workers call `put()` concurrently. The JSON is serialized once after all workers complete — not on every individual ticker update.

Updated atomically after every incremental fetch batch completes.

### 3.3 Public interface

```python
class CacheStore:
    def __init__(self, cache_dir: str = SCAN_CACHE_DIR): ...

    # Startup — no parquet reads
    def preload_index(self) -> None
        """Load metadata.json into memory."""

    # Pass 1 (metadata only — no disk I/O beyond startup)
    def get_meta(self, ticker: str, default: Optional[dict] = None) -> Optional[dict]
        """Return metadata dict for ticker, or default (None) if unknown."""

    # Pass 2 data access
    def get(self, ticker: str) -> Optional[pd.DataFrame]
        """Read-through: memory-first → parquet → None."""

    def put(self, ticker: str, df: pd.DataFrame) -> None
        """Write to memory + parquet. Updates in-memory metadata dict (lock-protected)."""

    # Incremental fetch
    async def fetch_incremental(self, ticker: str, semaphore) -> Optional[pd.DataFrame]
        """Load full parquet, fetch missing days, append, save. Returns updated df or None."""

    # Cache health
    def is_fresh(self, ticker: str) -> bool
        """True if last_updated within PRICE_CACHE_FRESH_DAYS business days."""

    def is_excluded(self, ticker: str) -> bool
        """True if last_updated > PRICE_CACHE_MAX_STALE_DAYS trading days ago."""

    def cache_hit_rate(self) -> float
        """Fraction of tickers served from memory vs disk vs network this session."""
```

### 3.4 Incremental fetch logic (strict)

```
fetch_incremental(ticker):
  1. Attempt to load full parquet from disk
     └─ On parse error / corruption: log warning → full download path
  2. last_date = df.index[-1].date()
  3. if last_date >= today - PRICE_CACHE_FRESH_DAYS business days:
       return df    # already fresh — no network call
  4. Fetch: yf.Ticker(ticker).history(start=last_date, end=today + 1 day)
     └─ Yields only bars yfinance has — handles weekends/holidays automatically
  5. If new_data is empty → return existing df (market closed / holiday gap)
  6. Concat existing df + new_data
  7. Sort index ascending
  8. Deduplicate on index: keep last occurrence (handles partial last-bar re-fetches)
  9. Handle partial last trading day: if last bar's date == today AND
     last bar's Volume == 0 → drop it (intraday incomplete bar)
 10. Atomic write back to parquet
 11. Update metadata dict entry (lock-protected):
       last_close, avg_vol_20d (rolling 20d), dollar_vol, above_sma50, last_updated
```

**Note on parquet tail reading:** Full parquet files are read into memory then sliced — pandas/pyarrow does not support row-group pushdown for non-partitioned files. At ~50–200 KB per ticker file, reading 400 files ≈ 20–80 MB total I/O, completed in under 2 seconds on any SSD. This is acceptable.

### 3.5 Staleness policy

| Condition | Action |
|-----------|--------|
| `last_updated` ≤ `PRICE_CACHE_FRESH_DAYS` (2) biz days | Fresh — use as-is, skip network |
| `last_updated` 3–5 biz days | Stale — attempt incremental update; proceed if successful |
| `last_updated` > `PRICE_CACHE_MAX_STALE_DAYS` (5) biz days | Attempt incremental update first; exclude only if update also fails |
| No cache file at all | Full download; exclude only if that fails |

**Rationale for "attempt update before exclude":** A file that is 6 days old is treated the same as a missing file — both get a download attempt. Excluding without attempting is worse behavior.

Setup metadata gets `"stale_data": true` only when stale data was used after a failed update attempt.

### 3.6 Batch download resilience

Three-tier retry in new helper `_batch_download_with_fallback(tickers, semaphore)`:

```
Tier 1: yf.download(batch of 100, timeout=30)
  └─ TimeoutError or Exception:
       Tier 2: split into 4 × 25-ticker sub-batches, retry each independently
            └─ sub-batch fails:
                 Tier 3: fetch each ticker individually via existing _fetch() (backoff + retries)
                      └─ all retries exhausted:
                           → use stale cache (set stale=True in metadata)
                           → exclude only if no cache at all
```

---

## 4. Two-Pass Scan

### 4.1 Pass 1 — Fast filter (metadata only, zero network)

**Input:** All `ACTIVE_UNIVERSE` tickers (~1600)
**Data source:** `cache_store.get_meta(ticker)` — in-memory metadata dict only
**Target output:** 200–400 survivors
**Expected time:** 2–5 seconds

Filters applied in order (cheapest first):

| Step | Filter | Source | Threshold |
|------|--------|--------|-----------|
| 1 | Metadata exists | metadata dict | drop if None |
| 2 | Not excluded-stale | `is_excluded()` | drop if > 5 biz days stale (after update attempt) |
| 3 | Price floor | `metadata.last_close` | ≥ `PASS1_MIN_PRICE` ($12) |
| 4 | Volume floor | `metadata.avg_vol_20d` | ≥ `PASS1_MIN_AVG_VOLUME` (1M) |
| 5 | Dollar volume | `metadata.dollar_vol` | ≥ `PASS1_MIN_DOLLAR_VOLUME` ($25M) |
| 6 | RS pre-filter | `rs_rank_cache.json` | ≥ `PASS1_MIN_RS_RANK` (45) |

No parquet reads. No yfinance calls. No indicator computation.

### 4.2 Discovery candidate whitelisting

Before adaptive tightening, the discovery layer checks are applied to all tickers using metadata:
- RS rank between 60–70 (from RS cache)
- `last_close` within 3% of 52-week high (requires `high_52w` in metadata — see Section 3.2 addition)
- Recent volume expansion (requires `vol_ratio_5d` in metadata — see Section 3.2 addition)

Tickers passing discovery criteria are added to a `_discovery_set` and bypass Pass 1's RS floor. This preserves the existing discovery layer behavior.

**Additional metadata fields for discovery:**
```json
{
  "TICKER": {
    ...existing fields...,
    "high_52w":    220.10,
    "vol_ratio_5d": 1.8
  }
}
```
These are computed from the tail of the parquet file during `put()` and stored cheaply.

### 4.3 Breadth computation from full-universe metadata

**Problem:** Engine 0 needs breadth (% of full universe above SMA50) — not just survivors.
**Solution:** Compute breadth during Pass 1 from `metadata.above_sma50` across ALL tickers in `ACTIVE_UNIVERSE` (not just survivors), before the filter loop begins. This is O(n) over the metadata dict — ~1 ms, negligible.

```python
# Before filter loop
above_sma50_count = sum(1 for t in active_universe if cache_store.get_meta(t, {}).get("above_sma50"))
breadth_pct = above_sma50_count / len(active_universe)
```

`above_sma50` in metadata is updated whenever `put()` is called (i.e., after every incremental fetch). On cold start (no metadata), it defaults to 0.5 (neutral) — same as today's fallback.

This replaces `compute_universe_breadth(_ticker_cache, tickers)` for the breadth component. The H/L ratio requires 52-week highs/lows, also computed from metadata (`high_52w` stored above).

### 4.4 Adaptive threshold tightening

If `len(survivors) > PASS1_MAX_SURVIVORS` (400) after standard filters, tighten in steps:
```
Step 1: raise RS floor from 45 → 50
Step 2: raise dollar_volume from $25M → $40M
Step 3: raise RS floor from 50 → 55
(stop as soon as survivors ≤ 400)
```
Discovery candidates (whitelisted in Section 4.2) are **exempt from adaptive tightening** — they are re-added after tightening runs.

Log which thresholds were tightened and final survivor count.

### 4.5 Pass 2 — Heavy processing (compute worker pool)

**Input:** Pass 1 survivors (~200–400) with fresh incremental data

**Pipeline order per ticker — matches live scanner exactly:**

```
1. vitality check        is_price_vital()                  — flatline/zombie skip
2. RS rank gate          _rs_rank_map.get(ticker)          — flat threshold (see §4.5a)
3. compute_indicators    compute_indicators(df, spy_df)    — full indicator suite
4. rs_score gate         ind.rs_score >= _LIVE_PARAMS.rs_threshold  — O'Neil RS score floor
5. liquidity gate        passes_liquidity(df)              — 50d median vol (uses raw df)
6. earnings blackout     in_earnings_blackout(...)
7. engines 1–9           (unchanged)
```

**§4.5a RS rank gate — single constant (not regime-specific):**
The per-ticker gate in `_process()` uses `RS_RANK_MIN_PERCENTILE` (70) — a single flat constant regardless of regime — exactly as the live scanner does at `main.py` line 1346. This is distinct from the regime-conditional scoring applied later in `score_and_filter_setups()`. Gate is bypassed in DEFENSIVE regime and for discovery candidates, same as today.

**§4.5b rs_score gate (step 4):**
After `compute_indicators`, the live scanner checks `ind.rs_score >= _LIVE_PARAMS.rs_threshold` (`BACKTEST_RS_THRESHOLD_DEFAULT = -0.01219`). This is a computed O'Neil RS score (stock return minus SPY return over rolling windows) — separate from the percentile rank gate in step 2. Tickers whose RS score falls below the threshold are skipped before reaching the engines. This gate must be preserved in Pass 2 to maintain identical output quality.

**Note on Pass 1 vs Pass 2 volume thresholds:** Pass 1 uses `metadata.avg_vol_20d` as a fast proxy. Pass 2 uses `passes_liquidity()` with the 50-day median from the full DataFrame. Some tickers that barely pass Pass 1's 20d check may fail Pass 2's stricter 50d check — this is intentional and correct. The dual-check eliminates weak tickers early (Pass 1) while retaining the authoritative gate for setups (Pass 2).

---

## 5. Worker Queue Design

Two separate worker pools, sized for their workload type.

### 5.1 I/O pool — incremental fetching

```python
IO_WORKER_COUNT  = SCAN_IO_WORKERS       # default 48, mostly waiting on network
QUEUE_MULTIPLIER = SCAN_QUEUE_MULTIPLIER  # default 2; maxsize = workers × 2

async def _run_io_phase(survivors, cache_store, semaphore):
    queue = asyncio.Queue(maxsize=IO_WORKER_COUNT * QUEUE_MULTIPLIER)
    workers = [asyncio.create_task(_io_worker(queue, cache_store, semaphore))
               for _ in range(IO_WORKER_COUNT)]
    for ticker in survivors:
        await queue.put(ticker)    # blocks when queue full → natural backpressure
    for _ in workers:
        await queue.put(None)      # poison pill
    await asyncio.gather(*workers)
```

### 5.2 Compute pool — Pass 2 processing

```python
# Cap at cpu_count×2 to avoid GIL-bound thread over-subscription
EFFECTIVE_COMPUTE_WORKERS = min(SCAN_COMPUTE_WORKERS, (os.cpu_count() or 4) * 2)

async def _run_compute_phase(survivors, ...):
    queue = asyncio.Queue(maxsize=EFFECTIVE_COMPUTE_WORKERS * QUEUE_MULTIPLIER)
    workers = [asyncio.create_task(_compute_worker(queue, ...))
               for _ in range(EFFECTIVE_COMPUTE_WORKERS)]
    for i, ticker in enumerate(survivors):
        await queue.put((ticker, i))
    for _ in workers:
        await queue.put(None)
    await asyncio.gather(*workers)
```

**GIL note:** `compute_indicators` runs via `loop.run_in_executor(None, ...)` (ThreadPoolExecutor). Because it is numpy/pandas (CPU-bound), the GIL limits true parallelism to physical cores. Capping at `cpu_count × 2` avoids scheduling overhead. The existing `asyncio.Semaphore(CONCURRENCY_LIMIT)` inside `_fetch()` is retained unchanged for HTTP request throttling.

---

## 6. RS Rank Cache Persistence

### 6.1 Storage format (`cache/rs_rank_cache.json`)
```json
{
  "_meta": {
    "computed_at":   "2026-03-24T09:15:00",
    "logic_version": "v3",
    "ticker_count":  412
  },
  "AAPL": 87.3,
  "NVDA": 92.1,
  ...
}
```

### 6.2 Logic version invalidation

```python
RS_LOGIC_VERSION = "v3"   # increment when O'Neil weights, formula, or lookback periods change
```

On cache load: if `_meta.logic_version != RS_LOGIC_VERSION` → cache is invalid → full recompute. Prevents silent stale-logic usage after a scoring change.

### 6.3 TTL + staleness-before-pass1

**Problem:** If the RS cache is 23h old, Pass 1 filters on near-stale ranks. A ticker that would pass the fresh rank map may be excluded in Pass 1 before the fresh map is computed at t2.

**Solution:** If cache age > `RS_RANK_CACHE_REFRESH_THRESHOLD` (20h = 83% of TTL), trigger a background recompute **before** Pass 1 runs. This adds ~20s on the rare scan that hits this window, but prevents correctness issues on volatile days. On most scans (cache < 20h old), this step is skipped entirely.

```python
# At start of _run_scan, before Pass 1:
if _rs_cache_age() > RS_RANK_CACHE_REFRESH_THRESHOLD:
    # Recompute using whatever data is already in memory/disk cache
    await _refresh_rs_cache(semaphore)  # ~20s, but rare
```

**Steady-state TTL flow:**
```
RS cache hit  (age < 20h, version matches) → Pass 1 + Pass 2 both use cached map → 0s
RS cache miss (age > 24h or stale) → full recompute after t1 fetch → ~20s
RS cache near-stale (20–24h) → refresh before Pass 1 → ~20s
```

---

## 7. Universe Builder Tightening

### 7.1 New filter thresholds

| Filter | Before | After | Rationale |
|--------|--------|-------|-----------|
| Min price | $10 | $12 | Remove low-priced tickers |
| Min avg volume | 500K | 1M | Better liquidity baseline |
| Min dollar volume | $0 (skipped) | $25M | Always enforced |
| Min ATR% | 2.5% (optional) | 2.5% (always) | Enforce; remove dead stocks |
| RS pre-filter | none | RS < 35 → exclude | Bottom third; conservative |

### 7.2 RS pre-filter behavior

- Reads `cache/rs_rank_cache.json` if exists and < 7 days old
- Excludes tickers with RS rank < 35 (bottom ~35th percentile)
- If cache missing or > 7 days old: skip filter (safe fallback, slightly larger universe)
- This runs at universe-build time (every 48h+), not every scan

**Expected universe after filters:** ~700–900 tickers (down from ~1600)
**Pass 1 then reduces to:** 200–400

---

## 8. New Constants (`constants.py`)

```python
# ── Scanner disk cache (separate from WFO's data/price_cache/) ────────────
SCAN_CACHE_DIR               = "data/scan_cache"
PRICE_CACHE_FRESH_DAYS       = 2        # skip incremental if ≤ N biz days old
PRICE_CACHE_MAX_STALE_DAYS   = 5        # attempt update before excluding
SCAN_CACHE_METADATA_FILE     = "data/scan_cache/metadata.json"

# ── RS rank cache ──────────────────────────────────────────────────────────
RS_RANK_CACHE_TTL               = 86400   # 1 day in seconds
RS_RANK_CACHE_FILE              = "cache/rs_rank_cache.json"
RS_RANK_CACHE_REFRESH_THRESHOLD = 72000   # 20h: refresh before Pass 1 if older

# ── Pass 1 thresholds ──────────────────────────────────────────────────────
PASS1_MIN_PRICE              = 12.0
PASS1_MIN_AVG_VOLUME         = 1_000_000
PASS1_MIN_DOLLAR_VOLUME      = 25_000_000
PASS1_MIN_RS_RANK            = 45
PASS1_MAX_SURVIVORS          = 400       # adaptive tightening trigger

# ── Worker pools ───────────────────────────────────────────────────────────
SCAN_IO_WORKERS              = 48        # I/O phase (incremental fetch)
SCAN_COMPUTE_WORKERS         = 32        # compute phase (capped at cpu_count×2 at runtime)
SCAN_QUEUE_MULTIPLIER        = 2         # queue maxsize = workers × this

# ── Universe builder (tightened) ──────────────────────────────────────────
UNIVERSE_MIN_PRICE           = 12.0      # was 10.0
UNIVERSE_MIN_AVG_VOLUME      = 1_000_000 # was 500_000
UNIVERSE_MIN_DOLLAR_VOL      = 25_000_000 # was 0
UNIVERSE_RS_FLOOR            = 35        # exclude bottom 35% RS (if cache exists)
```

---

## 9. Observability — Per-Phase Timing

Added to `_scan_state["engine_stats"]["timing"]` (exposed via existing `/api/scan-status`):

```python
"pass1_filter_s":    0.0,    # Pass 1 metadata filter
"fetch_s":           0.0,    # incremental fetch phase
"rs_cache_s":        0.0,    # RS map (0.0 if cache hit, ~20s if recomputed)
"pass2_s":           0.0,    # Pass 2 indicators + engines
"cache_hit_rate":    0.0,    # fraction served from memory/disk vs network
"pass1_survivors":   0,      # tickers that passed Pass 1
"pass1_thresholds":  {},     # any adaptive tightening applied this scan
```

No API changes required — these fields integrate into the existing `engine_stats.timing` dict.

---

## 10. Cold-Start Behavior

On first run (no `data/scan_cache/` directory):
1. `CacheStore.preload_index()` finds no metadata — returns empty index
2. All ACTIVE_UNIVERSE tickers fail Pass 1 step 1 (no metadata)
3. They are re-queued for full download before Pass 1 re-runs
4. Full downloads populate the cache; Pass 1 then runs normally
5. First cold-start runtime: ~5–8 minutes (full downloads for all tickers)
6. All subsequent runs: ~2–3 minutes (incremental)

**WFO cache seeding:** The WFO system's `data/price_cache/` flat files are a separate format (potentially different column names, different period) and are **not seeded** into the scanner cache. Cold start requires fresh downloads. This is a deliberate simplification — scanner data must be owned by the scanner cache.

---

## 11. What Does NOT Change

- All engine logic (Engines 1–9): **unchanged**
- `compute_indicators()`: **unchanged**
- `score_and_filter_setups()`: **unchanged**
- All scoring weights and thresholds: **unchanged**
- All DB schema and batch save logic: **unchanged**
- All API endpoints: **unchanged**
- `filters.py` (`passes_liquidity`, `in_earnings_blackout`): **unchanged**
- `backtest_engine.py`, `wfo_engine.py`, `wfo_cache.py`: **unchanged**
- Frontend: **no changes required**

---

## 12. Expected Runtime Breakdown

| Phase | Before | After (warm cache) | After (cold start) |
|-------|--------|-------------------|-------------------|
| Bulk prefetch 1600 × 252 days | 5–8 min | ~10–20s incremental | ~5–8 min full |
| Pass 1 filter | — | ~2–5s | ~2–5s (after cold download) |
| RS rank map | ~20–30s | ~0s (TTL hit) | ~20s (recompute) |
| Pass 2: 200–400 tickers | (was 1600) | 4–8× less work | 4–8× less work |
| **Total** | **10–15 min** | **~2–3 min** | **~5–8 min** |

The dominant saving is incremental fetch: 1–3 days × 200–400 tickers instead of 252 days × 1600 tickers.
