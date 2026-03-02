# Expanded Universe + ATR Pre-Filter Design

**Date:** 2026-03-02

## Goal

Replace the hardcoded ~700-ticker list with a dynamically filtered 3000+ ticker universe (SEC EDGAR → ~5000 NYSE/Nasdaq candidates), applying three pre-filters before any engine runs: price ≥ $10, 50-day avg volume ≥ 500K, ATR%(14) ≥ 2.0%.

## Current State

| Component | Current behaviour |
|---|---|
| `tickers.py` | 700 hardcoded SP500 + Russell 1000 tickers |
| `universe_builder.py` | Has `filter_price_volume()` (price + volume, batch=100, delay=2s) and `build_universe()` |
| `main.py` | Loads `active_universe.json` once at startup; scan uses that global `ACTIVE_UNIVERSE` |
| Missing | ATR% filter; universe not rebuilt on each scan |

## Architecture

```
POST /api/run-scan
  └─► _run_scan() [background task]
        │
        ├─ 1. build_filtered_universe() [executor thread, ~2-4 min]
        │       ├─ fetch_sec_tickers()            SEC EDGAR → ~8000 US equities
        │       ├─ filter_ticker_patterns()        remove warrants/prefs/ETFs → ~5000
        │       ├─ filter_universe()               bulk yf.download 60d, apply 3 gates
        │       │    ├─ price ≥ $10
        │       │    ├─ avg_vol_50d ≥ 500K
        │       │    └─ ATR%(14) ≥ 2.0%           → ~400-900 survivors
        │       ├─ build_sector_map()
        │       └─ save_universe() → active_universe.json
        │
        └─ 2. per-ticker scan [existing pipeline, unchanged]
              uses freshly filtered universe
```

## Changes by File

### `constants.py`
Add two new constants:
```python
MIN_ATR_PCT = 2.0           # ATR(14)/Close*100 minimum for pre-filter
UNIVERSE_FILTER_BATCH_SIZE = 250   # Larger batches → fewer sleeps → faster
UNIVERSE_FILTER_BATCH_DELAY = 1.0  # Reduced from 2.0s
```

### `universe_builder.py`

**Rename `filter_price_volume()` → `filter_universe()`** and add `min_atr_pct` parameter.

The function already downloads via `yf.download(..., period="3mo")` which gives enough data for ATR(14) computation. Add ATR% computation using the same downloaded DataFrame — no extra network call.

ATR%(14) formula:
```python
tr = pd.concat([
    ticker_df["High"] - ticker_df["Low"],
    (ticker_df["High"] - ticker_df["Close"].shift(1)).abs(),
    (ticker_df["Low"]  - ticker_df["Close"].shift(1)).abs(),
], axis=1).max(axis=1)
atr14 = tr.rolling(14).mean().iloc[-1]
atr_pct = atr14 / last_close * 100
if atr_pct < min_atr_pct:
    continue
```

Increase `BATCH_SIZE` for this function to `UNIVERSE_FILTER_BATCH_SIZE = 250` to reduce total sleep time from ~100s to ~20s for 5000 candidates.

Update `build_universe()` signature to accept and pass through `min_atr_pct`. Update metadata `filters` dict to include `min_atr_pct`.

### `main.py`

Import `build_universe` and `save_universe` from `universe_builder`.

At the start of `_run_scan()`, before the per-ticker loop, add:
```python
# Rebuild universe (runs in executor to avoid blocking event loop)
log.info("Rebuilding universe...")
universe_dict = await loop.run_in_executor(
    _executor,
    lambda: build_universe()
)
save_universe(universe_dict, UNIVERSE_FILE)
tickers = universe_dict["tickers"]   # replace passed-in tickers arg
global SECTORS
SECTORS = universe_dict["sectors"]
```

This replaces the startup-only load with a per-scan rebuild. The `tickers` variable (which was `ACTIVE_UNIVERSE`) is now the freshly filtered list for this scan run.

The `?tickers=EQT,NVDA` debug override is preserved — if specific tickers are passed to the endpoint, universe rebuild is skipped.

### `tickers.py`
Untouched. Kept as emergency fallback if SEC EDGAR is unreachable.

## Performance

| Step | Time estimate |
|---|---|
| SEC EDGAR fetch | ~2s |
| Pattern filter | <1s |
| `filter_universe()` bulk download (5000 tickers, 250/batch) | ~90-120s |
| Sector map (cached, only new tickers) | ~0s after first run |
| Per-ticker scan (400-900 survivors × existing pipeline) | existing timing |

Total added overhead per scan: **~2 minutes** (vs current ~0s universe load).

## What Does NOT Change

- Engine logic (0-7) — untouched
- Database schema — untouched
- Frontend API responses — untouched
- `active_universe.json` format — untouched (backward compatible)
- `sectors.json` / sector caching — untouched
