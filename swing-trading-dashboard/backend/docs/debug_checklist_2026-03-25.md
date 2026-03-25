# Scanner System Debug Checklist
**Generated:** 2026-03-25
**Scope:** Full backend scanner — data ingestion through DB save

---

## 1. Configuration / Constants (`constants.py`)

**What this part is responsible for**
Single source of truth for all thresholds, TTLs, weights, and toggle flags used across the entire system.

**What can go wrong**
- `CONCURRENCY_LIMIT = 64` has a comment saying "Backtest reads local parquet only — no network, safe to run high". But `_semaphore` is initialized from this value on startup and is used by the live scanner's `_fetch()` to gate yfinance network calls. 64 concurrent live network requests could trigger rate-limiting.
- `RS_RANK_MIN_PERCENTILE = 70` is a "legacy alias — kept for backtest/WFO compatibility" but is still the value used in `_process`'s RS gate. If someone changes the regime-specific constants (`RS_RANK_MIN_PERCENTILE_AGGRESSIVE = 65`, `RS_RANK_MIN_PERCENTILE_SELECTIVE = 70`) expecting the live gate to change, it won't — the gate uses the legacy alias.
- `SELECTIVE_SETUP_WEIGHTS` contains `PULLBACK: 0.5`. If `SELECTIVE_HARD_FILTER = False` (current), this penalty is applied as a multiplier in scoring but doesn't hard-block. The comment says "effectively blocks in soft mode (max score=100 × 0.5 = 50 < 70)". This is only true if the setup scores 100 — any scoring bonus could push it above 70.
- `SCAN_TIMEOUT_SECONDS = 600` exists but is not checked anywhere in the actual scan loop. It has no enforcement.

**What to verify during debugging**
- Confirm `CONCURRENCY_LIMIT` value matches the intended live-scanner limit (not a backtest value).
- Confirm `RS_RANK_MIN_PERCENTILE` value is what you actually want in production. There are now three RS thresholds in the file (70, 65, 70).
- Verify `SELECTIVE_HARD_FILTER` is set as intended.
- Check that weight components still sum to 100: `RS_RANK(25) + RR(17) + VOL(16) + REGIME(15) + TREND_DUR(10) + COILING(7) + SECTOR(5) + SUPPORT_TIER(5) + QUALITY(5) = 105`. The comment says "sum of primary weights = 100" but they add to 105.

**Performance risks**
- None directly, but misconfigured `CONCURRENCY_LIMIT` triggers yfinance bans that cascade into slow scans via retries.

**Data correctness risks**
- Stale Optuna-tuned values (VCP_TIGHT_RANGE_5D_PCT, ATR_STOP_MULTIPLIER, CCI_STRICT_FLOOR, etc.) sourced from a 2023–2024 in-sample window. May degrade forward of that window.

---

## 2. Universe Builder (`universe_builder.py`, `tickers.py`)

**What this part is responsible for**
Builds the 800+ ticker list from SEC EDGAR or falls back to the static `tickers.py` list. Refreshes every 48 hours during a scan.

**What can go wrong**
- Universe rebuild is triggered inside `_run_scan` with a 20-minute timeout. If the rebuild hangs partway through, the scan proceeds with a stale universe — but the rebuild has already mutated `ACTIVE_UNIVERSE` and `SECTORS` globals. This can cause inconsistent state if the old and new universes differ substantially.
- `_universe_stale = _universe_age_h >= 48` — there is no lower bound check. If `active_universe.json` has 0 entries (corrupt write) and is less than 48 hours old, it will be used as-is.
- `UNIVERSE_MIN_SIZE = 800` / `UNIVERSE_MAX_SIZE = 2500` are logged as warnings, not hard stops.
- The fallback (`tickers.py`) is a static list that can include delisted or renamed tickers.

