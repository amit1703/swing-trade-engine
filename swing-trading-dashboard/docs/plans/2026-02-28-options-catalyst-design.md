# Options Catalyst Scanner — Design Document

**Date:** 2026-02-28
**Status:** Approved

---

## Overview

An "Options Catalyst" scanner that detects unusual call-side options activity as a primary trading signal. The thesis: when smart money aggressively buys near-term calls on liquid tickers, the options flow itself is the catalyst — a relaxed technical confirmation (not a falling knife, basic uptrend) is sufficient to flag the setup.

---

## Architecture

### Engine 7 — Options Catalyst

New file: `backend/engines/engine7.py`

Engine 7 runs after Engines 2–6 in the per-ticker pipeline. It is **not gated by Engine 0** (market regime) — unusual call flow during a bearish market may signal an imminent reversal and is still worth surfacing.

---

## Detection Logic

### Liquidity Pre-filter

Uses OHLCV data already fetched — no extra API calls:

- `50-day avg volume > 1,000,000 shares`
- `close > $10.00`

Eliminates ~500 of the 700+ universe, leaving ~150–200 liquid tickers where options flow is meaningful. Tickers failing this filter skip Engine 7 entirely.

### Options Data Fetch

```python
t = yf.Ticker(ticker)
expirations = t.options  # list of expiry date strings
# Filter to 7 ≤ DTE ≤ 45
near_expiries = [e for e in expirations if 7 <= days_to_expiry(e) <= 45]
# Fetch calls for each qualifying expiry
calls_dfs = [t.option_chain(e).calls for e in near_expiries]
```

### Strike Filter

Focus on **0–10% OTM calls** only (directional intent, not deep-OTM lottery tickets):

```
min_strike = current_close * 1.00
max_strike = current_close * 1.10
```

### Four Signal Components (calls only)

| Signal | Formula | Interpretation |
|---|---|---|
| **Vol/OI Ratio** | `mean(volume / openInterest)` across qualifying contracts | High ratio = new positioning, not existing contracts rolling |
| **Absolute Call Volume** | `sum(volume)` across qualifying contracts | Raw size of the directional bet |
| **Call/Put Skew** | `total_call_vol / (total_call_vol + total_put_vol)` | Directional conviction ratio across near-term expirations |
| **IV Term Structure** | `iv_near / iv_next_expiry` | Near-term IV spike above far-term = urgency, catalyst expected soon |

### Composite OPTIONS_SCORE (0–100)

```python
score  = min(avg_vol_oi / 1.0, 1.0)            * 30   # Vol/OI component
score += min(total_call_vol / 2000.0, 1.0)      * 25   # Absolute volume
score += min((skew - 0.5) / 0.4, 1.0)           * 25   # Call/Put skew (0.5=neutral, 0.9=max)
score += min((iv_near / iv_next - 1.0) / 0.3, 1.0) * 20  # IV term structure
```

**Minimum threshold to flag: `OPTIONS_SCORE ≥ 60`**

---

## Relaxed Technical Filter

Two conditions, both required. Intentionally minimal — the options flow is the primary signal:

1. `close > SMA50` — basic uptrend, not a broken chart
2. `close > close[−10]` — not a falling knife over the past two weeks

No EMA crossovers, S/R zone requirements, RS filter, or volume confirmations.

---

## Output

### setup_type

`"OPTIONS_CATALYST"` — stored in the existing `scan_setups` table. No schema changes required.

### Entry / Stop / Target

| Field | Value |
|---|---|
| entry | current close |
| stop_loss | `close × 0.95` (5% hard stop) |
| take_profit | `close × 1.10` (10% target) |
| rr | `2.0` |

### Metadata JSON

```json
{
  "options_score": 78,
  "total_call_volume": 15420,
  "call_put_ratio": 0.82,
  "avg_vol_oi_ratio": 0.73,
  "iv_near": 0.45,
  "iv_next": 0.38,
  "iv_term_slope": 1.18,
  "dominant_strike": 195.0,
  "dominant_expiry": "2026-03-21",
  "dte": 21
}
```

---

## API Layer

New endpoint following the existing pattern:

```
GET /api/setups/options-catalyst  →  { setups: [...], count: N }
```

No new DB tables or columns. All options fields travel through the existing `metadata` JSON column in `scan_setups`.

---

## Concurrency & Performance

Options fetching is network-heavy but CPU-light. Runs in `loop.run_in_executor()` alongside the KDE calculation — non-blocking, parallelised across tickers via the existing `asyncio.Semaphore(CONCURRENCY_LIMIT)`. The liquidity pre-filter limits options API calls to ~150–200 tickers.

Engine 7 is added to the existing `engine_stats` dict:
```python
engine_stats["e7"] = {"options_catalyst": 0}
```

---

## Frontend

### New Tab

`OPTIONS` added to the top navigation alongside `SCANNER` and `PORTFOLIO`.

### Layout

Identical split to the SCANNER tab:
- **Left panel (400px):** SetupTable with `setup_type = "OPTIONS_CATALYST"`
- **Right panel (flex-1):** Existing `TradingChart` component — reused without modification

### SetupTable Configuration

- `accentColor`: purple (`#a855f7`)
- `title`: `"Options Catalyst"`

### Signal Badges (per row)

| Badge | Source field | Example |
|---|---|---|
| `SCORE 78` | `options_score` | Composite signal strength |
| `VOL 15.4K` | `total_call_volume` | Total near-term OTM call volume |
| `C/P 0.82` | `call_put_ratio` | Call dominance ratio |
| `DTE 21` | `dte` | Days to dominant expiry |

### App.jsx Additions

- One new state: `const [optionsSetups, setOptionsSetups] = useState([])`
- One new fetch: `loadOptionsSetups()` called inside `loadAllData()`
- Tab routing: `activeTab === 'options'` renders the new OPTIONS panel

---

## Constants (constants.py additions)

```python
# Engine 7 — Options Catalyst
OPTIONS_MIN_ADV            = 1_000_000   # Min 50-day avg daily volume
OPTIONS_MIN_PRICE          = 10.0        # Min share price
OPTIONS_DTE_MIN            = 7           # Min days to expiry
OPTIONS_DTE_MAX            = 45          # Max days to expiry
OPTIONS_OTM_MAX_PCT        = 0.10        # Max OTM % for strike filter (10%)
OPTIONS_MIN_SCORE          = 60          # Minimum OPTIONS_SCORE to flag
OPTIONS_VOL_OI_TARGET      = 1.0         # Vol/OI ratio at which component maxes out
OPTIONS_CALL_VOL_TARGET    = 2000        # Absolute call volume at which component maxes out
OPTIONS_SKEW_NEUTRAL       = 0.5         # Call/Put skew at neutral (50/50)
OPTIONS_SKEW_MAX           = 0.9         # Call/Put skew at which component maxes out
OPTIONS_IV_SLOPE_TARGET    = 0.30        # IV term slope at which component maxes out
```

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scan scope | Liquidity-filtered sub-universe | Options flow only meaningful on liquid tickers |
| Directional bias | Calls only | Matches long-biased dashboard; put interpretation is ambiguous |
| Expiration window | 7–45 DTE | Matches swing trading horizon; avoids LEAPS (hedges/long-term bets) |
| Strike range | 0–10% OTM | Captures directional intent; excludes deep-OTM lottery tickets |
| Market regime gate | None | Unusual call flow during bearish market may signal reversal |
| Technical filter | Minimal (2 conditions) | Options flow is the primary signal |
| UI layout | Reuse TradingChart | KDE zones and trendlines are immediately visible on click |
