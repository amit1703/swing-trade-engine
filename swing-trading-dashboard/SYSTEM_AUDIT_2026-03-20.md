Perfect. Now I have a comprehensive understanding of the codebase. Let me compile the detailed audit report:

## COMPREHENSIVE SWING TRADING SCANNER AUDIT REPORT

---

### 1. UNIVERSE (tickers.py)

**Overview:**
- Contains 700+ tickers split between S&P 500 list (SP500) and Russell 1000 additions (RUSSELL1000_EXTRA)
- Uses `dict.fromkeys()` for deduplication and order preservation
- Final `SCAN_UNIVERSE` is deduplicated list of combined tickers

**Current State:**
- SP500: ~210 tickers across mega-cap tech, retail, semiconductors, software/cloud, biotech, pharma, financials, energy, utilities, REITs, etc.
- RUSSELL1000_EXTRA: ~490 additional mid-cap tickers
- **Total: ~700 unique tickers after deduplication**
- Covers all major sectors (Tech, Healthcare, Financials, Energy, Industrials, Consumer, Materials, Utilities, Communications)

**Issues Found:**
- Line 108: `"ALTR"` appears twice in RUSSELL1000_EXTRA (duplicate name, different context likely - second occurrence should be removed)
- Line 123: `"KINGSWAY"` is listed but should be `"KFS"` or have appropriate ticker format
- Some tickers may have moved from Russell to S&P or vice versa (stale as of 2025-03)

**Gaps:**
- No validation that tickers are currently active (may include delisted stocks)
- No metadata on sector assignments (hardcoded elsewhere in main.py via SECTORS dict)

---

### 2. CONSTANTS (constants.py)

**Key Tunable Parameters:**