**What to verify during debugging**
- Check `active_universe.json` exists and has a sensible size (> 800).
- Confirm `SECTORS` dict covers the tickers in `ACTIVE_UNIVERSE` — a ticker with no sector mapping defaults to `"Unknown"` which scores out-of-tier in sector scoring.
- Verify universe file mtime is accurate (file system clock skew can cause unexpected rebuilds).

**Performance risks**
- Universe rebuild happening inside a scan call can add 5–20 minutes silently.

**Data correctness risks**
- Stale `active_universe.json` may include delisted tickers, causing yfinance fetch failures and backoff delays that eat up semaphore slots.

---

## 3. Dual Cache Architecture — Critical Design Risk

**What this part is responsible for**
Two completely separate caches exist in parallel:
- `_ticker_cache: dict` — in-memory `{ticker: (timestamp, df)}`, populated by `_fetch()` and `_prewarm_price_cache()`. Lives only for the server session.
- `CacheStore (_cache_store)` — disk-persisted parquet files + `metadata.json`. Populated by `bulk_fetch_incremental` and `fetch_incremental`.

**What can go wrong**
- The prewarm at startup (`_prewarm_price_cache`) populates `_ticker_cache` only. The scan's I/O phase (`_run_io_phase`) populates `CacheStore._mem` only. These two are completely independent.
- After the I/O phase, `main.py` manually bridges them at lines 1417–1420 by copying from `CacheStore` into `_ticker_cache`. This bridge only covers `_survivors` (~83 tickers), not the full 809-ticker universe.
- `compute_rs_rank_map` is called at line 1392 (before I/O phase) with `_ticker_cache`. If `_ticker_cache` is cold (restart), the map returns empty — AND saves an empty cache file to disk.
- `compute_rs_rank_map` is called again at line 1424 (after I/O phase) with only `_survivors` in `_ticker_cache`. The rank map is computed on ~83 tickers, not the full 809 — percentile rankings are relative to the survivor set, not the full universe.

**What to verify during debugging**
- After a scan completes, check `rs_rank_cache.json` — `ticker_count` should equal the number of survivors (~83), NOT 809.
- Verify the bridge at lines 1417–1420 runs before `compute_rs_rank_map` on line 1424.
- On every restart, `_ticker_cache` starts empty. The first scan after a cold restart will have an empty RS rank map unless the prewarm completes first.

**Performance risks**
- On cold start: prewarm downloads ~809 tickers via `_batch_download_sync` (yf.download). This competes with the scan's I/O phase for network bandwidth if the user triggers a scan immediately.
- Two separate download pipelines means 809 tickers can be downloaded twice in the worst case (once by prewarm into `_ticker_cache`, once by I/O phase into `CacheStore`).

**Data correctness risks**
- RS rank percentiles are computed on the survivor set (~83 tickers), not the full universe. A stock ranked 70th out of 83 survivors is not the same as 70th percentile of 809 stocks.

---

## 4. CacheStore — Disk Cache (`cache_store.py`)

**What this part is responsible for**
Persistent OHLCV parquet cache, sharded by first letter of ticker. Provides `get()` (memory → parquet fallback), `put()`, `fetch_incremental()`, `bulk_fetch_incremental()`.

**What can go wrong**
- `_normalise()` calls `df.index.tz_localize(None)` to strip timezone but only when `df.index.tz is not None`. Mixed-type indexes may not trigger this check correctly.
- `fetch_incremental` detects a "partial last bar" by checking `Volume == 0` on the last row. Some tickers legitimately have 0 volume on the last day (thin ADRs). These bars will be silently dropped on every refresh.
- `bulk_fetch_incremental` calls `self._flush_metadata()` only after all workers complete. If the service is restarted mid-prewarm (SIGKILL), `metadata.json` will not reflect the tickers processed in that run.
- `is_excluded` uses `PRICE_CACHE_MAX_STALE_DAYS = 5` business days. A ticker excluded Monday won't be retried for 5 biz days even if exclusion was from a transient yfinance error.
- `_update_meta_sync` computes `avg_vol_20d` using `.median()`. The `OPTIONS_MIN_ADV` check in Engine 7 uses `.mean()`. The two liquidity checks use different volume statistics.

