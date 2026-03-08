# Universe & Pre-Scan Filtering Design

**Date:** 2026-03-07
**Status:** Approved

## Goal

Improve signal quality by expanding the stock universe to 1200–1500 names, tightening liquidity filters, introducing RS tier scoring, a 3-tier sector gate, and a discovery layer for emerging leaders.

---

## Section 1: Hybrid Universe Loader

**Primary source:** `universe_builder.py` → `active_universe.json`
**Fallback:** `tickers.py` → `SCAN_UNIVERSE` (~700 tickers)

### Loader logic (main.py startup)

```
Load active_universe.json
  ├─ Missing or unreadable          → use tickers.py + log WARNING
  ├─ Age > UNIVERSE_MAX_AGE_DAYS(7) → use tickers.py + log WARNING
  ├─ Age > UNIVERSE_WARN_AGE_DAYS(5)→ use active_universe.json + log WARNING (aging)
  └─ Fresh                          → use active_universe.json (normal)
```

### Sanity checks on loaded universe

- `len(tickers) < UNIVERSE_MIN_SIZE (800)` → log WARNING (filter may be too tight)
- `len(tickers) > UNIVERSE_MAX_SIZE (2500)` → log WARNING (filter may be too loose)

### active_universe.json metadata fields

Required by `universe_builder.build_universe()`:
- `generated_at` — ISO timestamp
- `ticker_count` — int
- `filters` — dict: `{min_price, min_avg_volume_50d, min_atr_pct, min_dollar_volume}`
- `build_time_seconds` — float

### New API endpoint

`POST /api/build-universe` — background task, triggers `build_universe()` with tightened constants. Returns `{job_id}`. No polling endpoint needed (operator-facing, one-shot).

---

## Section 2: Pre-Scan Filter Constants

All changes in `constants.py`:

| Constant | Old | New | Note |
|---|---|---|---|
| `LIQUIDITY_MIN_AVG_VOLUME` | 500,000 | 750,000 | Tighter volume gate |
| `LIQUIDITY_MIN_DOLLAR_VOLUME` | 20,000,000 | 25,000,000 | Tighter dollar volume gate |
| `UNIVERSE_MAX_AGE_DAYS` | *(new)* | 7 | Hard staleness cutoff |
| `UNIVERSE_WARN_AGE_DAYS` | *(new)* | 5 | Soft aging warning |
| `UNIVERSE_MIN_SIZE` | *(new)* | 800 | Sanity floor |
| `UNIVERSE_MAX_SIZE` | *(new)* | 2,500 | Sanity ceiling |

`MIN_ATR_PCT = 2.5` — already updated in engine-hardening work. No change.

---

## Section 3: RS Tier Scoring

### New constants

```python
RS_TIER1_THRESHOLD  = 85    # RS rank >= 85 → Tier 1 (market leader)
RS_TIER1_MULTIPLIER = 1.15  # Tier 1 RS score multiplier
```

### Change to compute_setup_score() in scoring.py

```python
# RS rank component — linear with Tier 1 multiplier
rs_pts = rs_rank / 100.0 * SCORE_WEIGHT_RS_RANK
if rs_rank >= RS_TIER1_THRESHOLD:
    rs_pts *= RS_TIER1_MULTIPLIER
rs_pts = min(float(SCORE_WEIGHT_RS_RANK), rs_pts)
```

### Score effect (SCORE_WEIGHT_RS_RANK = 30)

| RS Rank | Tier | Old pts | New pts |
|---|---|---|---|
| 95 | 1 | 28.5 | 30.0 (capped) |
| 88 | 1 | 26.4 | 30.0 (capped) |
| 85 | 1 boundary | 25.5 | 29.3 |
| 80 | 2 | 24.0 | 24.0 |
| 70 | 2 floor | 21.0 | 21.0 |

The hard RS gate (`RS_RANK_MIN_PERCENTILE = 70`) is unchanged.

---

## Section 4: Sector Gate (3-tier)

### New constants

```python
TOP_SECTORS_N            = 8    # total sectors returned by compute_top_sectors (was 5)
SECTOR_TIER1_N           = 5    # top 5 → full sector points
SECTOR_TIER2_FACTOR      = 0.8  # rank 6–8 → 80% of sector points
SECTOR_OUT_OF_TOP_FACTOR = 0.4  # outside top 8 → 40% of sector points
```

### Change to compute_setup_score() in scoring.py

```python
if sector in top_sectors[:SECTOR_TIER1_N]:
    sector_pts = float(SCORE_WEIGHT_SECTOR)                            # 10 pts
elif sector in top_sectors:
    sector_pts = float(SCORE_WEIGHT_SECTOR) * SECTOR_TIER2_FACTOR     # 8 pts
else:
    sector_pts = float(SCORE_WEIGHT_SECTOR) * SECTOR_OUT_OF_TOP_FACTOR # 4 pts
```

`compute_top_sectors()` already returns a sorted list — `TOP_SECTORS_N = 8` controls its length.
No API changes required.

---

## Section 5: Discovery Layer

### New constants

```python
DISCOVERY_RS_MIN        = 60    # lower RS bound
DISCOVERY_RS_MAX        = 70    # upper RS bound (exclusive)
DISCOVERY_52WK_HIGH_PCT = 0.03  # within 3% of 52-week high
DISCOVERY_VOL_RATIO     = 1.5   # 5-day avg vol >= 1.5x 50-day avg
DISCOVERY_MAX_PCT       = 0.10  # cap at 10% of universe size
```

### Logic in _run_scan() (main.py), after RS rank map is built

```python
_discovery_tickers: set[str] = set()
_discovery_cap = int(len(tickers) * DISCOVERY_MAX_PCT)

for ticker in tickers:
    if len(_discovery_tickers) >= _discovery_cap:
        break
    rs = _rs_rank_map.get(ticker, 0.0)
    if not (DISCOVERY_RS_MIN <= rs < DISCOVERY_RS_MAX):
        continue
    entry = _ticker_cache.get(ticker)
    if entry is None or entry[1] is None:
        continue
    _, df = entry
    adj = "Adj Close" if "Adj Close" in df.columns else "Close"
    close_arr = df[adj].dropna().values.astype(float)
    if len(close_arr) < 20:
        continue
    high_52w = close_arr[-min(252, len(close_arr)):].max()
    if close_arr[-1] < high_52w * (1 - DISCOVERY_52WK_HIGH_PCT):
        continue
    vol = df["Volume"].dropna().values.astype(float)
    if len(vol) < 50:
        continue
    if vol[-5:].mean() < DISCOVERY_VOL_RATIO * vol[-50:].mean():
        continue
    _discovery_tickers.add(ticker)
```

### RS gate modification

```python
# In _process() per-ticker RS gate:
if _ticker_rs_rank < RS_RANK_MIN_PERCENTILE:
    if ticker not in _discovery_tickers:
        # skip ticker (existing behavior)
        return
    # else: discovery candidate — fall through
```

### Setup metadata

Discovery candidates that produce signals get `"is_discovery": True` in their setup dict.
Stored in the existing `metadata` JSON column — no schema change required.

---

## Files Changed

| File | Change |
|---|---|
| `constants.py` | +12 new constants, 2 updated |
| `main.py` | Hybrid universe loader at startup, discovery layer in `_run_scan()`, new `/api/build-universe` endpoint |
| `scoring.py` | RS tier multiplier + 3-tier sector scoring in `compute_setup_score()` |
| `universe_builder.py` | Add `min_dollar_volume` param to `filter_price_volume()` and `build_universe()` |

No engine files touched. No DB schema changes.