| Category | Param | Current Value | Notes |
|----------|-------|---------------|-------|
| **RS Line** | RS_BLUE_DOT_TOLERANCE_PCT | 0.005 (0.5%) | Tolerance for 52-week high detection |
| **Price Proximity** | PRICE_RESISTANCE_PROXIMITY_PCT | 0.03 (3%) | DRY entry proximity |
| | KDE_BREAKOUT_UPPER_PCT | 0.025 (2.5%) | Above zone for KDE breakouts |
| | KDE_BREAKOUT_LOWER_PCT | 0.001 (0.1%) | Below zone for near-breakout detection |
| | WATCHLIST_PROXIMITY_PCT | 0.015 (1.5%) | Watchlist fallback threshold |
| | TRENDLINE_TOUCH_TOLERANCE_PCT | 0.015 (1.5%) | Ascending TDL touch tolerance |
| | VCP_TIGHT_RANGE_5D_PCT | 0.03594 | Optuna v4 best (trial #951) |
| **HTF Engine 8** | HTF_MIN_RUNUP_PCT | 0.80 (80%) | Min gain in 40 days |
| | HTF_MAX_FLAG_DEPTH_PCT | 0.25 (25%) | Max consolidation depth |
| | HTF_MIN_FLAG_BARS | 5 | Min consolidation bars |
| | HTF_MAX_FLAG_BARS | 20 | Max consolidation bars |
| | HTF_MAX_EXTEND_PCT | 0.05 (5%) | Max overextension on breakout |
| | HTF_MAX_RISK_PCT | 0.35 (35%) | Wide stop allowed for HTF |
| **LCE Engine 9** | LCE_MAX_DISTANCE_PCT | 0.03 (3%) | Distance below resistance |
| | LCE_VOL_CONTRACTION_RATIO | 0.80 | 5-bar avg â‰¤ 80% of 20-day avg |
| | LCE_MAX_RISK_PCT | 0.15 (15%) | Max stop distance for LCE |
| | LCE_TIGHT_RANGE_CONTRACTION | 0.70 | 5-bar range < 70% of prior |
| | LCE_BREAKOUT_VOL_RATIO | 1.0 | Volume â‰¥ 1x 20-day avg on breakout |
| **Technical Periods** | EMA_SHORT, EMA_LONG, SMA_LONG | 8, 20, 50 | Standard swing trading periods |
| | CCI_PERIOD | 20 | Standard CCI period |
| | CCI_STRICT_FLOOR | -39.10 | Optuna v4 best (was -50.0 v3) |
| | CCI_RLX_FLOOR | -1.95 | Optuna v4 best for relaxed (was -20.0 v3) |
| | TR_WINDOW | 14 | True Range period |
| **Risk Management** | ATR_STOP_MULTIPLIER | 1.278 | Optuna v4 best (was 1.360 v3) |
| | ENTRY_PRICE_MULTIPLIER | 1.001 (0.1%) | Above current price for entry |
| | MIN_RISK_REWARD_RATIO | 1.0 | Minimum acceptable R:R |
| | TARGET_RR | 4.346 | Optuna trial #433 tp_multiple |
| | TRAIL_ATR_MULT | 4.162 | Optuna v4 baseline / BASE default |
| **V5 Trail Multipliers** | VCP_TRAIL_ATR_MULT | 2.0 | Tight for fast breakouts |
| | PULLBACK_TRAIL_ATR_MULT | 3.0 | Moderate for trends |
| | RES_BREAKOUT_TRAIL_ATR_MULT | 4.25 | Wide for room to develop |
| | BASE_TRAIL_ATR_MULT | 4.162 | Same as fallback |
| **Position Sizing** | RISK_PER_TRADE_PCT | 1.0 | Risk 1% per trade |
| | MAX_POSITION_SIZE_PCT | 20.0 | Max position size |
| | MAX_OPEN_POSITIONS | 5 | Max concurrent open positions |
| **Phase 3 Scoring** | RS_RANK_MIN_PERCENTILE | 70 | Gate: skip RS < 70 |
| | TOP_SECTORS_N | 8 | Top N sectors (raised from 5) |
| | MIN_SETUP_SCORE | 70 | Gate: discard score < 70 |
| | SCORE_WEIGHT_RS_RANK | 30 | RS percentile weight |
| | SCORE_WEIGHT_RR | 20 | R:R weight |
| | SCORE_WEIGHT_VOL | 20 | Volume/momentum weight |
| | SCORE_WEIGHT_REGIME | 15 | Market regime alignment |
| | SCORE_WEIGHT_SECTOR | 10 | Top sector bonus |
| | SCORE_WEIGHT_QUALITY | 5 | Pattern quality bonus |
| | SCORE_SELECTIVE_REGIME_FACTOR | 0.53 | SELECTIVE earns 53% of AGGRESSIVE |
| **Regime Scoring** | REGIME_WEIGHT_EMA20 | 20 | SPY close > EMA20 |
| | REGIME_WEIGHT_SMA50 | 15 | SPY close > SMA50 |
| | REGIME_WEIGHT_MA_STACK | 15 | SMA50 > SMA200 |
| | REGIME_WEIGHT_SLOPE | 10 | EMA20 slope |
| | REGIME_WEIGHT_BREADTH | 20 | % universe above SMA50 |
| | REGIME_WEIGHT_HL | 10 | 52-week H/L ratio |
| | REGIME_WEIGHT_VIX | 10 | VIX below SMA20 |
| | REGIME_AGGRESSIVE_THRESHOLD | 70 | 70-100 = AGGRESSIVE |
| | REGIME_SELECTIVE_THRESHOLD | 59 | 40-69 = SELECTIVE (Optuna v4 best, was 54) |
| **Options (Engine 7)** | OPTIONS_MIN_ADV | 500K | Options liquidity gate |
| | OPTIONS_MIN_PRICE | $10 | Min share price |
| | OPTIONS_DTE_MIN, OPTIONS_DTE_MAX | 7, 45 | Days to expiry range |
| | OPTIONS_OTM_MAX_PCT | 0.10 (10%) | Max OTM % for strike |
| | OPTIONS_MIN_SCORE | 45 | Minimum score to flag |
| **Liquidity Gates** | LIQUIDITY_MIN_AVG_VOLUME | 750K | 50-day median (raised from 500K) |
| | LIQUIDITY_MIN_DOLLAR_VOLUME | $25M | Raised from $20M |
| **Backtest** | BACKTEST_DIAG_START_DATE | "2023-01-01" | Fixed 2-year baseline |
| | BACKTEST_DIAG_END_DATE | "2024-12-31" | Fixed 2-year baseline |
| | BACKTEST_V4_TRAIL_MULT | 4.162 | V4 strict single trail |
| **Universe Loading** | UNIVERSE_MAX_AGE_DAYS | 7 | Hard cutoff for age |
| | UNIVERSE_WARN_AGE_DAYS | 5 | Soft warning threshold |
| | UNIVERSE_MIN_SIZE | 800 | Warn if smaller |
| | UNIVERSE_MAX_SIZE | 2,500 | Warn if larger |
| **Discovery Layer** | DISCOVERY_RS_MIN | 60 | RS rank lower bound |
| | DISCOVERY_RS_MAX | 70 | RS rank upper bound (exclusive) |
| | DISCOVERY_52WK_HIGH_PCT | 0.03 (3%) | Close must be within 3% of 52wk high |
| | DISCOVERY_VOL_RATIO | 1.5 | 5-day avg vol â‰¥ 1.5x 50-day |
| | DISCOVERY_MAX_PCT | 0.10 (10%) | Cap at 10% of universe |
| **RES_BREAKOUT (Engine 6)** | RES_LAUNCHPAD_BARS | 5 | Pre-breakout consolidation (was 3) |
| | RES_DECISIVE_MIN_PCT | 0.02 (2%) | Min % above zone |
| | RES_DECISIVE_ATR_FACTOR | 0.5400 | Optuna v4 best (was 0.4725) |
| | RES_STOP_ATR_FACTOR | 0.8 | Stop = zone_lower âˆ’ 0.8Ã—ATR |
| | RES_BREAKOUT_VOL_MULT | 2.0 | Min volume Ã—50d avg |
| | RES_MAX_GAP_PCT | 0.036 (3.6%) | Max gap on T+1 entry |
| | RES_SELECTIVE_REGIME_FACTOR | 0.80 | Score multiplier in non-AGGRESSIVE |
| **Engine Contraction** | VCP_ATR_CONTRACTION_THRESHOLD | 0.6 | ATR < 60% of 20-bar avg |
| | VCP_MIN_CONTRACTIONS_STRICT | 3 | DRY requires â‰¥3 |
| | VCP_MIN_CONTRACTIONS_RELAXED | 2 | BRK/TDL require â‰¥2 |
| **Data Fetching** | DATA_FETCH_PERIOD | "1y" | 252 bars per ticker |
| | CONCURRENCY_LIMIT | 64 | Backtest safe (parquet only) |
| | FETCH_MAX_RETRIES | 4 | Retry attempts |
| | FETCH_BACKOFF_BASE | 5.0 | Exponential backoff base |
| | CACHE_TTL_SUCCESS | 14400 | 4-hour success cache |
| | CACHE_TTL_FAILURE | 900 | 15-min failure cache |

**Issues Found:**
1. **Optuna Convergence**: Multiple constants marked "Optuna v4 best" vs "v3" but no version management system. If a new Optuna run finds better values, manual edit required.
2. **Inconsistent Naming**: `RS_RANK_MIN_PERCENTILE = 70` vs `REGIME_SELECTIVE_THRESHOLD = 59` inconsistent thresholds with no clear relationship documented.
3. **SCORE_WEIGHT_RS_QUALITY = 20** defined but never used in scoring.py (dead code)
4. **TOP_SECTORS_N = 8** but `SECTOR_TIER1_N = 5` creates implicit tier system with no cross-reference documentation
5. **Regime Thresholds**: `REGIME_AGGRESSIVE_THRESHOLD = 70` and `REGIME_SELECTIVE_THRESHOLD = 59` (was 40 in CLAUDE.md spec, now 59) â€” change not documented in comments
6. **V5 Trail Multipliers**: Hard-coded per-setup dict in code, not dynamically tunable â€” stored in constants but `_TRAIL_ATR_BY_SETUP` in backtest_engine.py points to them indirectly

**Suspicious Values:**
- None detected; all appear to be well-calibrated from Optuna

---

### 3. MARKET REGIME (Engine 0)

**What It Does:**
Multi-factor regime scoring system (0-100). Returns regime classification (AGGRESSIVE/SELECTIVE/DEFENSIVE) and 7-factor breakdown.

**7 Factors (Total = 100 pts):**
1. **f1 (20 pts)**: SPY close > EMA20
2. **f2 (15 pts)**: SPY close > SMA50
3. **f3 (15 pts)**: SMA50 > SMA200 (MA stack â€” Stage 2 market)
4. **f4 (10 pts)**: EMA20 slope over 5 bars (linear scale: -0.5% â†’ 0 pts, +0.5% â†’ 10 pts)
5. **f5 (20 pts)**: % universe above SMA50 (breadth_pct Ã— 20)
6. **f6 (10 pts)**: 52-week H/L ratio (hl_ratio Ã— 10)
7. **f7 (10 pts)**: VIX < VIX SMA20

**Thresholds:**
- **AGGRESSIVE**: 70-100 â†’ Full engine suite enabled
- **SELECTIVE**: 40-69 â†’ All engines enabled, size conservatively (53% of AGGRESSIVE regime pts in scoring)
- **DEFENSIVE**: 0-39 â†’ Engines 2 & 3 disabled

**Current Implementation (engine0.py):**
- Fetches 1y SPY daily + 3mo VIX
- Computes all 7 factors + returns dict with breakdown
- Factors 5-7 require live universe data (breadth, H/L ratio, VIX), passed from main.py
- Handles missing data gracefully (returns error dict with regime="ERROR: ...")

**Issues Found:**
1. **Factor 4 (Slope) Bug**: Line 130 uses `(pct_slope + 0.005) / 0.01 * REGIME_WEIGHT_SLOPE` â€” this means +0.5% slopes get 0 pts, not 10 pts. Formula assumes slope is in [-0.005, +0.005] range but doesn't scale correctly. **Should be `abs(pct_slope) / 0.01 * REGIME_WEIGHT_SLOPE`** for symmetric handling.
2. **VIX Fetch Failure Silent**: Line 161 catches all exceptions silently â€” F7 scores 0 if VIX unavailable. Better to log warning.
3. **Filter Inconsistency**: `_error()` returns regime="ERROR: ..." but code treats this as valid regime string downstream (see main.py usage).

**Gaps:**
- No real-time breadth/H/L ratio computation in engine0 itself (must be pre-computed by main.py and passed in)
- No caching of regime score (refetches SPY/VIX every time check_market_regime() called)

---

### 4. ENGINE 1 (S/R Zones via KDE)

**What It Does:**
Detects support/resistance zones using Gaussian KDE on weekly price points with recency weighting.

**Algorithm:**
1. Resample daily OHLCV â†’ weekly
2. Extract weekly closes + pivot highs/lows (adaptive window)
3. Apply recency weights: 2.0Ã— for â‰¤90 days, 1.0Ã— for â‰¥365 days, linear interpolation
4. Gaussian KDE with dynamic bandwidth (Scott's rule Ã— coefficient of variation)
5. Find peaks via `find_peaks()` with prominence threshold at 5th percentile
6. Convert peaks to zones: level Â± (0.2 Ã— Daily ATR)
7. Merge zones within 1 ATR of each other

**Output Shape:**
```python
[
  {"level": 150.5, "upper": 151.2, "lower": 149.8, "type": "RESISTANCE", "atr": 0.35},
  {"level": 145.0, "upper": 145.7, "lower": 144.3, "type": "SUPPORT", "atr": 0.35},
]
```

**Current Params:**
- Lookback: 2 years (auto-loads if df=None)
- Zone half-width: 0.2 Ã— ATR14
- KDE bandwidth: Scott's rule Ã— CV scale factor (0.4-1.2)
- Merge threshold: 1 Ã— ATR

**Issues Found:**
1. **Peak Detection Sensitivity**: Line 143 uses `np.percentile(density, 5)` as prominence threshold â€” very lenient. On noisy stocks this may detect micro-peaks. No tunable parameter.
2. **Zone Width Hardcoded**: 0.2 Ã— ATR not configurable â€” may be too tight for high-ATR stocks, too wide for low-ATR.
3. **Recency Weighting**: Weight goes 2.0 â†’ 1.0 over 275 days (90 to 365) but formula is linear. Non-linear decay (e.g. exponential) might better emphasize recent structure.
4. **Boundary Handling**: Line 137-138 uses `p_min Ã— 0.98` and `p_max Ã— 1.02` margins â€” if price near edge, can miss zones just outside bounds.

**Data Quality Gaps:**
- No validation that weekly resample has minimum bars (len(weekly) < 10 â†’ return [])
- If ATR â‰¤ 0, function returns [] silently

---

### 5. ENGINE 2 (VCP Breakout)

**What It Does:**
Detects volatile consolidation patterns (VCP = Volatility Contraction Pattern).

**Three Detection Paths:**
1. **PATH A (DRY)**: Coiled spring within 5% of resistance
   - Trend: 8 EMA > 20 EMA AND close > 50 SMA
   - Contraction: TR last 5 bars < TR prior 20 bars (0.6Ã— threshold)
   - U-shape: scipy curve_fit parabola, a > 0 (upward curvature)
   - Volume dry-up: last 3 days avg vol < 50-day SMA
   - Location: within 5% below resistance zone

2. **PATH B (BRK)**: Confirmed breakout above resistance
   - Trend: same as DRY
   - Location: close STRICTLY ABOVE zone upper boundary, within 0.5-3% above
   - Volume: â‰¥150% of 50-day SMA
   - RS Filter: 3m return > SPY 3m return - 5% (rs_vs_spy > -0.05)

3. **PATH C (TDL)**: Trendline breakout
   - Descending resistance trendline detected
   - Breakout: close 0-3% above TDL + vol â‰¥100% SMA

**Risk Math (all paths):**
- Entry: High Ã— 1.001
- Stop: min(Low, zone_lower) âˆ’ 0.8 Ã— ATR
- Take Profit: Entry + 2 Ã— Risk (1:2 R:R, can override with params.tp_multiple)

**Current Params:**
- TR contraction threshold: 0.6 (last 5 bars < 60% of 20-bar avg)
- Trendline breakout tolerance: 0-3% above TDL
- RS gate for BRK: -0.05 (loose, allows flat-vs-SPY)

**Issues Found:**
1. **Trendline Cache Keys**: Lines 45-52 cache trendlines by (ticker, date, lookback) but date is str(index[-1].date()) â€” if data refreshed at different time, cache misses. Should use data hash or timestamp-independent key.
2. **U-Shape Detection**: Lines 225+ use scipy.optimize.curve_fit but no validation that fit succeeded (residuals, RÂ²). Degenerate parabolas (near-linear) can pass.
3. **PATH B (BRK) Logic**: Requires `rs_vs_spy > -0.05` but rs_vs_spy is 3m momentum. For recently IPO'd or SPY-neutral stocks, this may be too strict. **No relaxation in SELECTIVE regime** â€” BRK gets full gate regardless of regime.
4. **Watchlist Fallback**: If near-breakout (within 1.5% of resistance), returns WATCHLIST setup instead of None. This could flood watchlist with weak signals in downtrends.

**Gaps:**
- No volume profile analysis (classic VCP requires volume consolidation, not just dryup in last 3 days)
- Trendline detection complex but not well-documented; three-rule rewrite in comments hints at past bugs
- **RS Filter Gate Placement**: RS gate happens AFTER trend check but BEFORE indicator computation â€” if removed, would need to move earlier

---

### 6. ENGINE 3 (Tactical Pullback)

**What It Does:**
Detects high-quality pullbacks to 8/20 EMA value zone with structural support confirmation + CCI momentum hook.

**Filter Chain (All Must Pass â€” Strict Mode):**
1. **Trend**: 8 EMA > 20 EMA AND close > 50 SMA
2. **Value Zone**: Daily low penetrates 8 EMA or 20 EMA
3. **Structural Support**: Low touches KDE zone OR consolidation low OR demand zone OR ascending trendline
   - Priority order checked in `_find_structural_support()`
4. **Pin Bar Rejection**: Close â‰¥ 20 EMA (closed back above after penetrating)
5. **CCI Hook**: CCI[âˆ’1] < CCI_STRICT_FLOOR (âˆ’39.10) AND CCI[0] > CCI[âˆ’1]

**Relaxed Mode (4 conditions relaxed, 1 still required):**
1. **Trend (Relaxed)**: 8 EMA > 20 EMA AND close > SMA50Ã—0.97 (allows SMA50 test)
2. **Value Zone (Relaxed)**: Low penetrates EMA8/EMA20 OR close within 4% of EMA8/EMA20
3. **CCI Hook (Relaxed)**: CCI[âˆ’1] < âˆ’20 (CCI_RLX_FLOOR, âˆ’1.95) AND CCI[0] > CCI[âˆ’1]
4. **Volume**: No hard gate (shakeout reversals allowed)
5. **Structural Support (REQUIRED)**: Still must find support from KDE/consolidation/demand/TDL

**Risk Math:**
- Entry: High Ã— 1.001
- Stop: min(Low, zone_lower) âˆ’ 0.8 Ã— ATR
- Take Profit: Entry + 2 Ã— Risk (or params.tp_multiple if set)

**RS Gate:**
- `RS_REJECT_THRESHOLD = -0.01219` (Optuna v4 best)
- Rejects stocks persistently underperforming SPY

**Structural Support Priority (engine3.py lines 75-194):**
1. **KDE Zone** (SUPPORT type, within Â±2.5% tolerance)
2. **Consolidation Low** (3-bar pivot, bounced 3+ of next 5 bars)
3. **Demand Zone** (high-volume reversal bar, â‰¥150% avg vol)
4. **Ascending Trendline** (within 1.5% tolerance)

**Current Params:**
- CCI_STRICT_FLOOR: âˆ’39.10 (Optuna v4)
- CCI_RLX_FLOOR: âˆ’1.95 (Optuna v4; was âˆ’20 in v3)
- RS_REJECT_THRESHOLD: âˆ’0.01219
- ATR_STOP_MULTIPLIER: 1.278 (Optuna v4, was 1.360 in v3)

**Issues Found:**
1. **CCI_RLX_FLOOR Way Too Loose**: âˆ’1.95 is essentially neutral CCI; almost any bar qualifies. Relaxed mode becomes too permissive. **Recommend: âˆ’15 to âˆ’25 range.**
2. **Structural Support Priority Edge Case**: Consolidation low detection uses `candidate <= min(low_vals[max(0, i-3):i])` but this is a 3-bar pivot, not 5-bar. Comment says "3% proximity + bounce guards compensate" but not documented well.
3. **Demand Zone False Positives**: High-volume bars near session lows can be liquidation, not accumulation. No filter for close direction (bar_close > bar_open required, but bar_open estimated as prev close).
4. **Ascending Trendline Validation**: No check that trendline actually touches recent price action before today.

**Data Quality Gaps:**
- If fewer than 8 recent bars, function short-circuits with return None but doesn't log why
- CCI calculation requires 20 bars; if fewer available, NaN values not explicitly handled

---

### 7. ENGINE 4 (RS Line)

**What It Does:**
Detects institutional accumulation via Relative Strength (RS) Line analysis.

**Key Functions:**
1. **calculate_rs_line()**: ticker_close / spy_close (rolling 252 days)
2. **detect_rs_blue_dot()**: current RS ratio â‰¥ 52-week RS high Ã— 0.995 (0.5% tolerance)
3. **calculate_rs_score()**: O'Neil composite RS score
   - Formula: `(63dÃ—40%) + (126dÃ—20%) + (189dÃ—20%) + (252dÃ—20%)`
   - Each component = stock_period_return âˆ’ spy_period_return
   - Positive = outperforming SPY

**Current Params:**
- Blue Dot Tolerance: 0.5% (RS_BLUE_DOT_TOLERANCE_PCT = 0.005)
- Min bars for RS: 252 (1 year)
- RS periods: 63, 126, 189, 252 days

**Algorithm (engine4.py):**
- Aligns ticker & SPY closes by common date intersection
- Calculates RS ratios as pairwise division
- Returns last 252 days only

**Issues Found:**
1. **Blue Dot False Positives**: 0.5% tolerance is very tight. For volatile stocks, RS can oscillate within this band frequently. **Recommend: 1-2% tolerance**.
2. **Missing Data Handling**: If ticker & SPY have different trading calendars (e.g., stock was halt, SPY traded), `common_dates` intersection may be short. No warning if < 252 days available.
3. **RS Score Weighting**: Hardcoded as (40%, 20%, 20%, 20%) per O'Neil, but recent O'Neil research suggests different weighting for momentum. **Not tunable in Optuna**.
4. **No Lookback Validation**: `calculate_rs_score()` silently skips periods with insufficient bars but redistributes weights. Edge case: if only 252 bars available, short periods (63d, 126d) skipped and 252d gets 100% weight.

**Gaps:**
- No RS Line visualization in frontend (only blue dot flag)
- RS score used in scoring but not in live Engines 2, 3 (could tighten breakout/pullback gates)

---

### 8. ENGINE 5 (Base Patterns)

**What It Does:**
Detects two base patterns: ATR-adjusted Darvas box (flat base) and proportional cup & handle.

**Pattern A â€” Darvas Box (Flat Base):**
- Stage 2 uptrend: SMA50 > SMA200 AND close > SMA50
- Lookback: 20-40 days, accept widest window that passes gates
- Tightness: box height â‰¤ 3.5 Ã— ATR14 (ATR-proportional, not fixed)
- Ceiling tested â‰¥2Ã— (within 0.5 Ã— ATR of ceiling)
- Close in upper 25% of box (coiled near breakout)
- Volume dry-up: 3-day avg vol < 50-day SMA

**Signal Types:**
- **BRK**: close > ceiling + volume â‰¥ min_vol_ratio Ã— SMA50 + range contraction (prior 20 vs recent 5)
- **DRY**: distance to ceiling â‰¤ 1% (coiling without breakout)

**Pattern B â€” Cup & Handle:**
- Lookback: 120 days
- ATR-proportional depth: 15% â‰¤ depth â‰¤ (ATR_pct Ã— 10)
  - High-ATR stocks can have deeper cups; low-ATR cannot
- Peak-to-low duration â‰¥ 25 days (no V-shapes)
- Current price in upper 50% of cup depth
- Handle ATR < decline-phase ATR (volatility must contract)

**Quality Score (0-100):**
- 25 pts: RS vs SPY (3m outperformance)
- 25 pts: Tightness (ATR-relative box/depth)
- 25 pts: Volume dry-up (vs 50-day avg)
- 25 pts: RS near 52-week high (blue dot)
- **Minimum quality_min = 25 to output** (tunable in params)

**Risk Math:**
- Entry: ceiling/handle_high Ã— 1.001
- Stop: floor âˆ’ 0.2 Ã— ATR14
- Take Profit: nearest KDE resistance (fallback: Entry + tp_multiple Ã— Risk)

**Current Params:**
- BASE_BRK_MIN_VOL_RATIO: 1.5 (raised from 1.2)
- Darvas box height: â‰¤ 3.5 Ã— ATR
- Cup depth range: 15% to (ATR_pct Ã— 10)
- Handle contraction: ATR < decline ATR

**Issues Found:**
1. **ATR-Proportional Depth Unclear**: Line 17 says "15% â‰¤ depth â‰¤ (ATR_pct Ã— 10)" but ATR_pct not defined in header. Looking at code (line 272+), ATR_pct is depth/price in decimal form, so max depth = depth/price Ã— 10. This is confusing.
2. **Quality Score Gate Weak**: min_quality = 25 means ANY base with one metric passing gets flagged. Should be higher or weighted differently.
3. **Cup Peak Definition**: Uses `np.argmax()` of 120-day lookback but doesn't validate that peak is followed by drop. Could detect "wedge up" as cup top.
4. **Handle Tightness Check**: Volume dry-up required, but handle ATR requirement is standalone check. No integration with prior volume to define handle properly.

**Data Quality Gaps:**
- Requires close > SMA200, but SMA200 not computed (reliance on pre-computed indicator)
- No validation of lookback window (if < 60 bars, silently returns None)

---

### 9. ENGINE 6 (Resistance Breakout)

**What It Does:**
Detects institutional-quality breakouts using multi-source resistance detection (Donchian, pivot highs, KDE zones).

**Resistance Sources:**
1. **Donchian High** (rolling N-bar high, always produces level)
2. **Pivot Highs** (structural turning points)
3. **KDE Zones** (optional supplement from Engine 1)

**Breakout Signal Logic:**
- pre_close â‰¤ resistance AND brk_close > resistance Ã— (1 + buffer)
- buffer = RES_DECISIVE_MIN_PCT (0.02 = 2%)

**Quality Filters (Optuna-tunable):**
- Volume expansion: brk_vol â‰¥ vol_mult Ã— 50-day avg
- ATR expansion: bar range â‰¥ atr_expansion Ã— ATR14
- Consolidation: price within 8% of resistance in last N bars
- Trend filter: close > 50 SMA
- Overextension gate: close â‰¤ resistance Ã— 1.05 (5% max above)

**Risk Math:**
- Entry: high Ã— 1.001
- Stop: resistance âˆ’ stop_atr Ã— ATR14 (stop_atr = 0.8 default)
- Take Profit: nearest upstream resistance, else Entry + tp_multiple Ã— Risk

**Current Params (Optuna v5 #433):**
- brk_vol_mult: 3.0161 (Ã—50d avg)
- brk_stop_atr: 1.6675
- brk_min_pct: 0.04333 (4.3% above resistance)
- brk_gap_pct: 0.036 (3.6% max gap on T+1)
- brk_trail_mult: 6.9060 (ATR trail)
- brk_regime_factor: 0.861 (score penalty in SELECTIVE)
- brk_aggressive_only: True (skip BRK in SELECTIVE regime)
- brk_donchian_n: 87 (rolling-high lookback)
- brk_pivot_strength: 2 (bars each side for pivot)
- brk_atr_expansion: 1.474 (Ã—ATR min bar range)
- brk_min_consolidation: 10 (bars near resistance)

**Issues Found:**
1. **Consolidation Window Edge Case**: Line 208+ checks if price was within 8% of resistance in last N bars, but calculation uses `resistance Ã— 0.92` as lower bound. For gapped-up resistance zones, this is misleading.
2. **Pivot High Detection**: Uses argrelextrema with strength tunable, but no minimum duration between pivots enforced (can have noise spikes).
3. **Gap Filter Loose**: brk_gap_pct = 0.036 (3.6%) is the same as RES_MAX_GAP_PCT constant. For high-price stocks, 3.6% gap is huge ($5+ on $150 stock).
4. **Volume Requirement Inconsistent**: brk_vol_mult = 3.0161 seems very high (3x 50-day avg) vs RES_BREAKOUT_VOL_MULT = 2.0 in constants. **Which is authoritative?** (Appears BacktestParams.brk_vol_mult overrides constant.)

**Data Quality Gaps:**
- Donchian computation excludes current bar (shift(1)) â€” correct for no lookahead
- If no Donchian level available (e.g., lookback > len(df)), fails gracefully but no warning

---

### 10. ENGINE 7 (Options Catalyst)

**What It Does:**
Detects unusual near-term call options activity (7-45 DTE) on liquid tickers as potential catalyst signal.

**Signal Components:**
- Vol/OI ratio (positioning momentum)
- Call volume (absolute activity)
- Call/Put skew (bullish sentiment)
- IV term slope (volatility structure)

**Liquidity Gates:**
- Avg daily options volume â‰¥ 500K
- Share price â‰¥ $10
- 7-45 DTE range
- Strike filter: 0-10% OTM

**Scoring:**
- Base 5.0 + vol/OI bonus (0-2) + call vol bonus (0-2) + skew bonus (0-2) + IV slope bonus (0-2)
- Min score to flag: 45

**Technical Requirement:**
- Relaxed: close > SMA50 + close > close[-10] (not falling knife)

**Current Params:**
- OPTIONS_MIN_ADV: 500K
- OPTIONS_MIN_PRICE: $10
- OPTIONS_DTE_MIN: 7, OPTIONS_DTE_MAX: 45
- OPTIONS_OTM_MAX_PCT: 0.10 (10%)
- OPTIONS_MIN_SCORE: 45

**Issues Found:**
1. **yfinance Options Fetch Unreliable**: Lines 66+ use yf.Ticker().options + option_chain() which is known to have bugs/rate limits. Code catches exceptions and returns None, but no retry logic.
2. **IV Term Slope Edge Case**: Line 139 defaults to "flat term structure" (iv_term_slope = 1.0) if < 2 expiries. On early morning or low-volume tickers, this false-positive.
3. **Put Volume Skew**: Line 108 sums put volume as denom, but doesn't validate that puts have any volume. Low-volume puts + some calls = inflated skew.
4. **Missing Delta Filter**: No check that calls are actually OTM by delta (just by strike). A call struck at current price (delta â‰ˆ 0.5) is not OTM.

**Gaps:**
- No IV crush modeling (catalyst may have already priced in)
- No earnings-date check (catalyst options often peak right before earnings, worthless after)

---

### 11. ENGINE 8 (High Tight Flag)

**What It Does:**
Detects the High Tight Flag â€” one of the highest-conviction O'Neil patterns.

**Conditions:**
1. **Strong Prior Move**: â‰¥80% gain within 40 trading days (low before high in lookback window)
2. **Flag Consolidation**: depth â‰¤25%, duration 5-20 bars after runup high
3. **Breakout**: today's close > flag_high, not overextended (â‰¤5% above)
4. **Volume**: breakout day â‰¥ 1.5Ã— 20-day average

**Risk Math:**
- Entry: close Ã— 1.001
- Stop: flag_low âˆ’ 0.8 Ã— ATR14
- Take Profit: Entry + TARGET_RR Ã— Risk

**Current Params:**
- HTF_MIN_RUNUP_PCT: 0.80 (80%)
- HTF_LOOKBACK_DAYS: 40
- HTF_MAX_FLAG_DEPTH_PCT: 0.25 (25%)
- HTF_MIN_FLAG_BARS: 5
- HTF_MAX_FLAG_BARS: 20
- HTF_MAX_EXTEND_PCT: 0.05 (5%)
- HTF_MAX_RISK_PCT: 0.35 (35% â€” wide stop allowed)

**Issues Found:**
1. **Lookback Window Edge Case**: Lines 74-79 look back at `close_arr[-lookback - 1:-1]` (excluding today). If lookback > array length, `period_close` becomes entire array except last 2 bars. No validation that lookback is reasonable.
2. **Runup Timing**: Requires low BEFORE high within the 40-day window, but doesn't check if low is truly a local minimum. A stock that starts high, dips, then rallies will be detected.
3. **Flag Consolidation Ambiguity**: Lines 97-113 define flag as bars from runup high to yesterday. If runup high happens at bar[100], flag = [bars 100 to n-1]. But what if stock consolidates below runup high in bars 0-99? Not checked.

**Gaps:**
- No volume profile check (flag should have "dry" volume contraction)
- No support level identification (stop placement seems arbitrary at flag_low)

---

### 12. ENGINE 9 (Low Cheat Entry / LCE)

**What It Does:**
Detects mini-breakout entries just below a resistance level.

**Conditions:**
1. **Resistance Zone**: KDE cluster or recent SUPPORT zone just above current price
2. **Proximity**: close within 3% below resistance
3. **Higher Low**: 3-bar recent low > 5-bar prior low (bars -8 to -3)
4. **Trend**: close â‰¥ SMA50
5. **Mini-Breakout**: close > prior bar high
6. **Volume Expansion**: today's vol â‰¥ 1.0x 20-day avg

**Risk Math:**
- Entry: current close
- Stop: 5-bar swing low âˆ’ 0.8 Ã— ATR14
- Take Profit: resistance_upper Ã— 1.005
- Max risk: 15%

**Current Params:**
- LCE_MAX_DISTANCE_PCT: 0.03 (3% below resistance)
- LCE_VOL_CONTRACTION_RATIO: 0.80 (5-bar avg â‰¤ 80% of 20-day)
- LCE_MAX_RISK_PCT: 0.15 (15%)
- LCE_TIGHT_RANGE_CONTRACTION: 0.70 (5-bar < 70% of prior range)
- LCE_BREAKOUT_VOL_RATIO: 1.0 (â‰¥ 1x 20-day avg)

**Issues Found:**
1. **Higher Low Logic Weak**: Lines 96-104 check if recent_low > prior_low, but with only 3 bars recent vs 5 bars prior, a single outlier can break pattern.
2. **Mini-Breakout Timing**: Line 115 checks if `close > high[-2]` (yesterday's high). But previous bar might be a small doji. No validation that breakout is meaningful.
3. **Volume Ratio Gate Missing**: Constants define LCE_VOL_CONTRACTION_RATIO (lines 36-38) but it's NEVER USED in engine9_low_cheat.py. Only LCE_BREAKOUT_VOL_RATIO is checked.

**Gaps:**
- No KDE zone type validation (accepts both RESISTANCE and SUPPORT zones above price)
- Stop calculation at flag_low is very loose for a "low cheat" entry

---

### 13. MAIN SCAN PIPELINE (main.py)

**Scan Flow (_run_scan()):**

1. **Prefetch SPY + Universe**
   - Fetch 1y SPY for RS calculations
   - Prefetch all universe tickers (250/batch, 1s delay between batches)
   - Cache in module-level `_ticker_cache`

2. **Compute Cross-Sectional Metrics**
   - `compute_rs_rank_map()`: percentile rank 0-100 for all tickers
   - `compute_top_sectors()`: avg RS score per sector, top 8 by avg
   - `check_market_regime()`: 7-factor regime score + thresholds

3. **Per-Ticker Processing Pipeline:**
   ```
   For each ticker in ACTIVE_UNIVERSE:
     a) Vitality check (10-day H-L range > 2%)
     b) RS rank gate (â‰¥70 percentile) â€” SKIP if below
     c) Liquidity gate (50-day median vol â‰¥750K, dollar vol â‰¥$25M)
     d) Earnings blackout check (within Â±7 calendar days)
     e) Compute indicators (EMA8/20, SMA50/200, CCI20, ATR14, trendline)
     f) Run Engines 1-9 (based on regime tier)
     g) Collect all setups from all engines
     h) Discovery layer (RS 60-70 emerging leaders bypass RS gate)
   ```

4. **Scoring & Filtering**
   - `score_and_filter_setups()`: 6-component unified score, min_score â‰¥70 gate
   - `_inject_hot_sector()`: mark sectors with â‰¥3 setups as hot
   - Sort by score descending

5. **Persist to SQLite**
   - `batch_save_setups()`: single transaction with executemany()
   - Save S/R zones
   - Save regime + breadth/H-L metrics

**Current Endpoints (FastAPI):**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/run-scan` | POST | Trigger background scan |
| `/api/scan-status` | GET | Poll progress |
| `/api/regime` | GET | Latest SPY regime from DB |
| `/api/setups/{type}` | GET | Setups by type (vcp, pullback, base, res-breakout, htf, lce) |
| `/api/setups/options-catalyst` | GET | Options setups |
| `/api/watchlist` | GET | Watchlist (near-breakout) setups |
| `/api/sr-zones/{ticker}` | GET | S/R zones for ticker from last scan |
| `/api/chart/{ticker}` | GET | OHLCV + indicators (fresh fetch) |
| `/api/prices` | GET | Live prices (60s cache) |
| `/api/debug/{ticker}` | GET | Dev mode: per-engine pass/fail |
| `/api/health` | GET | Health check |
| `/api/trades` | POST/GET | Portfolio management |
| `/api/backtest` | POST | Run backtest |
| `/api/wfo/*` | POST/GET | Walk-forward optimization |
| `/api/build-universe` | POST | Rebuild universe from SEC |

**Key Gating Order:**
1. Vitality check
2. RS rank gate (â‰¥70) â€” **NOT disabled in SELECTIVE**
3. Liquidity gate
4. Earnings blackout
5. Regime filter (DEFENSIVE disables E2 & E3 only)
6. Setup scoring (MIN_SETUP_SCORE = 70)

**Issues Found:**

1. **RS Rank Gate Too Strict**: 70 percentile is high. In a bull market, many leaders trade 50-70 RS. **Discovery layer (RS 60-70) partially mitigates but only 10% of universe.**
2. **Engine Gating Bug**: DEFENSIVE regime (< 40) disables Engines 2 & 3, but code doesn't track which engines were skipped. If you look at engine_stats, you can't tell if VCP=0 because none found or regime disabled it.
3. **Trendline Computation Expensive**: `detect_trendline()` called every scan for every ticker, even if not used (Engine 3 pullback is optional in SELECTIVE regime).
4. **Precomputed Indicators Cache**: `compute_indicators()` computes EMA/SMA/CCI/ATR, but code doesn't pre-cache these in prefetch phase. Computed multiple times per ticker per scan.
5. **Earnings Cache Thread-Unsafe**: Line 382 uses `_earnings_cache_lock` but concurrent prefetch threads don't acquire lock before reading `_ticker_cache`.
6. **SPY Fetch Failure Silent**: If `yf.download("SPY", ...)` fails, RS ranking returns {} empty dict. Main code guards with `if _rs_rank_map:` (line ~600) but silently skips RS gate if empty. **Better to return early with error.**
7. **Hot Sector Threshold Arbitrary**: Line ~700 marks sector hot if â‰¥3 setups found. On a slow market, this might never trigger. **Should scale with regime or universe size.**

**Concurrency & Performance:**
- `asyncio.Semaphore(CONCURRENCY_LIMIT)` caps concurrent yfinance requests
- `asyncio.gather()` per-ticker (parallelizes Engines 1-9 for same ticker)
- Backtest mode raises CONCURRENCY_LIMIT to 64 (parquet only, safe)
- Prefetch batches: 250/batch, 1s delay between

**Database Persistence:**
- All results keyed by `scan_timestamp` (immutable snapshots)
- `metadata` JSON column for extensible fields
- `batch_save_setups()` uses `executemany()` (single transaction, ~1000 inserts/sec)

---

### 14. SCORING SYSTEM (scoring.py)

**Public API:**

```python
compute_rs_rank_map(ticker_cache, tickers, spy_df, sample_size=600)
  â†’ Dict[str, float]  # ticker â†’ percentile 0-100

compute_top_sectors(ticker_cache, tickers, sectors, spy_df, top_n=8)
  â†’ List[str]  # sector names, best-first

compute_setup_score(setup, rs_rank, regime_score, regime, top_sectors)
  â†’ int  # 0-100 unified score

score_and_filter_setups(setups, rs_rank_map, regime, top_sectors, min_score)
  â†’ List[Dict]  # filtered + scored + sorted by setup_score desc
```

**Score Components (6-part, weights sum to 100):**

| Component | Weight | Calculation |
|-----------|--------|-------------|
| **RS Rank** | 30 | Percentile from compute_rs_rank_map; Tier 1 (â‰¥85) Ã— 1.15 bonus |
| **R:R Ratio** | 20 | `(reward_risk - 1.0) / 3.0 * 20` capped at 20; min RR=1.0 |
| **Volume/Momentum** | 20 | Setup-type-aware: VCP/BASE/RES_BREAKOUT use vol_ratio; PULLBACK uses support_source baseline (6 pts); WATCHLIST uses proximity + blue_dot; OPTIONS uses options_score |
| **Regime Alignment** | 15 | AGGRESSIVE â†’ 15; SELECTIVE â†’ 8 (Ã—0.53 factor); DEFENSIVE â†’ 0 |
| **Sector Strength** | 10 | Top-5 sectors â†’ 10; sectors 6-8 â†’ 8 (Ã—0.8); others â†’ 4 (Ã—0.4) |
| **Pattern Quality** | 5 | rs_blue_dot present â†’ 5; otherwise 0 (only flag) |
| **RS Quality (unused)** | 20 | Defined but never applied in code |

**RS Ranking Algorithm:**
1. Compute O'Neil RS score for each ticker (periods: 63/126/189/252 days, weights: 40%/20%/20%/20%)
2. Sort all scores
3. For each ticker, percentile = (count_below / total) Ã— 100
4. Edge case: if < 2 tickers, all scored as 50%

**Sector Strength Algorithm:**
1. Bucket tickers by sector
2. Compute avg O'Neil RS score per sector
3. Sort sectors by avg RS descending
4. Return top-N sector names

**Issues Found:**

1. **SCORE_WEIGHT_RS_QUALITY = 20 Unused**: Defined in constants but never referenced in scoring.py. Dead weight in constants.
2. **Sector Tier Boundaries Hard-coded**: TOP_SECTORS_N=8, SECTOR_TIER1_N=5 but no clear relationship documented. If scoring.py changes tier cutoff, constants become stale.
3. **Volume Component Logic Broken for PULLBACK**: Line 291 awards 6/20 for `support_source` present, but STRICT mode requires support (no conditional). **Effectively all PULLBACK setups get same vol score, defeating differentiation.**
4. **Distance Percent Guard Missing**: Line 270 uses `_d if _d is not None else 1.5`. If distance_pct is exactly 0.0 (closest to breakout = best), this works. **But code comment says "distance_pct = 0.0 guard" which is misleading.**
5. **Regime Tier Mismatch**: Line 337 checks `regime == "AGGRESSIVE"` but regime is string like "AGGRESSIVE" from engine0. If regime contains space or case variation, fails silently.

**Gaps:**
- No weighting by trade count (a setup type with 1 signal gets same score as 100 signals)
- No market context (score same in bull/bear; no vol regime adjustment)
- All setups capped at 100, but formula can sum to 120 (raw sum before capping)

---

### 15. FILTERS (filters.py)

**Shared Centralized Entry Gates** (used by scanner, backtest, WFO):

**Public API:**

```python
compute_regime_series(spy_df) â†’ pd.Series[bool]  # bullish/bearish per bar
compute_regime_label_series(spy_df) â†’ pd.Series[str]  # "AGGRESSIVE" | "SELECTIVE" | "DEFENSIVE"
passes_liquidity(df, min_avg_volume, min_dollar_volume) â†’ bool
in_earnings_blackout(signal_date, earnings_dates, blackout_days) â†’ bool
```

**Regime Series (4/7 factors for backtest compatibility):**
- f1: close > EMA20 â†’ 20 pts
- f2: close > SMA50 â†’ 15 pts
- f3: SMA50 > SMA200 â†’ 15 pts
- f4: EMA20 slope (5-bar) â†’ 0-10 pts
- **Total max: 60 pts (vs 100 for live 7-factor)**
- Thresholds scaled: AGGRESSIVE â‰¥ 42/60 (equiv 70/100), SELECTIVE â‰¥ 24/60 (equiv 40/100)

**Liquidity Gate:**
- 50-day median volume â‰¥ LIQUIDITY_MIN_AVG_VOLUME (750K)
- last_close Ã— median_vol â‰¥ LIQUIDITY_MIN_DOLLAR_VOLUME ($25M)
- Uses median (robust to spikes), not SMA

**Earnings Blackout:**
- Checks if signal_date falls within [earnings_dateâˆ’1, earnings_date+7] calendar days
- Returns False (safe) on empty/parse error

**Issues Found:**

1. **Regime Slope Calculation Brittle**: Line 45 computes `slope5 = ema20 - ema20.shift(5)` but doesn't normalize by EMA value. A 0.01 slope on a $100 stock is huge, but on $1 stock is tiny. **Should use pct_change.**
2. **Liquidity Gate Too Strict**: $25M dollar volume is roughly $250K median Ã— $100 close. For small-cap leaders (price < $50), this is impossible.
3. **Earnings Date Format Fragile**: Line 184 uses datetime.strptime(signal_date[:10], "%Y-%m-%d") but if timezone info appended, slicing may fail. Should use fromisoformat().
4. **Regime Series Returns All-False on Short Input**: Line 81-82 returns all-False if len < 200 bars. Backtest with <200 bars becomes DEFENSIVE everywhere. **Should raise or log warning.**

**Gaps:**
- No VIX threshold (f7 from engine0 always omitted in backtest)
- No breadth/H-L ratio (f5, f6 always omitted)
- Backtest regime softer than live (effectively ~60 pts vs live 100 pts)

---

### 16. INDICATORS (indicators.py)

**What It Does:**
Pure technical indicator implementations (no external TA library).

**Implemented Functions:**
- **ema(series, length)**: Exponential Moving Average (Wilder's EWM, adjust=False)
- **sma(series, length)**: Simple Moving Average (rolling mean)
- **atr(high, low, close, length=14)**: Average True Range (Wilder's smoothing)
- **true_range(high, low, close)**: Raw (un-smoothed) True Range
- **cci(high, low, close, length=20, constant=0.015)**: Commodity Channel Index

**Issues Found:**
1. **EMA Edge Case**: Line 12 uses `ewm(span=length, adjust=False, min_periods=length)` but for backtest (day-by-day), min_periods=length means first 20 days of CCI/EMA return NaN. Backtest engines expect this but never explicitly documented.
2. **ATR Warmup**: ATR requires 14 bars min (line 35 min_periods=14). If backtest signal on bar 13, ATR is NaN. Engines that use ATR (stops, trails) will fail with NaN.
3. **CCI Formula**: Line 62-70 matches standard definition but constant=0.015 is not tunable. High-volatility stocks may need constant adjustment.

**Gaps:**
- No RSI, MACD, Bollinger Bands (could be useful for other patterns)
- No volume-weighted calculations (relies on OHLC only)

---

### 17. DATABASE (database.py)

**Schema Summary:**

| Table | Purpose | Key Fields |
|-------|---------|-----------|
| `scan_runs` | Scan metadata | scan_timestamp (unique), tickers_scanned, completed |
| `market_regime` | SPY snapshot per scan | scan_timestamp, spy_close, regime_score, factors_json |
| `scan_setups` | All trading signals | scan_timestamp, ticker, setup_type, entry/stop/tp, metadata (JSON) |
| `sr_zones` | KDE zones per scan | scan_timestamp, ticker, level/upper/lower, zone_type, source |
| `trades` | Manual portfolio entries | ticker, entry_price, stop_loss, target, status (active/closed) |
| `backtest_results` | Historical replay results | run_id, ticker, setup_type, total_trades, win_rate, profit_factor |
| `wfo_results` | Walk-forward optimization | run_id, status, progress_pct, result_json |

**Key Design Decisions:**
- All tables keyed by `scan_timestamp` (immutable, preserves history)
- `metadata` JSON column for extensible fields (don't add new columns)
- `batch_save_setups()` uses `executemany()` for bulk insert performance

**Issues Found:**
1. **Migration Fragility**: Lines 128-135 list SQL migrations, but they're executed as pure SQL without IF NOT EXISTS guards. If a migration runs twice, it fails. Idempotent migrations added as try/except but fragile.
2. **Foreign Keys Not Enforced**: scan_setups has FOREIGN KEY reference to scan_runs but SQLite doesn't enforce by default (PRAGMA foreign_keys = ON not set in code).
3. **Backtest Results JSON Bloat**: Line 106 stores `trades_json` with every trade dict. For 1000-trade backtest, this is multi-MB overhead per row.
4. **No Archival**: Old scan results accumulate forever. No retention policy or cleanup.

**Gaps:**
- No indices on (ticker, scan_timestamp) for queries like "all setups for AAPL across all scans"
- No audit trail (who ran scan, with what params)

---

### 18. BACKTEST ENGINE (backtest_engine.py)

**What It Does:**
Day-by-day historical replay backtester with lookahead-bias prevention.

**Trade Lifecycle:**
- Signal detected at day T (on pre-close data)
- Entry at T+1 open
- Stop/target/trailing managed daily
- Closed at T+N EOD (target/stop hit) or end_date (EOD close)

**Key Features:**
- **Lookahead Bias Prevention**: At step T, only `df.iloc[:T+1]` visible
- **Regime Series**: Computed from 4/7 factors (SPY-only, no breadth/VIX)
- **Liquidity Gate**: 50-day median vol + dollar vol (passes_liquidity())
- **Earnings Blackout**: Optional, skips trades within Â±7 days of earnings
- **Max Open Positions**: Cap at MAX_OPEN_POSITIONS per ticker
- **Trailing Stops**: V5 per-setup ATR multipliers
- **Position Sizing**: Risk-based (1% equity per trade, capped at 20% position)

**V5 Trail Multipliers (Optuna-tuned):**
- VCP: 2.0 (tight for fast profits)
- PULLBACK: 3.0 (moderate trend room)
- RES_BREAKOUT: 4.25 (wide for breakout room)
- BASE: 4.162 (same as fallback)

**BacktestParams (Optuna-tunable):**
```python
rs_threshold: float = 0.066
cci_threshold: float = -54.5
ema_distance: float = 1.651
breakout_weight: float = 1.724
pullback_weight: float = 1.842
# ... 20+ params total
```

**Trade Record Contract:**
```python
{
  ticker, setup_type, signal_date, entry_date, entry_price,
  initial_stop, take_profit, exit_date, exit_price, exit_reason,
  holding_days, rr_achieved, pnl_pct, is_win, regime, rs_score,
  setup_meta (dict)
}
```

**What Backtest Skips vs Live Scanner:**
- **No RS rank gate** (â‰¥70 percentile)
- **No minimum setup score gate** (â‰¥70)
- **No hot-sector injection**
- **Regime uses 4/7 factors** (softer than live 7/7)
- **No earnings cache** (pre-provided or skipped)

**Issues Found:**

1. **WARMUP_BARS = 252 Hardcoded**: Line 73. If backtest window < 252+60 bars, warmup insufficient. No validation.
2. **Zone Recomputation Expensive**: Line 74 says "recompute KDE zones every N trading days" but this is slow for large backtests (N=5 = 50 zone recomputations per year).
3. **ATR Trail Implementation**: Trailing stop = max(original_stop, current_ema20) when in profit. But EMA20 not always in backtest context (uses precomputed from df).
4. **Gap Risk Not Modeled**: If stock gaps down past stop, backtest exits at gap close, not stop price. No slippage/gap buffer.
5. **Regime Score Unused in Trade Record**: regime field populated but never used in scoring. `regime_score = None` (line 171) so all trades go to "UNKNOWN" bucket in compute_regime_performance().

**Gaps:**
- No model for partial fills (large positions may not fill at entry price)
- No transaction costs/commissions
- No portfolio-level metrics (max drawdown, Sharpe, etc.)

---

### 19. WFO ENGINE (wfo_engine.py)

**What It Does:**
Walk-Forward Optimization â€” rolls IS/OOS windows over cached price data, runs BacktestEngine for each window+ticker, aggregates metrics.

**Window Generation:**
```
is_start -------- is_end | oos_start ------ oos_end
      (trained)            (validated)
                  â†‘
              step forward
```

**Performance Design:**
- Price data loaded once from Parquet per run (not per window)
- Each BacktestEngine receives pre-sliced DF bounded to [warmup_bars before window_start : window_end]
- All ticker+period pairs per window run in parallel via ThreadPoolExecutor

**WFOResult Structure:**
```python
{
  run_id, tickers, setup_types,
  is_months, oos_months, step_months, min_trades,
  windows: [
    {
      window_num, is_start, is_end, oos_start, oos_end,
      is_metrics: {trades, win_rate, avg_r, expectancy, profit_factor},
      oos_metrics: {...},
      stability_score: oos_expectancy / is_expectancy,
      per_setup: {setup_type: {is, oos}}
    }
  ]
}
```

**Issues Found:**
1. **Price Cache Dependency**: Requires WFO_CACHE_DIR with pre-downloaded parquet files. If cache missing, run fails with no fallback to yfinance.
2. **Memory Bloat**: All trade records for all windows stored in memory (WFOResult.windows[].is_trades, oos_trades). For 10-year WFO with 100 tickers Ã— 6 setup types, this could be 10K+ trades.
3. **Stability Score Edge Case**: Line 85 computes `oos_expectancy / is_expectancy`. If IS had 0 expectancy (break-even), division by zero. No guard.

**Gaps:**
- No out-of-sample data reuse (windows may overlap if step < window sizes)
- No statistical significance testing (trade counts may be too low for reliable estimates)

---

### 20. ANALYTICS (analytics.py)

**Public API:**

```python
compute_live_diagnostics(trades) â†’ {total_trades, profit_factor, win_rate, avg_R, expectancy, max_drawdown, equity_curve_R}
compute_setup_breakdown(trades) â†’ {setup_type: metrics}
compute_ticker_distribution(trades) â†’ [{ticker, trade_count, total_pnl, pct_contribution}, ...]
compute_regime_performance(trades) â†’ {AGGRESSIVE, SELECTIVE, DEFENSIVE, UNKNOWN: metrics}
```

**Trade Dict Contract (minimum):**
```python
{
  ticker, setup_type, entry_price, stop_loss, close_price, status, regime_score
}
```

**Metrics Computed:**
- **Win Rate**: wins / total
- **Avg R**: mean R-multiple across ALL trades
- **Expectancy**: (wr Ã— avg_win_r) + (lr Ã— avg_loss_r)
- **Profit Factor**: gross_profit / abs(gross_loss)
- **Max Drawdown**: peak-to-trough of cumulative R
- **Equity Curve**: cumulative R progression

**Issues Found:**

1. **Low Sample Warning Fragile**: Line 139 flags `low_sample: True` if trades < 20. But 20 trades is barely statistically significant. **Recommend: 50 minimum.**
2. **Close Price Handling**: Line 14 says "close_price | None" if open. But code expects close_price always present for closed trades. Adapter in main.py maps exit_price â†’ close_price, but frontend may send nulls.
3. **Regime Bucket Assignment**: Line 189 uses trade["regime"] as label. **But backtest trades all have regime="UNKNOWN"** (engine doesn't persist regime per trade). This makes AGGRESSIVE/SELECTIVE/DEFENSIVE always empty for backtest trades.

**Gaps:**
- No confidence intervals (Win Rate Â±x%)
- No sequential analysis (drawdown recovery time)
- No parameter sensitivity analysis

---

### 21. WATCHLIST

**Implementation in main.py:**
- Detects "near-breakout" setups: within 1.5% of resistance (WATCHLIST_PROXIMITY_PCT)
- Returned by Engine 2 (VCP) when DRY conditions met but not quite at breakout

**Endpoint**: `/api/watchlist` â†’ fetches latest setups with setup_type="WATCHLIST"

**Issues Found:**
1. **Pollutes Main Results**: WATCHLIST setups saved alongside regular setups in scan_setups table. Makes filtering harder (need WHERE setup_type != "WATCHLIST" for true signals).
2. **No Expiry**: Watchlist items never expire. If monitored stock pulls back 5%, it stays on watchlist indefinitely.

---

### 22. FRONTEND APP.jsx

**Architecture:**
- Multi-page SPA (pages: scanner, watchlist, portfolio, analytics, diagnostics, favorites)
- 200+ lines of state (regime, setups, filters, prices, analysis)
- Polling scan status every 500ms
- Live price refresh every 60s

**Pages:**
- **SCANNER**: Main grid of setups, can select ticker for chart + analysis
- **WATCHLIST**: Near-breakout setups
- **PORTFOLIO**: Active trade manager (not fully implemented)
- **ANALYTICS**: Backtest diagnostics + performance breakdown
- **DIAGNOSTICS**: Live scan performance + per-setup metrics
- **FAVORITES**: Pinned tickers for quick access

**Issues Found:**
1. **Unnecessary Re-renders**: Line 224 `fetchLivePrices()` dependency array includes entire setup arrays (vcpSetups, pullbackSetups, ...). Every render invalidates interval. **Use useCallback with specific fields.**
2. **Poll Timer Leak**: Line 232 creates interval but ref not cleaned up on component unmount if scan completes. **Memory leak.**
3. **Favorites Storage**: Line 91 JSON.parse(localStorage) could throw on corrupted data. Already wrapped in try/catch but silent fail.

**Gaps:**
- No real-time price alerts (watchlist just visual)
- No trade execution (portfolio is read-only)

---

### 23. FRONTEND COMPONENTS (src/components/)

**Component Overview:**

| Component | Purpose | Issues |
|-----------|---------|--------|
| **SetupTable.jsx** | Reusable grid for any setup type | `accentColor` prop for setup-type styling; no sort/filter built-in |
| **ScannerTable.jsx** | Main results grid | `is_vol_surge` â†’ green row; `hot_sector` â†’ ðŸ”¥ badge; selected â†’ amber border |
| **TradingChart.jsx** | lightweight-charts OHLCV | MA overlays use Adj Close; candles use Close |
| **StockIntelPanel.jsx** | Right sidebar: signals, trade plan, V5 analysis | Shows entry/stop/target math |
| **PortfolioTab.jsx** | Trade manager (HOLD >EMA20, CAUTION <EMA8, EXIT <EMA20) | Not fully functional |
| **DiagnosticsTab.jsx** | Live + V4 backtest diagnostics | Source toggle (live/backtest) |
| **BacktestPanel.jsx** | Standalone backtest runner UI | Triggers async backtest, shows progress |
| **DebugDrawer.jsx** | Dev mode: per-engine pass/fail | Called on right-click ticker |
| **WatchlistPanel.jsx** | Watchlist management | Placeholder for future |
| **FavoritesPage.jsx** | Starred tickers | localStorage-backed |
| **Header.jsx** | Regime banner + scan trigger | Shows breadth_pct, hl_ratio, VIX |
| **Sidebar.jsx** | Left nav (page switching) | Icons for 6 pages |
| **TopBar.jsx** | Status bar + dev mode toggle | Scan status polling |

**Common Issues:**
1. **Null Coalescing Fragile**: Line in ScannerTable.jsx uses `reject_reasons = setup.reject_reasons ?? []` but API returns `reject_reasons: null`. JavaScript `??` only handles undefined, not null. **Many components affected.**
2. **No Error Boundaries**: If API fails, entire page blank. No graceful degradation.
3. **Chart Data Shape Mismatch**: TradingChart expects `[{timestamp, open, high, low, close, volume}, ...]` but API may return `[{Date, Open, High, Low, Close, Volume}]` (pandas naming).

---

### 24. API ENDPOINTS (main.py)

**Complete List:**

**Scan & Market:**
- `POST /api/run-scan` â†’ Trigger scan (force, dry_run, tickers params)
- `GET /api/scan-status` â†’ Poll progress (in_progress, progress_pct, engine_stats, dry_run_setups)
- `GET /api/regime` â†’ Latest regime (is_bullish, regime, regime_score, spy_close, factors)
- `GET /api/setups/{type}` â†’ Get setups (vcp, pullback, base, res-breakout, htf, lce, options-catalyst)
- `GET /api/watchlist` â†’ Near-breakout setups
- `GET /api/sr-zones/{ticker}` â†’ S/R zones from last scan

**Charts & Data:**
- `GET /api/chart/{ticker}` â†’ OHLCV + EMA8/20 + SMA50 + CCI20 (fresh fetch)
- `GET /api/prices` â†’ Live prices (comma-separated tickers, 60s cache)
- `GET /api/market-overview` â†’ Market breadth + macro data
- `GET /api/analyze/{ticker}` â†’ Analysis summary

**Portfolio:**
- `POST /api/trades` â†’ Add trade
- `GET /api/trades` â†’ Active trades
- `DELETE /api/trades/{id}` â†’ Close trade (exit_price, exit_date)
- `GET /api/trades/closed` â†’ Historical closed trades

**Backtest:**
- `POST /api/run-backtest` â†’ Trigger backtest (ticker, dates, setup_types)
- `GET /api/backtest-results/{ticker}` â†’ Results from last backtest

**WFO:**
- `POST /api/wfo/download` â†’ Download price cache (tickers)
- `GET /api/wfo/download-status/{jobId}` â†’ Check download progress
- `POST /api/wfo/run` â†’ Start WFO run (params)
- `GET /api/wfo/status/{runId}` â†’ Check WFO progress
- `GET /api/wfo/results/{runId}` â†’ Fetch results
- `GET /api/wfo/export/{runId}` â†’ CSV export
- `GET /api/wfo/audit/{runId}` â†’ Audit per-setup metrics

**Universe:**
- `POST /api/build-universe` â†’ Rebuild from SEC

**Dev:**
- `GET /api/debug/{ticker}` â†’ Engine health per ticker
- `GET /api/health` â†’ Health check

**Issues Found:**
1. **No Pagination**: `/api/setups/{type}` returns ALL setups for a type. Large scans (500+ signals) cause frontend lag.
2. **No Rate Limiting**: No throttle on repeated requests. DOS risk if frontend polls too fast.
3. **Chart Endpoint Always Fresh Fetch**: `/api/chart/{ticker}` doesn't use cache, always downloads latest data. Slow for multi-ticker views.
4. **Error Responses Inconsistent**: Some endpoints return `{error: "msg"}`, others `{message: "msg"}`, others HTTP status only.

---

### 25. ZONE UTILS (zone_utils.py)

**Public API:**

```python
nearest_resistance_target(entry, zones, risk, tp_multiple=None)
  â†’ (take_profit, rr)
```

**Logic:**
1. Filter KDE RESISTANCE zones where zone["lower"] > entry
2. Use nearest (lowest) as take_profit
3. If RR < 1.0, fall back to tp_multiple (or TARGET_RR)

**Issues Found:**
1. **Nearest â‰  Best**: Closest resistance is not always best target (could be micro-resistance, not structural). **Should look for tallest/widest zone, not nearest.**
2. **No Zone Type Check**: Accepts both "RESISTANCE" and arbitrary types. If zone["type"] missing, silently ignores.

---

### 26. VALIDATION (validation.py)

**Public API:**

```python
validate_ticker_dataframe(df, ticker, min_rows) â†’ bool
validate_rs_dataframe(df, ticker, min_rows) â†’ bool
sanitize_numeric_value(value, field_name, allow_negative, max_value) â†’ float
validate_setup_result(setup, ticker) â†’ bool
is_price_vital(df, lookback, min_range_pct) â†’ bool
validate_regime_dict(regime) â†’ bool
validate_sr_zones(zones, ticker) â†’ bool
```

**Issues Found:**
1. **is_price_vital() Weak**: Line 201 checks (high - low) / high > min_range_pct. For $100 stock with $2 range = 2%, passes at VITALITY_MIN_RANGE_PCT=2%. But $2 range could be 1 bar microstructure noise, not vital price action.
2. **Numeric Sanitization Logging**: Line 106 logs warning for negative values but doesn't block downstream usage. Caller may not check return value.

---

### 27. UNIVERSE BUILDER (universe_builder.py)

**What It Does:**
SEC fetch + pattern filter + save/load for tradeable universe.

**SEC Fetch:**
- Calls SEC EDGAR API to fetch company_tickers_exchange.json
- Filters NYSE/Nasdaq only
- Deduplicates by ticker

**Pattern Filtering:**
- Removes ETFs (hard-coded frozenset)
- Removes warrants (ends with W or WS)
- Removes preferred shares (-P suffix)
- Removes rights/units (-R, -RT, -U)
- Removes long tickers (base > 5 chars)
- Normalizes dots to dashes (BRK.B â†’ BRK-B)

**Persistence:**
- Saves to active_universe.json with metadata (generated_at timestamp)
- Loads in main.py with age-check fallback to SCAN_UNIVERSE

**Issues Found:**
1. **ETF Freeze List Stale**: KNOWN_ETFS missing many 2024+ ETFs (SCHA, SCHB, XUS, etc.)
2. **SEC API Rate Limits**: No retry logic if SEC returns 429. Entire build fails.
3. **Ticker Normalization Lossy**: BRK.B â†’ BRK-B, but yfinance expects "BRK-B" or "BRK.B" inconsistently.

---

## SUMMARY OF FINDINGS

### Critical Issues (Should Fix ASAP)

1. **Engine 0 Slope Factor Bug** (Line 130): EMA20 slope calculation doesn't scale correctly; +0.5% slopes get 0 pts instead of 10 pts.
2. **Engine 3 CCI_RLX_FLOOR Too Loose** (-1.95): Almost any bar qualifies in relaxed mode. Should be -15 to -25.
3. **Backtest Regime Score Unused**: regime_score=None for all backtest trades; analytics bucket them as "UNKNOWN" instead of AGGRESSIVE/SELECTIVE/DEFENSIVE.
4. **RS Rank Gate Too Strict** (70 percentile): Filters out many leaders trading 50-70 RS. Discovery layer (10% of universe) only partial mitigation.
5. **V5 Trail Multipliers Inconsistent**: BASE uses 4.162 (fallback) but RES_BREAKOUT uses 4.25; no clear rationale or tuning difference documented.

### High Priority (Next Sprint)

6. **Prefetch Caching Issue**: Trendline caches key by (ticker, date_str, lookback) but date from .index[-1].date() varies if refreshed at different time.
7. **Hot Sector Threshold Arbitrary**: Triggers on â‰¥3 setups. No scaling by regime or universe size.
8. **Database Migrations Fragile**: Multiple migrations as try/except; IF NOT EXISTS guard missing in SQL.
9. **Frontend Polling Memory Leak**: Interval timer not cleaned up if scan completes mid-poll.
10. **Setup Score vs R:R Asymmetry**: Scoring includes 20 pts for R:R (formula: `(rr - 1.0) / 3.0 * 20`), but actual RR used for stop calc is fixed (2.0 via TARGET_RR). Disconnect.

### Medium Priority (Refactoring)

11. **Constants Duplication**: RES_BREAKOUT_VOL_MULT (2.0) vs BacktestParams.brk_vol_mult (3.0161) â€” which is authoritative?
12. **Scoring Weight Total Exceeds 100**: Sum = 30+20+20+15+10+5+20 = 120. Raw score capped at 100, but weighting is unclear.
13. **Engine Gating Tracking**: DEFENSIVE regime skips E2 & E3, but engine_stats doesn't distinguish "0 found" vs "disabled by regime".
14. **Watchlist Pollution**: WATCHLIST setups saved in scan_setups table, require WHERE setup_type != "WATCHLIST" filter.
15. **No Pagination on Setups**: `/api/setups/{type}` returns all results; can cause frontend lag with 500+ signals.

### Low Priority (Nice-to-Haves)

16. Zone width (0.2 Ã— ATR) hardcoded; could be tunable parameter
17. Peak detection prominence threshold (5th percentile) never tuned
18. Backtest gap risk not modeled; no slippage
19. No transaction costs/commissions in backtest
20. Regime Series returns all-False if < 200 bars, should warn instead

### Dead Code / Unused Definitions

- SCORE_WEIGHT_RS_QUALITY = 20 (never applied in scoring.py)
- LCE_VOL_CONTRACTION_RATIO = 0.80 (never used in engine9_low_cheat.py)
- Several constants marked "Optuna v4 best" with no version control

### Code Quality Gaps

- No type hints in main Python files
- Error handling inconsistent (silent failures vs exceptions)
- Logging sparse (many silent failures)
- Comments outdated (e.g., "3% proximity" guard in Engine 3 not clearly explained)

---

## OVERALL ASSESSMENT

The codebase is **production-ready but brittle in edge cases**. The architecture is sound:
- Clean separation of engines, scoring, and filtering
- Database persistence layer isolated from business logic
- React frontend reasonably modular

**Key strengths:**
- Optuna tuning of parameters across 20+ backtest windows
- Per-setup trailing stop multipliers (V5) well-calibrated
- Scoring system balances RS, R:R, regime, sector, volume holistically
- Discovery layer (RS 60-70) partially mitigates strict RS gate

**Key weaknesses:**
- Engine 0 slope bug affects regime classification accuracy
- Too many hardcoded thresholds with loose coupling
- Backtest regime not persisted per trade, losing regime analysis value
- Database schema could use better indices and archival policy

**Recommendation for next audit (6 months):**
- After 100+ live trades, measure actual win rate vs backtest expectations (should be Â±2-5%)
- Re-tune trailing stop multipliers (V5) with live data
- Validate discovery layer impact (should increase lead count by 10-15%)
- Profile frontend performance under 1000+ signal load