**What to verify during debugging**
- Check that `metadata.json` exists and has a reasonable ticker count after a completed scan.
- Verify parquet files exist in shard directories (`data/scan_cache/A/`, `B/`, etc.).
- Confirm `last_updated` dates in `metadata.json` are recent (today or yesterday).
- Check if any tickers are marked `"stale": true` — these are returned from cache but their data is outdated.

**Performance risks**
- `_load_parquet` is called on every `get()` that misses `_mem`. On cold start after restart, `compute_rs_rank_map` can trigger 809 parquet reads if `_mem` is empty.
- `bulk_fetch_incremental` with `workers=48` and `CONCURRENCY_LIMIT=64` means up to 48 concurrent yfinance requests with no wait.

**Data correctness risks**
- `_normalise` deduplicates columns keeping the last occurrence: `df.loc[:, ~df.columns.duplicated()]`. This silently discards `Adj Close` if it appears before `Close` in column order.
- `PRICE_CACHE_FRESH_DAYS = 2` business days. Data 2 biz days old is treated as fresh and won't be updated.

---

## 5. Pass 1 — Metadata Filter (`_pass1_filter` in `main.py`)

**What this part is responsible for**
Fast pre-filter using only `metadata.json` (no DataFrames loaded). Cuts 809 tickers down to ~80–400 survivors before any I/O.

**What can go wrong**
- Cold-start behavior: when `meta is None`, the ticker is passed through unconditionally. On the first scan after a restart with no populated metadata, ALL 809 tickers pass through to the I/O phase.
- Adaptive tightening: `(rs_cache.get(t) or 0) >= rs_step` treats RS=0.0 the same as missing RS (both become 0). A valid score of exactly 0.0 is incorrectly treated as missing.
- `_identify_discovery_candidates` only identifies tickers already in the RS cache. On cold start when `rs_cache` is empty, no discovery candidates are identified even if breakout stocks with RS 60–70 are in the universe.
- Pass 1 RS floor is `PASS1_MIN_RS_RANK = 45` but the RS gate in `_process` uses `RS_RANK_MIN_PERCENTILE = 70`. Tickers with RS 45–69 pass Pass 1 but are dropped in `_process` — they go through the full I/O phase and indicator compute for nothing.

**What to verify during debugging**
- Log "Pass 1 complete: 809 → N survivors" — N should be 80–400 for a warm scan. N = 809 means cold start or empty metadata.
- Check "Pass 1 adaptive tighten" log lines — these trigger when survivors > 400.
- Confirm `_rs_for_pass1` is not an empty dict — if empty, RS filtering in Pass 1 is bypassed for all tickers.

**Performance risks**
- When `_rs_for_pass1` is empty (cold start or failed RS cache), Pass 1 cannot filter by RS. Combined with the cold-start `meta is None` pass-through, ALL 809 tickers survive and go through a full I/O fetch.

**Data correctness risks**
- Pass 1 uses RS rank from the cache written by the previous scan (potentially hours old). A stock that was RS 40 yesterday but surged to RS 80 today would be filtered unless the RS cache has been refreshed.

---

## 6. RS Rank Cache (`scoring.py`, `cache/rs_rank_cache.json`)

**What this part is responsible for**
Computes O'Neil RS percentile for every ticker in the survivor set, caches to JSON with a 24h TTL. Used by Pass 1, the RS gate in `_process`, and setup scoring.

**What can go wrong**
- **Double-call problem**: `compute_rs_rank_map` is called at line 1392 (before I/O phase, result discarded) and again at line 1424 (after I/O phase, result stored). The first call with an empty `_ticker_cache` writes an empty cache file to disk. The `ticker_count == 0` guard prevents using an empty cache on the second call, but a partial cache (e.g., 50 tickers ranked of 83) would pass the guard and be used as-is.
- The first call at line 1392 only triggers when `_rs_cache_age_seconds > 20h`. If the cache is less than 20h old, the first call is skipped — but the existing cache could be from a previous failed scan with partial data.
- `RS_LOGIC_VERSION = "v3"` is hardcoded. If scoring logic changes but the version is not incremented, stale cache values will be used silently.
- The rank percentile is computed on `len(raw_scores)` tickers passed in. With only ~83 survivors, percentile scores are relative to that small set, not the full 809-ticker universe.

