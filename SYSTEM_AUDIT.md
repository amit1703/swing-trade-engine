# Swing Trading Dashboard — Full System Audit
**Date:** March 6, 2026
**Prepared for:** Technical Review
**Scope:** Complete codebase — backend engines, algorithms, data pipeline, database, frontend UI, automation

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Tech Stack](#2-tech-stack)
3. [System Architecture](#3-system-architecture)
4. [Universe Building Pipeline](#4-universe-building-pipeline)
5. [Scan Orchestration (main.py)](#5-scan-orchestration-mainpy)
6. [Technical Indicators Layer](#6-technical-indicators-layer)
7. [Engine 0 — Market Regime](#7-engine-0--market-regime)
8. [Engine 1 — S/R Zone Mapper (KDE)](#8-engine-1--sr-zone-mapper-kde)
9. [Engine 2 — VCP Breakout Scanner](#9-engine-2--vcp-breakout-scanner)
10. [Engine 3 — Tactical Pullback Scanner](#10-engine-3--tactical-pullback-scanner)
11. [Engine 4 — Relative Strength (RS Line)](#11-engine-4--relative-strength-rs-line)
12. [Engine 5 — Base Pattern Scanner](#12-engine-5--base-pattern-scanner)
13. [Engine 6 — Resistance Breakout Scanner](#13-engine-6--resistance-breakout-scanner)
14. [Zone Utility & Take-Profit Targeting](#14-zone-utility--take-profit-targeting)
15. [Risk Management Model](#15-risk-management-model)
16. [Database Architecture](#16-database-architecture)
17. [REST API Layer](#17-rest-api-layer)
18. [Frontend Architecture](#18-frontend-architecture)
19. [Automation & Email Digest](#19-automation--email-digest)
20. [Configuration Management](#20-configuration-management)
21. [Concurrency & Performance Model](#21-concurrency--performance-model)
22. [Summary Table — All Engines](#22-summary-table--all-engines)

---

## 1. Executive Summary

This is a full-stack swing trading signal detection and portfolio management platform. It scans a live universe of **1,770+ NYSE/Nasdaq tickers** (dynamically built from SEC EDGAR) using a pipeline of 7 specialized technical analysis engines, persists results to a SQLite database, and surfaces actionable trade setups in a React dashboard.

The system is designed around the **Mark Minervini / William O'Neil** methodology — focusing on Stage 2 uptrends, volume confirmation, relative strength leadership, and tight base patterns. The scan runs on a background thread and completes in approximately 5–10 minutes for the full universe.

**Key Capabilities:**
- Market regime gating (SPY vs 20 EMA — disables aggressive engines in bearish markets)
- Gaussian KDE-based S/R zone mapping per ticker
- VCP (Volatility Contraction Pattern) detection with 3 detection paths
- Tactical pullback detection with 3 variants (strict, relaxed, pure-EMA)
- Base pattern detection (ATR-Adjusted Darvas Box + Proportional Cup & Handle)
- Resistance breakout scanner (Minervini 3-rule method)
- O'Neil composite RS score + blue-dot detection
- Hot-sector detection (≥3 setups in same sector)
- Live portfolio management with health signals and trailing stops
- APScheduler-driven daily 7:30AM ET scan + 8:00AM email digest

---

## 2. Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend runtime | Python 3.10 |
| API framework | FastAPI 0.129 + Uvicorn 0.41 |
| Data source | yfinance (async via ThreadPoolExecutor) |
| Database | SQLite via aiosqlite (async) |
| Numerics | NumPy, Pandas, SciPy (gaussian_kde, curve_fit, find_peaks) |
| Scheduling | APScheduler 3.11 (BackgroundScheduler) |
| Email | Python smtplib (Gmail SMTP SSL, port 465) |
| Frontend | React 18.3 + Vite 5.4 |
| Styling | Tailwind CSS 3.4 |
| Charts | lightweight-charts 4.2 (TradingView library) |
| Dev proxy | Vite dev server → localhost:8000 |

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      FRONTEND (React / Vite)                 │
│                        localhost:5173                        │
│                                                             │
│  App.jsx (root state)                                       │
│  ├── Header.jsx        (regime banner, scan trigger)        │
│  ├── WatchlistPanel.jsx (near-breakout tickers)             │
│  ├── SetupTable.jsx    (reusable VCP/PB/Base/ResBreak grid) │
│  ├── TradingChart.jsx  (lightweight-charts OHLCV + overlays)│
│  ├── PortfolioTab.jsx  (active trades, live P/L, health)    │
│  └── api.js            (fetch wrapper → /api/*)             │
└─────────────────────────────────────────────────────────────┘
                          │  HTTP (proxied)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   BACKEND (FastAPI / Uvicorn)                │
│                        localhost:8000                        │
│                                                             │
│  main.py                                                    │
│  ├── REST endpoints (POST/GET /api/*)                       │
│  ├── _run_scan()  — background task orchestrator            │
│  │   ├── Engine 0  (market regime — always runs)            │
│  │   ├── Engine 1  (KDE S/R zones — per ticker)             │
│  │   ├── Engine 2  (VCP — gated by bullish regime)          │
│  │   ├── Engine 3  (Pullback — gated by bullish regime)     │
│  │   ├── Engine 4  (RS Line — used internally)              │
│  │   ├── Engine 5  (Base patterns — always runs)            │
│  │   └── Engine 6  (Resistance breakout — always runs)      │
│  ├── APScheduler  (7:30 AM ET scan, 8:00 AM ET email)       │
│  └── database.py  (SQLite CRUD via aiosqlite)               │
│                                                             │
│  active_universe.json  (1,770 pre-filtered tickers)         │
│  trading.db            (SQLite — immutable scan snapshots)  │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  yfinance (data source)                      │
│   Downloads 1y daily OHLCV per ticker (period="1y")         │
│   SPY fetched separately for regime + RS calculations       │
│   ThreadPoolExecutor + asyncio.Semaphore(5) for concurrency │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Universe Building Pipeline

**File:** `backend/universe_builder.py`

The tradeable universe is NOT hardcoded. It is built dynamically from live SEC EDGAR data and filtered through a 4-stage pipeline:

### Stage 1 — SEC EDGAR Fetch
- Calls `https://www.sec.gov/files/company_tickers_exchange.json`
- Filters to NYSE and Nasdaq exchanges only
- Deduplicates by ticker

### Stage 2 — Pattern Filter (`filter_ticker_patterns`)
Removes non-common-equity securities:
- **Warrants:** tickers ending in `W` or `WS`
- **Preferred shares:** tickers matching `-P[A-Z]?$`
- **Rights/Units:** tickers ending in `-R`, `-RT`, or `-U`
- **Known ETFs:** hardcoded set of 45 major ETFs (SPY, QQQ, ARKK, etc.)
- **Long tickers:** base length > 5 characters
- Normalizes dots to dashes (`BRK.B` → `BRK-B`)

### Stage 3 — Price/Volume Filter (`filter_price_volume`)
Downloads 3 months of daily data in batches of 250 tickers and applies:
- **Minimum price:** $10.00 (removes penny stocks)
- **Minimum 50-day avg volume:** 500,000 shares (liquidity gate)
- **Optional ATR% filter:** `ATR(14)/Close × 100 ≥ min_atr_pct` (zombie stock filter)

Batch delay of 1.0s between batches to avoid yfinance rate limiting.

### Stage 4 — Sector Mapping (`build_sector_map`)
- Uses `yfinance.Ticker(t).info` to fetch GICS sector per ticker
- Caches results in `sectors.json` — only fetches for new tickers
- Removes any ETFs detected via `quoteType == "ETF"`
- Falls back to `"Unknown"` on failure

### Output
Saved to `active_universe.json` with full metadata including build time, filter counts, and generated timestamp. Current production universe: **1,770 tickers**.

---

## 5. Scan Orchestration (main.py)

**File:** `backend/main.py`

### Scan Trigger
`POST /api/run-scan` starts a background asyncio task via `asyncio.create_task()`. Returns immediately — the frontend polls `GET /api/scan-status` every 2 seconds.

### Scan Flow (`_run_scan`)

```
1. Load active universe from active_universe.json
2. Run Engine 0 (SPY regime check)
3. Persist regime to DB
4. Set is_bullish flag
5. Fetch SPY 1y data for RS calculations (shared across all tickers)
6. Build per-ticker task list
7. Run per-ticker pipeline concurrently via asyncio.gather()
   — asyncio.Semaphore(5) caps concurrent yfinance downloads
   — Each ticker runs _process_ticker(ticker, spy_df, scan_ts, is_bullish)
8. Collect all setups
9. _inject_hot_sector() — mark sectors with ≥3 setups
10. batch_save_setups() — single transaction write to SQLite
11. Mark scan run as completed
```

### Per-Ticker Pipeline (`_process_ticker`)

```
1. Download 1y daily OHLCV via yfinance (with 3 retries, exponential backoff)
2. Vitality check: if stock moved < 2% H-L range in last 10 days → skip (zombie filter)
3. Engine 1: compute KDE S/R zones
4. Engine 4: compute RS score (O'Neil composite) + RS line + blue dot
5. If bullish market:
   a. Engine 2: scan VCP (DRY, BRK, TDL paths)
   b. Engine 3: scan Pullback (strict → relaxed → EMA path, first match wins)
6. Engine 5: scan base patterns (Cup & Handle + Darvas Box)
7. Engine 6: scan resistance breakout
8. Compute trendlines (ascending + descending)
9. Collect all valid setups from this ticker
```

### Hot Sector Injection (`_inject_hot_sector`)
After all tickers are processed, count setups per sector. Any sector with **≥3 setups** across all engine types gets `hot_sector: True` on all its setups. This is displayed as a 🔥 emoji in the frontend.

### Concurrency
- `asyncio.Semaphore(5)` — max 5 simultaneous yfinance downloads
- `ThreadPoolExecutor` — yfinance and heavy math (KDE, curve_fit) run in threads to avoid blocking the event loop
- Retry policy: `FETCH_MAX_RETRIES = 3`, `FETCH_BACKOFF_BASE = 1.0s` (exponential)

### Scan Status Polling
`GET /api/scan-status` returns:
```json
{
  "in_progress": true,
  "progress": 450,
  "total": 1770,
  "progress_pct": 25.4,
  "started_at": "2026-03-06T07:30:00",
  "last_completed": "2026-03-05T07:35:22",
  "engine_stats": {...}
}
```

### Dry-Run Mode
When `?dry_run=true`, results are NOT written to the database. They're returned in-memory via `scan_status.dry_run_setups` and the frontend displays them directly, bypassing the DB read cycle.

---

## 6. Technical Indicators Layer

**File:** `backend/indicators.py`

All indicators are implemented from scratch using NumPy/Pandas — no external TA library dependency.

### EMA (Exponential Moving Average)
```python
series.ewm(span=length, adjust=False, min_periods=length).mean()
```
Standard EWM formula. `adjust=False` uses recursive (Wilder-style) smoothing.

### SMA (Simple Moving Average)
```python
series.rolling(window=length, min_periods=length).mean()
```

### ATR (Average True Range — Wilder Smoothing)
```
TR = max(High−Low, |High−PrevClose|, |Low−PrevClose|)
ATR = TR.ewm(alpha=1/length, adjust=False)
```
Uses Wilder smoothing (alpha = 1/n), not simple rolling mean. Period: 14 days.

### True Range (raw, un-smoothed)
Same TR calculation as ATR but without smoothing — used for volatility contraction checks in Engine 2.

### CCI (Commodity Channel Index)
```
TP = (High + Low + Close) / 3
CCI = (TP − SMA(TP, n)) / (0.015 × MeanDeviation(TP, n))
```
Period: 20. Constant: 0.015 (Lambert's original formula). Division-by-zero protected via `.replace(0, NaN)`.

---

## 7. Engine 0 — Market Regime

**File:** `backend/engines/engine0.py`
**Purpose:** Master market switch — determines if aggressive long setups should fire

### Algorithm
1. Download SPY 6-month daily data
2. Compute `EMA(Close, 20)`
3. Compare latest SPY close to EMA-20

### Decision Rule
| Condition | Regime | Effect |
|-----------|--------|--------|
| `SPY_Close > SPY_20EMA` | BULLISH | Engines 2 & 3 enabled |
| `SPY_Close ≤ SPY_20EMA` | BEARISH | Engines 2 & 3 disabled |

### Output
```json
{
  "is_bullish": true,
  "spy_close": 580.45,
  "spy_20ema": 572.30,
  "regime": "BULLISH"
}
```

Errors return `is_bullish: false` with an `"ERROR: ..."` regime string — fail-safe defaults to bearish.

### Frontend Display
Shown as a prominent GO (green) / HALT (red) banner in the `Header.jsx` component.

---

## 8. Engine 1 — S/R Zone Mapper (KDE)

**File:** `backend/engines/engine1.py`
**Purpose:** Map institutional-level support and resistance zones using Gaussian KDE

This engine runs for every ticker in the universe. Its output is reused by Engines 2, 3, and 6 — it is the foundational "battlefield map" for all other engines.

### Algorithm

**Step 1 — Weekly Resample**
- Resample daily OHLCV to weekly: `Close = last, High = max, Low = min`
- Minimum 10 weeks of data required

**Step 2 — Pivot High/Low Collection**
- `argrelextrema(highs, np.greater_equal, order=order)` — local pivot highs
- `argrelextrema(lows, np.less_equal, order=order)` — local pivot lows
- Adaptive window: `order = max(2, len(weekly) // 20)`
- Combined price cloud: weekly closes + pivot highs + pivot lows

**Step 3 — Recency Weighting**
Each price point is assigned a weight based on age:
- ≤90 days ago: **weight = 2.0** (high recency)
- ≥365 days ago: **weight = 1.0** (baseline)
- Between 90–365 days: linear interpolation
- Minimum weight: 0.1

**Step 4 — Gaussian KDE with Dynamic Bandwidth**
- Uses `scipy.stats.gaussian_kde` with recency weights
- Dynamic bandwidth: `bandwidth = scott_factor × bw_scale`
  - Scott's rule: `n^(-1/5)`
  - `bw_scale = clip(CV / 0.05, 0.4, 1.2)` where CV = coefficient of variation
- Evaluates density over 600 linearly-spaced points between `price_min × 0.98` and `price_max × 1.02`

**Step 5 — Peak Detection**
- `scipy.signal.find_peaks()` with prominence threshold = 5th percentile of density
- Minimum distance between peaks: `max(4, len(x) × 0.008)`
- Retain top 70% of peaks by density + always include peaks within 3% of current price

**Step 6 — Peak Merging**
- Sort peaks, merge any within 1 ATR of each other (cluster → mean)

**Step 7 — Zone Construction**
```
zone_half_width = 0.2 × ATR14
zone_upper = level + zone_half_width
zone_lower = level - zone_half_width
```

**Step 8 — Zone Classification**
- `level > current_price` → RESISTANCE
- `level ≤ current_price` → SUPPORT

**Step 9 — Pivot Resistance Zones (`_find_pivot_resistance`)**
Additional overlay using daily bar pivot highs:
- `argrelextrema(highs, np.greater, order=15)` — major swing highs (30-bar window)
- Union-Find clustering: groups pivots within `PIVOT_TOUCH_MARGIN_PCT = 2.0%` AND `≥7 bars apart`
- Minimum `PIVOT_MIN_TOUCHES = 2` pivots to form a zone
- Narrow bands: `±0.1 × ATR` (tighter than KDE zones)
- Only emits zones within 3% below current price or overhead
- Returns top 2 nearest overhead pivot zones

### Output Format
```json
[
  {"level": 145.20, "upper": 146.10, "lower": 144.30, "type": "RESISTANCE", "atr": 4.50, "is_primary": true},
  {"level": 138.50, "upper": 139.40, "lower": 137.60, "type": "SUPPORT", "atr": 4.50, "is_primary": false}
]
```

---

## 9. Engine 2 — VCP Breakout Scanner

**File:** `backend/engines/engine2.py`
**Purpose:** Detect Volatility Contraction Pattern setups — the core high-conviction long setup

Three detection paths, all output `setup_type = "VCP"`:

### Path A — DRY (Coiled Spring)
Stock is coiling just below a resistance zone with drying volume. Not yet broken out.

| Rule | Implementation |
|------|---------------|
| **Trend** | `EMA8 > EMA20` AND `Close > SMA50` |
| **TR Contraction** | `MeanTR(last 5 bars) < MeanTR(prior 20 bars)` |
| **U-Shape** | `scipy.optimize.curve_fit` parabola over last 15 bars → coefficient `a > 0` (opening upward) |
| **Volume Dry-Up** | At least 1 bar in last 10 bars with volume below 50% of 50-day SMA |
| **Location** | Current close within 5% below a KDE resistance zone level |

### Path B — BRK (Confirmed Breakout)
Stock has already closed above resistance with institutional volume.

| Rule | Implementation |
|------|---------------|
| **Trend** | `EMA8 > EMA20` AND `Close > SMA50` |
| **Location** | `Close > zone_upper × 1.025` (0–2.5% above zone) |
| **Volume** | `Daily Volume ≥ 150% of 50-day vol SMA` |
| **RS Filter** | `rs_vs_spy > -0.05` (stock not persistent underperformer) |

Sub-flags on BRK setups:
- **`is_rs_lead`** (highest conviction): BRK + stock 3m return > SPY 3m return + RS blue dot
- **`is_breakout = true`**: standard BRK flag

### Path C — TDL (Trendline Breakout)
Stock breaks above a descending trendline fitted to recent pivot highs.

| Rule | Implementation |
|------|---------------|
| **Trendline** | Linear regression on last 5 pivot highs (descending slope required) |
| **Location** | Close 0–3% above trendline value |
| **Volume** | `Daily Volume ≥ 100% of 50-day vol SMA` |

TDL setups surface as VCP (not watchlist). They carry `is_trendline_breakout = true`.

### Watchlist (Near-Breakout)
Any DRY setup within 1.5% of resistance (but not triggering DRY criteria) is downgraded to `setup_type = "WATCHLIST"`. TDL-BRK setups are removed from watchlist.

### Risk Math (all VCP paths)
```
Entry      = High × 1.001
Stop Loss  = min(Low, zone_lower) − 0.2 × ATR14
Risk       = Entry − Stop
Take Profit= nearest KDE resistance zone above entry (fallback: Entry + 2 × Risk)
```

Risk gate: `0 < Risk ≤ 15% of entry`

### Metadata Fields
All VCP setups carry in their `metadata` JSON:
- `rs_score` (O'Neil composite, float)
- `hot_sector` (bool)
- `is_breakout`, `is_rs_lead`, `is_trendline_breakout`, `is_kde_breakout`
- `resistance_level`, `zone_upper`, `volume_ratio`

---

## 10. Engine 3 — Tactical Pullback Scanner

**File:** `backend/engines/engine3.py`
**Purpose:** Identify high-quality pullbacks to the 8/20 EMA value zone during established uptrends

Three scan functions, tried in order — first match wins:

### Strict Pullback (`scan_pullback`)
All 5 conditions must pass:

| Condition | Rule |
|-----------|------|
| **0. RS Gate** | `rs_score ≥ -0.05` (not a persistent underperformer) |
| **1. Trend** | `EMA8 > EMA20` AND `Close > SMA50` |
| **2. Value Zone** | `Low ≤ EMA8` OR `Low ≤ EMA20` (price entered the zone) |
| **3. Support Touch** | Low is inside a KDE SUPPORT zone (±2.0% tolerance) OR ascending trendline touch (±1.5%) |
| **4. Pin Bar** | `Close ≥ EMA20` (rejection — closed back above the zone) |
| **5. CCI Hook** | `CCI[yesterday] < -50` AND `CCI[today] > CCI[yesterday]` (momentum turning from oversold) |

### Relaxed Pullback (`scan_relaxed_pullback`)
Triggered when strict scan finds nothing. Looser CCI requirement, mandatory KDE zone:

| Condition | Rule |
|-----------|------|
| **1. Trend** | `EMA8 > EMA20` AND `Close > SMA50` |
| **2. Buffer Zone** | `Close within 2% of EMA8 or EMA20` |
| **3. CCI Signal** | `CCI[yesterday] < -30` AND `CCI[today] > CCI[yesterday]` |
| **4. Volume Dry** | `3-day avg volume ≤ 50-day avg volume` |
| **5. KDE Support** | Mandatory — Low or Close inside a KDE SUPPORT zone (±2.0%) |

Flags `is_relaxed = true` in output.

### Pure EMA Pullback (`scan_ema_pullback`)
No KDE zone required — pure moving average touch:

| Condition | Rule |
|-----------|------|
| **1. Trend** | `EMA8 > EMA20 > SMA50` (stricter — all three in order) |
| **2. EMA20 Touch** | `Low ≤ EMA20 × 1.005` (within 0.5% of EMA20) |
| **3. Rejection** | `Close ≥ EMA20` (pin bar) |
| **4. CCI Hook** | `CCI[yesterday] < -30` AND `CCI[today] > CCI[yesterday]` |
| **5. Volume Dry** | `Today's volume < 50-day avg volume` |

Flags `is_ema_path = true` in output.

### Risk Math
```
Entry      = High × 1.001
Stop Loss  = min(Low, support_lower) − 0.2 × ATR14
Take Profit= nearest KDE resistance above entry (fallback: Entry + 2 × Risk)
```

### Ascending Trendline Detection
Used as an alternative support source in all three paths. The trendline is computed by fitting a line through the last 3+ ascending swing lows. Touch tolerance: `±1.5%` of trendline value. When a trendline touch is found, `is_ascending_tdl = true` is flagged in the output.

---

## 11. Engine 4 — Relative Strength (RS Line)

**File:** `backend/engines/engine4.py`
**Purpose:** Measure a stock's performance relative to SPY — used as a filter and ranking metric across all engines

### RS Line (`calculate_rs_line`)
```
RS_line[t] = ticker_close[t] / SPY_close[t]
```
- Aligned on common trading dates (intersection of ticker and SPY date index)
- Returns last 252 values (1 trading year)
- Requires ≥252 common bars — otherwise returns `None`

### Blue Dot (`detect_rs_blue_dot`)
```
blue_dot = RS_today ≥ RS_52w_high × (1 − 0.005)
```
RS ratio within 0.5% of its 52-week high = RS Blue Dot = institutional accumulation signal. Used in Engine 5 quality scoring and Engine 2 RS Lead flagging.

### O'Neil Composite RS Score (`calculate_rs_score`)
Weighted multi-period outperformance vs SPY:

| Period | Weight | Formula |
|--------|--------|---------|
| 63 days (3 months) | 40% | `stock_return_63d − spy_return_63d` |
| 126 days (6 months) | 20% | `stock_return_126d − spy_return_126d` |
| 189 days (9 months) | 20% | `stock_return_189d − spy_return_189d` |
| 252 days (1 year) | 20% | `stock_return_252d − spy_return_252d` |

Result = weighted sum. Positive = outperforming SPY. Example: `0.076` = 7.6% outperformance. Periods with insufficient data are skipped with weight redistribution.

### Usage Across Engines
| Engine | How RS Score Is Used |
|--------|---------------------|
| Engine 2 (VCP BRK) | `rs_vs_spy > -0.05` filter; `is_rs_lead` = BRK + outperform + blue dot |
| Engine 3 (Pullback) | `rs_score ≥ -0.05` quality gate on all 3 paths |
| Engine 5 (Base) | 25/100 quality score points for RS outperformance ≥5% |
| All engines | `rs_score` stored in metadata JSON for frontend sorting |

---

## 12. Engine 5 — Base Pattern Scanner

**File:** `backend/engines/engine5.py`
**Purpose:** Detect stocks building constructive basing patterns — potential multi-week setup opportunities

### Pattern A — ATR-Adjusted Darvas Box (Flat Base)

**Entry Gate (Stage 2 uptrend — strict):**
- `SMA50 > SMA200` (Stage 2 confirmed)
- `Close > SMA50`

**Box Detection (scans lookback windows 20–40 days, accepts widest passing window):**

| Gate | Rule |
|------|------|
| **Tightness** | `Box height ≤ 3.5 × ATR14` — eliminates low-volatility drift |
| **Ceiling tested** | `≥2 bars with High ≥ ceiling − 0.5 × ATR` (real resistance, not phantom) |
| **Position** | `Close ≥ floor + 75% of box height` (coiled near breakout) |
| **Volume dry** | `5-day avg volume < 50-day avg volume` |

**Signal Classification:**
- `BRK`: `Close > ceiling` AND `volume ≥ 120%` of 50-day avg
- `DRY`: `distance to ceiling ≤ 1.0%`
- Otherwise: no setup

### Pattern B — Proportional Cup & Handle

**Entry Gate:** `Close > SMA200`

**Cup Detection (last 120 bars):**

| Gate | Rule |
|------|------|
| **Left peak** | Highest close in first 2/3 of lookback window |
| **Cup bottom** | Lowest close after left peak |
| **ATR-proportional depth** | `15% ≤ depth ≤ min(45%, ATR% × 10)` — high-ATR stocks allow deeper cups |
| **Duration** | `cup_bottom_idx − left_peak_idx ≥ 25 bars` (no V-shapes) |
| **Recovery** | Right rim recovers ≥50% of cup depth |

**Handle Requirements:**
- At least 5 bars after right rim
- `Close ≥ cup_bottom + 50% of cup depth` (in upper half)
- `handle_ATR < decline_phase_ATR` (volatility contraction in the handle)

**Signal Classification:**
- `BRK`: `Close > handle_high` AND `volume ≥ 120%` of 50-day avg
- `DRY`: `distance to handle_high ≤ 1.0%`

### Quality Score (0–100)
All base patterns are scored on four equally-weighted dimensions (25 pts each):

| Component | Scoring Rule |
|-----------|-------------|
| **RS vs SPY** | `rs_score ≥ 5%` outperformance = 25 pts (scales linearly) |
| **Tightness** | Lower tightness ratio = more pts; 0 = perfectly tight = 25 pts |
| **Volume Dry-Up** | `vol5/vol50 ≤ 30%` = 25 pts; scales to 0 at 100% |
| **RS Blue Dot** | 25 pts if `detect_rs_blue_dot() = True` |

**Minimum quality score to emit a setup: 25/100**

### Risk Math
- Darvas Box: `Entry = ceiling × 1.001`, `Stop = floor − 0.2 × ATR`
- Cup & Handle: `Entry = handle_high × 1.001`, `Stop = handle_low − 0.2 × ATR`

### Geometry Metadata
Base setups include a `geometry` dict with start/end dates and key price levels for chart overlay rendering.

---

## 13. Engine 6 — Resistance Breakout Scanner

**File:** `backend/engines/engine6.py`
**Purpose:** Detect institutional-quality breakouts using Minervini's three-rule method

### Uptrend Filter
`Close > SMA50` — only stocks above their 50-day moving average are considered.

### Overextension Gate
`current_close ≤ zone_upper × 1.05` — stops chasing stocks already extended >5% above breakout zone.

### Three Mandatory Rules (all must pass)

**Rule 1 — Launchpad (Pre-Breakout Coiling)**
The 3 bars immediately before the breakout bar must all show:
- `High ≤ zone_upper × 1.03` (coiling under resistance, not poking through)
- `Bar range < 1.5 × ATR14` (tight daily ranges — no chaotic distribution)

**Rule 2 — Decisive Close**
The breakout bar itself must show:
- `Close > zone_upper × 1.005` (at least 0.5% above zone — not a wick through)
- `Close ≥ Low + 70% × Day_Range` (closes in top 30% of the day's range — no bearish wick fakeout)

**Rule 3 — Institutional Volume**
- `Breakout day volume ≥ 150% of 50-day volume SMA`

### Lookback Window
Checks last 3 days for a qualifying breakout bar (`days_back` = 0, 1, 2, or 3). Returns the most recent qualifying breakout. `days_since_breakout` (0–3) is included in output for freshness ranking.

### Zone Source Compatibility
Checks both KDE RESISTANCE zones AND recently-crossed KDE SUPPORT zones (zones that were RESISTANCE but price has moved above them — Engine 1 reclassifies as SUPPORT after price breaks above).

### Risk Math
```
Entry     = breakout_bar_high × 1.001
Stop Loss = zone_lower − 0.2 × ATR14
Take Profit= nearest KDE resistance above entry (fallback: Entry + 2 × Risk)
```

---

## 14. Zone Utility & Take-Profit Targeting

**File:** `backend/zone_utils.py`
**Used by:** Engines 2, 3, 5, 6

### `nearest_resistance_target(entry, zones, risk)`

Logic:
1. Find all KDE RESISTANCE zones where `zone.lower > entry`
2. Take the nearest one (minimum `zone.lower`)
3. Compute `R:R = (zone.lower − entry) / risk`
4. If `R:R < 1.0` → too close, use fallback
5. Fallback: `Entry + TARGET_RR × risk` where `TARGET_RR = 2.0` (configurable)

This ensures take-profit targets are dynamically placed at the next real supply overhead rather than an arbitrary multiple.

---

## 15. Risk Management Model

### Per-Trade Risk Rules (enforced in all engines)
| Rule | Value |
|------|-------|
| Entry price | `High × 1.001` (0.1% above setup candle high) |
| Stop loss | `Swing Low − 0.2 × ATR14` |
| Max risk per trade | ≤15% of entry price (hard filter — setup rejected if wider) |
| Min R:R | 1.0 (take-profit at least 1× risk away) |
| Default R:R target | 2.0 (configurable via `TARGET_RR`) |

### Portfolio Health Signals (PortfolioTab.jsx)
Once a trade is entered, live health monitoring provides daily exit guidance:

| Signal | Condition | Meaning |
|--------|-----------|---------|
| HOLD | `Close > EMA20` | Trend intact |
| CAUTION | `Close < EMA8` | Short-term momentum weakening |
| EXIT | `Close < EMA20` OR `CCI < 100` | Exit signal — trend breaking |

### Trailing Stop
```
trailing_stop = max(original_stop, EMA20)
```
Applied when the trade is in profit — ratchets stop up to the 20 EMA as it rises.

---

## 16. Database Architecture

**File:** `backend/database.py`
**Engine:** SQLite via aiosqlite (fully async)

### Schema

**`scan_runs`** — one row per scan
```sql
id, scan_timestamp (UNIQUE), tickers_scanned, completed, created_at
```

**`market_regime`** — SPY snapshot per scan
```sql
id, scan_timestamp, spy_close, spy_20ema, is_bullish, regime
```

**`scan_setups`** — all trading signals
```sql
id, scan_timestamp, ticker, setup_type, entry, stop_loss,
take_profit, rr, setup_date, metadata (JSON)
```

**`sr_zones`** — KDE S/R zones per scan
```sql
id, scan_timestamp, ticker, level, zone_upper, zone_lower,
zone_type, source ('kde' | 'pivot')
```

**`trades`** — portfolio entries (independent of scans)
```sql
id, ticker, entry_price, quantity, stop_loss, target,
targets_json (multi-target JSON array), entry_date, notes,
status ('active' | 'closed'), exit_price, exit_date, created_at
```

### Indexes
```sql
idx_setups_ts     ON scan_setups(scan_timestamp)
idx_setups_type   ON scan_setups(scan_timestamp, setup_type)
idx_setups_ticker ON scan_setups(ticker)
idx_zones_ticker  ON sr_zones(ticker, scan_timestamp)
idx_zones_scan    ON sr_zones(scan_timestamp)
idx_regime_ts     ON market_regime(scan_timestamp)
idx_trades_status ON trades(status)
```

### Immutable Snapshots
Each scan is keyed by `scan_timestamp`. Old results are **never deleted or updated** — new scans append new rows. The frontend always reads from the latest completed scan. This provides full historical auditability.

### Batch Insert
`batch_save_setups()` uses `executemany()` in a single transaction. Per-row inserts (`save_setup()`) are available but discouraged for full-scan writes — batch is 5–10× faster.

### Metadata Column
Extra engine-specific fields (rs_score, hot_sector, base_type, geometry, etc.) are stored as JSON in the `metadata` TEXT column. This avoids schema migrations for new engine outputs and keeps the core schema stable.

### Schema Migrations
`init_db()` applies safe `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migrations at startup:
- `trades.targets_json`
- `sr_zones.source`
- `trades.exit_price`, `trades.exit_date`

---

## 17. REST API Layer

**File:** `backend/main.py`
**Framework:** FastAPI 0.129

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/run-scan` | Trigger background scan. Params: `force`, `dry_run`, `tickers` |
| GET | `/api/scan-status` | Poll scan progress and engine stats |
| GET | `/api/regime` | Latest market regime from DB |
| GET | `/api/setups/{type}` | Setups by type: `vcp`, `pullback`, `base`, `res-breakout`, `options-catalyst` |
| GET | `/api/setups` | All setups (all types) |
| GET | `/api/watchlist` | Watchlist items (near-breakout) |
| GET | `/api/sr-zones/{ticker}` | KDE S/R zones for a ticker from latest scan |
| GET | `/api/chart/{ticker}` | OHLCV + EMA8/20 + SMA50 + CCI20 (fresh yfinance fetch) |
| GET | `/api/prices` | Live prices for comma-separated tickers (60s server-side cache) |
| GET | `/api/debug/{ticker}` | Dev mode: per-engine pass/fail drill-down for one ticker |
| GET | `/api/trades` | Active portfolio trades |
| POST | `/api/trades` | Add a new trade |
| DELETE | `/api/trades/{id}` | Close/exit a trade |
| GET | `/api/trades/closed` | Closed trade history with P/L calculations |
| GET | `/api/health` | Health check |

### CORS
```python
allow_origins = ["localhost:5173", "localhost:3000", "127.0.0.1:5173", "127.0.0.1:3000"]
```

### Live Price Cache
`GET /api/prices` fetches quotes via yfinance `Tickers.history(period="1d")`. Results are cached server-side for 60 seconds (dict keyed by ticker set) to prevent hammering yfinance during frontend 60s refresh cycles.

### Debug Endpoint
`GET /api/debug/{ticker}` re-runs the full per-ticker pipeline with `debug=True` on each engine, returning a structured pass/fail report for each engine rule. Used by the `DebugDrawer` component in dev mode.

---

## 18. Frontend Architecture

**File layout:**
```
frontend/src/
├── App.jsx               ← Root state + layout + routing
├── api.js                ← Fetch wrapper (all API calls)
└── components/
    ├── Header.jsx         ← Regime banner, scan button, search
    ├── SetupTable.jsx     ← Reusable setup grid
    ├── TradingChart.jsx   ← lightweight-charts OHLCV + overlays
    ├── PortfolioTab.jsx   ← Portfolio management
    ├── WatchlistPanel.jsx ← Near-breakout watchlist
    ├── EngineHealthPanel.jsx ← Dev mode engine stats
    ├── DebugDrawer.jsx    ← Dev mode per-engine drill-down
    └── SystemGuideModal.jsx ← Help modal (press '?')
```

### State Management (App.jsx)
Simple `useState` + `useCallback` — no Redux or Zustand. All state lives in `App.jsx` and flows down as props.

Key state atoms:
```javascript
activeTab           // 'scanner' | 'portfolio' | 'options'
regime              // SPY regime object
vcpSetups           // VCP setup array
pullbackSetups      // Pullback setup array
baseSetups          // Base pattern array
resBreakoutSetups   // Resistance breakout array
optionsSetups       // Options catalyst array
watchlistItems      // Near-breakout watchlist
selectedTicker      // Currently selected ticker (drives chart)
chartData           // OHLCV + indicator data
scanStatus          // Polling status object
livePrices          // {ticker: price} map
devMode             // Debug features toggle
dryRun              // Non-persisting scan mode
sortBy              // Active sort key
hotOnly             // Hot-sector filter toggle
```

### Scan Polling Flow
```
User clicks "Scan" → triggerScan() POST → in_progress = true
→ setInterval(fetchScanStatus, 2000)
→ on completion: loadAllData() (DB read) OR dry_run setups (in-memory)
→ clearInterval
```

### SetupTable.jsx
Reusable grid for all engine types. Accepts:
- `setups`: array of setup objects
- `title`: section label
- `accentColor`: `"blue"` (VCP) | `"accent"` (Pullback) | `"green"` (Base/ResBreakout) | `"purple"` (Options)

Row behaviors:
- `is_vol_surge = true` → green tinted row background
- `hot_sector = true` → 🔥 emoji next to ticker
- Selected ticker → amber border highlight
- Clicking ticker → loads chart + S/R zones
- Dev mode → [?] debug button per row

Signal badges rendered per engine type:
- VCP: `BRK`, `DRY`, `TDL`, `RS LEAD`, `🔵` (blue dot)
- Pullback: `STRICT`, `RELAXED`, `EMA`, `TDL`
- Base: `CUP+H`, `FLAT`, `BRK`, `DRY`
- ResBreakout: `BRK`, freshness indicator (D+0, D+1, D+2, D+3)

### TradingChart.jsx
Built on `lightweight-charts` v4.2 (TradingView's charting library).

Main series:
- **Candlestick chart:** raw OHLCV prices (`Close` column — not adjusted, for display accuracy)
- **EMA8, EMA20, SMA50:** computed on `Adj Close` for mathematical accuracy

Overlays:
- **S/R zones:** horizontal bands (KDE zones as wider bands, pivot zones as narrow lines)
- **Base geometry:** for BASE setups — cup/handle geometry overlay
- **Trendlines:** ascending and descending trendlines (when available)

Lower panel:
- **CCI(20):** oscillator panel with ±100 reference lines

### PortfolioTab.jsx
Full portfolio management interface:
- Add trades with multi-target support
- Live P/L calculation using `livePrices` (auto-refreshes every 60s)
- Health signals per trade (HOLD / CAUTION / EXIT) based on EMA and CCI
- Trailing stop display: `max(original_stop, EMA20)` when in profit
- Closed trade history with P/L%, days held, total PnL

### WatchlistPanel.jsx
Narrow left-side panel showing WATCHLIST setups from the last scan. These are stocks within 1.5% of a resistance zone but not yet triggering a full VCP signal. Acts as an early-alert queue.

### Sort & Filter Bar
Controls in `App.jsx` SortBar component:
| Option | Sorts By |
|--------|----------|
| Default | Scan order |
| Risk % ↑/↓ | `(entry − stop) / entry` |
| R:R ↓ | Reward-to-risk ratio |
| Vol ↓ | Volume ratio (vs 50d avg) |
| $ ↑ | Entry price ascending |
| A–Z | Ticker alphabetical |
| RS ↓ | O'Neil RS score descending |
| 🔥 Hot | Filter to hot-sector only |

---

## 19. Automation & Email Digest

**File:** `backend/email_digest.py`, `backend/main.py`

### APScheduler Jobs
Two scheduled jobs registered at startup via `APScheduler.BackgroundScheduler`:

| Job | Time | Function |
|-----|------|----------|
| `run_morning_scan` | 7:30 AM Eastern | Full 1,770-ticker scan |
| `send_morning_email` | 8:00 AM Eastern | Email digest of scan results |

Jobs fire every weekday. The scheduler uses `America/New_York` timezone.

### Email Digest (`send_digest`)
Sends a dark-themed HTML email via Gmail SMTP SSL (port 465):

**Configuration (`.env` file):**
```
EMAIL_FROM      = your-gmail@gmail.com
EMAIL_PASSWORD  = xxxx-xxxx-xxxx-xxxx  (Gmail App Password, not account password)
EMAIL_TO        = recipient@example.com
```

**Email Contents:**
- Date, time, BULL/BEAR/NEUTRAL badge
- SPY close and 50-day SMA context
- Summary bar: total setups count by type
- Sections: VCP Breakouts, VCP Dry, Resistance Breakouts, Pullbacks, Options
- Each section: table with Ticker | Entry | Stop | R:R | RS Score
- RS Score color-coded: green ≥80, amber ≥50, muted <50
- R:R color-coded: green ≥2.5×, white otherwise

---

## 20. Configuration Management

**File:** `backend/constants.py`

All tunable thresholds are centralized in one file. Key values:

### RS & Strength
| Constant | Value | Meaning |
|----------|-------|---------|
| `RS_BLUE_DOT_TOLERANCE_PCT` | 0.5% | RS ratio within 0.5% of 52w high = blue dot |

### Price & Proximity
| Constant | Value | Meaning |
|----------|-------|---------|
| `PRICE_RESISTANCE_PROXIMITY_PCT` | 3% | Entry proximity for calculations |
| `KDE_BREAKOUT_UPPER_PCT` | 2.5% | Max above resistance for BRK path |
| `DRY_RESISTANCE_PROXIMITY_PCT` | 5% | DRY path coiling window |
| `WATCHLIST_PROXIMITY_PCT` | 1.5% | Near-breakout watchlist threshold |
| `TRENDLINE_TOUCH_TOLERANCE_PCT` | 1.5% | Ascending trendline touch check |

### Technical Indicators
| Constant | Value |
|----------|-------|
| `EMA_SHORT` | 8 |
| `EMA_LONG` | 20 |
| `SMA_LONG` | 50 |
| `CCI_PERIOD` | 20 |
| `TR_WINDOW` | 14 (ATR) |
| `CCI_STRICT_FLOOR` | -50 |
| `CCI_RLX_FLOOR` | -30 |

### Risk Management
| Constant | Value |
|----------|-------|
| `ATR_STOP_MULTIPLIER` | 0.2 (20% of ATR below swing low) |
| `ENTRY_PRICE_MULTIPLIER` | 1.001 (0.1% above high) |
| `TARGET_RR` | 2.0 (default take-profit multiplier) |

### Data & Scan
| Constant | Value |
|----------|-------|
| `DATA_FETCH_PERIOD` | "1y" |
| `CONCURRENCY_LIMIT` | 15 |
| `FETCH_MAX_RETRIES` | 3 |
| `VITALITY_MIN_RANGE_PCT` | 2% (zombie stock filter) |
| `MIN_ATR_PCT` | 2.0 (universe pre-filter) |
| `PIVOT_LOOKBACK_DAYS` | 252 |
| `PIVOT_TOUCH_MARGIN_PCT` | 2.0% |
| `PIVOT_MIN_SEPARATION_DAYS` | 7 |
| `PIVOT_MIN_TOUCHES` | 2 |

---

## 21. Concurrency & Performance Model

### Backend
- FastAPI runs on Uvicorn (ASGI) — fully async
- yfinance downloads (blocking I/O) execute in a `ThreadPoolExecutor` so they don't block the event loop
- `asyncio.Semaphore(5)` limits concurrent yfinance calls
- KDE computation (CPU-bound, scipy) also offloaded to executor
- `asyncio.gather()` processes all tickers concurrently within the semaphore cap
- Retry backoff: `1s, 2s, 4s` (exponential)

### Typical Scan Performance
- Universe: ~1,770 tickers
- Concurrency: 5 simultaneous downloads
- Total scan time: ~5–10 minutes
- DB write: single `executemany()` transaction — writes all setups in one atomic operation

### Frontend
- Live price polling: every 60 seconds via `setInterval`
- Scan status polling: every 2 seconds during active scan
- All API calls are `Promise.allSettled()` — one failing request doesn't block others

---

## 22. Summary Table — All Engines

| Engine | Name | Setup Type | Market Gate | Key Signal Conditions |
|--------|------|-----------|-------------|----------------------|
| 0 | Market Regime | `regime` | None | SPY Close vs 20 EMA |
| 1 | KDE Zone Mapper | `sr_zones` | None | Gaussian KDE on weekly OHLCV |
| 2 | VCP Scanner | `VCP`, `WATCHLIST` | Bullish only | EMA trend + TR contraction + volume + resistance proximity |
| 3 | Pullback Scanner | `PULLBACK` | Bullish only | EMA trend + value zone + KDE support + pin bar + CCI hook |
| 4 | RS Line | (filter/metric) | None | ticker/SPY ratio, O'Neil weighted composite score |
| 5 | Base Patterns | `BASE` | None | Darvas Box or Cup & Handle with ATR-proportional depth |
| 6 | Resistance Breakout | `RES_BREAKOUT` | None | Launchpad + decisive close + institutional volume |

---

*End of Audit Document*
*Generated from live codebase — March 6, 2026*