**What to verify during debugging**
- `cat cache/rs_rank_cache.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['_meta'])"`
  - `ticker_count` should be > 0 after any completed scan
  - `computed_at` should be recent
  - `logic_version` should match `RS_LOGIC_VERSION` in `scoring.py`
- Verify `_rs_cache_valid` returns False for a cache with `ticker_count == 0`.
- Confirm the RS rank cache is populated AFTER the I/O phase (post-survivors), not before.

**Performance risks**
- `compute_rs_rank_map` runs synchronously (not in executor). With 809 tickers it iterates all of them, calling `ticker_cache.get(t)` for each — triggering 809 parquet reads from disk if `_mem` is cold.

**Data correctness risks**
- RS percentile computed on ~83 survivors produces scores not comparable to the full-universe percentile referenced in `RS_RANK_MIN_PERCENTILE = 70`.

---

## 7. Engine 0 — Market Regime (`engines/engine0.py`)

**What this part is responsible for**
7-factor score (0–100) determining AGGRESSIVE / SELECTIVE / DEFENSIVE regime. Factors include SPY MAs, EMA slope, breadth, 52w H/L ratio, VIX.

**What can go wrong**
- Breadth (f5) and H/L ratio (f6) are computed from `_compute_breadth_from_metadata`. On cold start when `total == 0`, defaults `(0.5, 0.5)` are used — these contribute 30 pts artificially, inflating the regime score.
- VIX data (f7) is fetched separately by `engine0.py` using `yf.download("^VIX", ..., progress=False)`. In yfinance 1.2.0, `yf.download()` still accepts `progress=False` but behavior may change in future versions.
- `REGIME_SELECTIVE_THRESHOLD = 59` is Optuna-tuned from a 2023–2024 in-sample window.
- Live regime uses 7/7 factors (max 100 pts). Backtest regime in `filters.py` uses 4/7 factors (max 60 pts). The proportional scaling (`_BACKTEST_REGIME_SELECTIVE = round(59/100 × 60) = 35`) means backtest and live SELECTIVE thresholds are not equivalent.

**What to verify during debugging**
- Log "Engine 0: REGIME score=N" — if N = 16, regime is DEFENSIVE.
- Check if `breadth_pct` in the Engine 0 log is 0.5 (default from empty metadata) vs a real value.
- Confirm VIX data is being fetched correctly on the VPS.

**Performance risks**
- Engine 0 calls `yf.download("SPY", ...)` and `yf.download("^VIX", ...)` independently — additional network calls beyond the SPY fetch at line 1364 of `_run_scan`.

**Data correctness risks**
- If VIX fetch fails, the VIX component (10 pts) defaults to 0, making regime appear more DEFENSIVE.

---

## 8. Pass 2 — Per-Ticker Processing (`_process` in `main.py`)

**What this part is responsible for**
Runs full indicator + engine pipeline for each survivor. Each `_process` coroutine: `_fetch` → vitality → RS gate → `compute_indicators` → liquidity gate → earnings gate → Engines 1–9.

**What can go wrong**
- `_process` calls `_fetch(ticker, semaphore=semaphore)` as its first step. Since `_ticker_cache` was populated at lines 1417–1420, this is normally a cache hit. But if `CacheStore.get(_t)` returned None for a ticker (I/O phase failure), `_fetch` will attempt a live yfinance download here — inside the compute worker pool, acquiring the semaphore and blocking other workers.
- `collected_setups` is a nonlocal list shared across all 32 async workers. Workers append to it without a lock. In CPython, `list.append()` is GIL-protected, but this is an implementation detail — not a language guarantee.
- `loop = asyncio.get_event_loop()` is called inside `_process` (deprecated in Python 3.10+). Should be `asyncio.get_running_loop()`.
- Engine 7 (`scan_options_catalyst`) is called via `loop.run_in_executor(None, scan_options_catalyst, ticker, df)`. Inside, `yf.Ticker(ticker).options` and `t.option_chain(expiry)` are called synchronously — completely outside the semaphore, unconstrained. With 32 workers all calling Engine 7 concurrently, up to 32 simultaneous yfinance options chain requests are made.
- If `_process` raises an exception after adding a setup to `collected_setups` but before completing, the partial setup remains in the list.

**What to verify during debugging**
- Check if any tickers triggered live `_fetch` downloads inside `_process` (look for "Fetch %s: empty/None data" logs during the compute phase).
- Confirm Engine 7 is being called for the expected number of tickers (log line "OPTIONS TICKER ...").
- Check that `collected_setups` entries all have required fields before batch save.

**Performance risks**
- Engine 7 makes 2–5 yfinance calls per ticker (options + option_chain per expiry + IV term structure). With 32 workers, up to 32 × 5 = 160 concurrent unconstrained yfinance requests.
- Each `_process` call makes ~8 sequential `run_in_executor` calls. With 32 workers, up to 256 executor tasks can be queued against a thread pool of 6 threads (min(32, cpu+4) on VPS).

**Data correctness risks**
- `spy_df_full` is fetched once at scan start and shared across all tickers. If the SPY fetch returns < 252 bars, RS values will be incorrect for all tickers.

---

## 9. Compute Indicators (`compute_indicators`, `indicators.py`)

**What this part is responsible for**
Computes EMA8/20, SMA50/200, ATR, CCI, volume SMA, RS line values, blue dot detection, and other derived fields from the raw OHLCV DataFrame.

**What can go wrong**
- Indicators use `Adj Close` for price calculations; raw `Close` is used for candles in the frontend. If `Adj Close` is missing from the DataFrame, the fallback to `Close` is inconsistent between indicators and engines — RS line and candle rendering use different price series.
- EMA/SMA with `min_periods=length` returns NaN for the first `length` bars. If a ticker has exactly 60 bars (MIN_CANDLES_FOR_ANALYSIS), indicators requiring 50+ bars will have very few valid values.
- CCI's `mean_dev` uses `.apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)` — pure Python per window, not vectorized. Slow but not critical for single tickers.

**What to verify during debugging**
- Verify `Adj Close` column exists in DataFrames returned from CacheStore.
- Check that DataFrames have at least `MIN_CANDLES_FOR_RS = 252` bars for tickers where RS blue dot is expected.

**Performance risks**
- CCI computation is O(n × window) due to the `.apply()`. Adds up across 83 tickers but not the primary bottleneck.

**Data correctness risks**
- `compute_indicators` runs inside `run_in_executor` — it must be thread-safe (no shared mutable state). Verify there are no module-level caches written inside the function.

---

## 10. Strategy Engines (Engines 1–6, 8, 9)

**What this part is responsible for**
Each engine is a (mostly) pure function taking a ticker, DataFrame, and zones as inputs and returning a setup dict or None.

**What can go wrong**
- **Engine 1 (KDE S/R Zones)**: zones are computed per ticker and reused by Engines 2, 3, 6, 8, 9. If Engine 1 returns an empty list, all downstream engines with `if zones:` guards are skipped silently with no log line.
- **Engine 2 (VCP)**: `if True:` guard at line 1631 is a placeholder — was presumably intended to be gated on regime at some point.
- **Engine 3 (Pullback)**: relaxed scan uses a lambda closure `lambda: scan_relaxed_pullback(ticker, df, ...)`. If `ticker` or `df` were mutated after the lambda is defined but before execution, the closure would capture mutated values. In the current asyncio context there is no mutation, but this is a fragile pattern.
- **Engine 6 (RES_BREAKOUT)**: `_brk_regime_ok = True` immediately followed by `if zones and _brk_regime_ok:` — the flag is hardcoded True and serves no purpose. Presumably intended to be wired to the regime but never was.
- **Engine 7 (Options)**: Individual `t.option_chain(expiry)` calls inside the executor have no individual timeout. A single hanging expiry call blocks one executor thread indefinitely.
- **Engines 8, 9**: `if zones:` check prevents execution on empty zones, with no log. A ticker with strong HTF or LCE setup but no KDE zones is silently skipped.

**What to verify during debugging**
- Check if zones are populated for a representative sample of survivors.
- Verify Engine 6's `_brk_regime_ok` flag — confirm it is intentionally hardcoded True.
- Confirm Engine 7 has a reasonable timeout for each options chain request.

**Performance risks**
- Engine 7 can make up to `len(near_expiries)` option chain requests per ticker (typically 3–4 expiries in DTE 7–45), plus a second chain fetch for IV term structure. Total: up to 5 yfinance calls per ticker in Engine 7 alone.

**Data correctness risks**
- Engine 7 `_days_to_expiry` uses `date.today()` with no market timezone consideration. Options expiring the same Friday as the scan (run after market close) may appear with DTE=0 and be filtered out.
- `CCI_STRICT_FLOOR = -39.10` is Optuna-tuned from 2023–2024 data. In a different market regime this threshold could over-filter or under-filter pullback entries.

---

## 11. Worker Queue / Concurrency (`_run_compute_phase`, `_run_io_phase`)

**What this part is responsible for**
Two bounded async worker pools: `_run_io_phase` (48 I/O workers, disk/network) and `_run_compute_phase` (32 compute workers, CPU/engine logic).

**What can go wrong**
- `_run_compute_phase` uses `asyncio.Queue(maxsize=n_workers × SCAN_QUEUE_MULTIPLIER)`. With 32 workers and multiplier=2, queue capacity is 64. With 83 survivors, 64 tickers are queued immediately and 19 wait. The first 64 all compete for the thread pool simultaneously.
- Each `_process` coroutine makes sequential `run_in_executor` calls (indicators → engine1 → engine2 → ... → engine9). Executor calls within one ticker are sequential, not parallel. The event loop can switch to another worker while one is awaiting an executor result, but the executor itself serializes CPU work to `min(32, cpu+4)` = 6 threads on the VPS.
- There is no per-ticker timeout inside `_process`. A single hanging ticker (e.g., Engine 7 option chain request that never returns) holds a worker slot indefinitely.
- `SCAN_TIMEOUT_SECONDS = 600` is defined but never enforced.

**What to verify during debugging**
- Log "Per-ticker processing completed [N.Ns]" — with 32 workers and 83 tickers this should now be 5–15 seconds. >30 seconds suggests a stuck Engine 7 call or semaphore contention.
- Log "Incremental fetch complete [N.Ns]" — with warm parquet cache this should be < 5 seconds. >10 seconds indicates live yfinance network calls.
- If a scan hangs indefinitely (no completion log), suspect a stuck Engine 7 executor call.

**Performance risks**
- Engine 7 yfinance calls inside `run_in_executor` block thread pool threads. With 32 compute workers and 6 thread pool threads, 6 simultaneous Engine 7 calls saturate the entire thread pool — all other `run_in_executor` calls (indicators, other engines) queue up.

---

## 12. RS Gate in `_process` (`main.py` lines ~1543–1559)

**What this part is responsible for**
Skips tickers with RS rank below `RS_RANK_MIN_PERCENTILE` (70) before running the expensive indicator + engine pipeline.

**What can go wrong**
- Gate is bypassed when `not _rs_rank_map` (empty dict is falsy). On cold start, ALL tickers bypass the gate — meaning all ~83 survivors run through all 9 engines regardless of RS quality.
- Gate uses `_rs_rank_map` computed on ~83 survivors with relative percentiles. A ticker ranked 60th of 83 gets rank ~72 — it passes the gate. But among all 809 tickers it might actually be rank 40. The gate is not meaningful when computed on survivors only.
- Discovery candidates bypass the gate unconditionally, but `_discovery_tickers` is empty when the RS cache is empty (cold start). Both bypass conditions fail simultaneously on cold start — tickers bypass via the empty-map condition instead, which is correct behavior but for the wrong reason.

**What to verify during debugging**
- Confirm `_rs_rank_map` is non-empty before the gate runs.
- Log how many tickers are skipped by this gate per scan.
- Confirm `_discovery_tickers` is being populated (should be > 0 for most scans with warm RS cache).

---

## 13. Scoring (`scoring.py`, `score_and_filter_setups`)

**What this part is responsible for**
Computes a 0–100 score for each setup across 9 components, filters by minimum threshold (currently 0 — disabled), sorts descending.

**What can go wrong**
- Score component weights sum to 105, not 100 as documented: `RS_RANK(25) + RR(17) + VOL(16) + REGIME(15) + TREND_DUR(10) + COILING(7) + SECTOR(5) + SUPPORT_TIER(5) + QUALITY(5) = 105`. The `SCORE_WEIGHT_RS_QUALITY = 20` additive bonus is on top of this.
- `SELECTIVE_SETUP_WEIGHTS` applies a `0.5` multiplier to PULLBACK scores in SELECTIVE regime. With `_score_threshold = 0` (current), this multiplier has NO filtering effect — all PULLBACK setups in SELECTIVE are still shown regardless of score.
- `score_and_filter_setups` is wrapped in a fail-open try-except. If scoring raises an exception, ALL setups pass with no `setup_score` field populated. The frontend reading this field gets undefined/null.
- `_score_support_tier` looks up `support_source` field. If missing or unexpected value, defaults to 0 points with no warning.

**What to verify during debugging**
- Check that setup dicts have `setup_score` field populated after scoring.
- Verify `compute_setup_score` doesn't raise for any setup type.
- Confirm `SELECTIVE_SETUP_WEIGHTS` is applied only in SELECTIVE regime.

**Data correctness risks**
- Score is computed with `_rs_rank_map` values computed on survivors only — the RS rank component is inflated relative to true full-universe percentile rank.

---

## 14. Database Layer (`database.py`)

**What this part is responsible for**
SQLite schema management, async CRUD via aiosqlite. Key operations: `batch_save_setups` (single transaction), `save_sr_zones`, `save_scan_run`, `complete_scan_run`.

**What can go wrong**
- `DB_TIMEOUT = 10.0` — if `batch_save_setups` runs while the DB is locked, it raises after 10 seconds. Setups are silently never saved even though the scan completed.
- If the process dies between `batch_save_setups` and `complete_scan_run`, the scan has data in the DB but is not marked complete — the frontend may not show these results.
- `metadata` JSON column serialization: if any setup field is a numpy float64 or other non-JSON-serializable type, the entire batch save may fail silently.
- Zone saves (`save_sr_zones`) are called per-ticker inside `_process` — individual async DB calls, not batched. With 83 tickers × 5–10 zones each = 400–800 individual DB write calls during the compute phase.

**What to verify during debugging**
- After a completed scan, verify `scan_runs` table has a row with `completed = 1`.
- Check `scan_setups` has rows with the latest `scan_timestamp`.
- Verify `sr_zones` table is populated.
- If a scan completes with 0 setups saved, check for JSON serialization errors in logs.

**Performance risks**
- Zone saves are not batched — 400–800 individual aiosqlite calls during the compute phase, each acquiring and releasing the connection.

---

## 15. Error Handling / Retries

**What this part is responsible for**
`_fetch` retries with exponential backoff. Engines wrapped in per-engine try-except. Scoring is fail-open.

**What can go wrong**
- `_fetch` retry backoff: `FETCH_BACKOFF_BASE × (2 ** attempt)`. With `FETCH_BACKOFF_BASE = 5.0` and `FETCH_MAX_RETRIES = 4`, worst case a single ticker blocks its semaphore slot for `5 + 10 + 20 + 40 = 75 seconds`. With 10 bad tickers simultaneously, 10 of 64 semaphore slots are blocked for 75 seconds each.
- Engine exceptions are caught per-engine with `log.warning()`. A crash in Engine 1 (no zones) doesn't stop Engine 2 from running with empty zones — it just runs Engine 2 pointlessly.
- If an individual `t.option_chain(expiry)` call inside Engine 7's executor hangs (network timeout), it blocks an executor thread for the default requests library timeout (can be 30–300 seconds).

**What to verify during debugging**
- Check for "Fetch DROPPED" log lines — tickers that failed all retries consume `FETCH_BACKOFF_BASE × (2^0 + 2^1 + ... + 2^3) = 75s` of wall time each.
- Check for "Error processing %s" log lines in the compute phase.
- Verify Engine 7 exceptions are caught and not causing silent worker thread hangs.

---

## 16. APScheduler / Startup Lifecycle

**What this part is responsible for**
Schedules morning scan (7:30 AM ET), email (8:00 AM ET), prewarm (9:15 AM ET). Runs `_prewarm_price_cache` immediately on startup.

**What can go wrong**
- `run_prewarm_job` calls `asyncio.run(_prewarm_price_cache())` — this creates a new event loop in the APScheduler thread. `_ticker_cache` is a module-level dict shared between this thread and the FastAPI event loop thread. Concurrent writes are not thread-safe.
- The startup prewarm runs on the FastAPI event loop. The 9:15 AM scheduled prewarm runs via `asyncio.run()` in a background thread — a separate event loop. If both run simultaneously, they both write to `_ticker_cache` without locks.
- `run_morning_scan` calls `asyncio.run(_run_scan(...))` from an APScheduler thread. The scan accesses `_scan_state`, `_ticker_cache`, `_last_rs_rank_map`, and `collected_setups` — all shared globals — from that background thread.
- `_digest_cache_lock` is a `threading.Lock()` protecting `_digest_cache` between the scan and email jobs. Other shared state (`_scan_state`, `_ticker_cache`) uses no locks.

**What to verify during debugging**
- Confirm no two scans run simultaneously — check `_scan_state["in_progress"]` gate.
- Verify the startup prewarm completes before the first manual scan is triggered.

**Performance risks**
- Startup prewarm runs immediately and competes with any user-triggered scan within the first few minutes of startup. Both write to `_ticker_cache` concurrently without coordination.

---

## Summary: Top-Priority Debug Invariants

| # | What to check | Where | Expected invariant |
|---|--------------|-------|-------------------|
| 1 | RS rank cache `ticker_count` | `cache/rs_rank_cache.json` | > 0 after any completed scan |
| 2 | RS rank map size | Log "RS rank map: N tickers ranked" | N = survivors (~83), not 809 |
| 3 | Pass 1 survivors | Log "Pass 1 complete: 809 → N" | 80–400 warm; 809 = cold start |
| 4 | Scan completes | Log "Per-ticker processing completed" | Must appear; missing = worker hang |
| 5 | Scan marked complete in DB | `scan_runs` table | `completed = 1` for latest scan |
| 6 | Engine 7 yfinance calls | No current log | Risk: up to 32 × 5 = 160 unconstrained requests |
| 7 | Prewarm vs scan overlap | Startup log order | Prewarm should finish before scan runs |
| 8 | SPY data length | Log "SPY data fetched: N days" | N >= 252 for valid RS/regime |
| 9 | Metadata populated | `metadata.json` ticker count | ~809 tickers after first warm scan |
| 10 | Score weights | `constants.py` | Primary weights sum to 105, not 100 as documented |
| 11 | Zone saves performance | No current log | 400–800 individual DB calls per scan — not batched |
| 12 | `_rs_for_pass1` populated | Before Pass 1 runs | Non-empty dict; empty = no RS filtering in Pass 1 |
