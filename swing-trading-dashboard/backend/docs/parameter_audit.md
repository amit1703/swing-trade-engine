# PARAMETER AUDIT — FULL SYSTEM
Generated: 2026-03-25

---

## 1. PARAMETER TABLE

### Pass 1 Filtering

| Name | Location | Value | Optimized? | Issue |
|------|----------|-------|------------|-------|
| `PASS1_MIN_PRICE` | constants.py:380 | 12.0 | N | Consistent with UNIVERSE_MIN_PRICE=12.0 |
| `PASS1_MIN_AVG_VOLUME` | constants.py:381 | 1,000,000 | N | 33% higher than LIQUIDITY_MIN_AVG_VOLUME (750K) — creates hidden redundancy |
| `PASS1_MIN_DOLLAR_VOLUME` | constants.py:382 | 25,000,000 | N | Same as LIQUIDITY_MIN_DOLLAR_VOLUME — Pass 1 and Pass 2 dollar-vol gates are identical |
| `PASS1_MIN_RS_RANK` | constants.py:383 | 0 (disabled) | N | Disabled; note prompt name "PASS1_MIN_RS_RANK_COLD" doesn't match actual name |
| `PASS1_MIN_RS_RANK_WARM` | constants.py:384 | 0 (disabled) | N | Disabled; no practical difference from cold |
| `PASS1_MIN_52W_HIGH_PCT` | constants.py:385 | 0.65 | N | Applied only to above-SMA50 tickers |
| `PASS1_BELOW_SMA50_MIN_52W_PCT` | constants.py:389 | 0.75 | N | Stricter than above-SMA50 floor (0.75 > 0.65) — counterintuitive |
| `PASS1_BELOW_SMA50_VOL_RATIO` | constants.py:390 | 1.20 | N | Fixed fallback only |
| `PASS1_BELOW_SMA50_MIN_RS` | constants.py:391 | 0 (disabled) | N | Effectively no RS check for below-SMA50 |
| `PASS1_BELOW_SMA50_VOL_PERCENTILE` | constants.py:393 | 70 | N | Adaptive threshold — 70th percentile |
| `PASS1_BELOW_SMA50_VOL_FLOOR` | constants.py:394 | 1.00 | N | |
| `PASS1_BELOW_SMA50_VOL_CEIL` | constants.py:395 | 1.50 | N | |
| `PASS1_BELOW_SMA50_PROX_PERCENTILE` | constants.py:396 | 70 | N | |
| `PASS1_BELOW_SMA50_PROX_FLOOR` | constants.py:397 | 0.70 | N | |
| `PASS1_BELOW_SMA50_PROX_CEIL` | constants.py:398 | 0.85 | N | |
| `PASS1_BELOW_SMA50_MIN_SAMPLE` | constants.py:399 | 20 | N | |
| `PASS1_MAX_SURVIVORS` | constants.py:400 | 400 | N | |
| Adaptive tighten RS steps | main.py:1165 | RS≥50, ≥50, ≥55 | N | **Hardcoded in logic, not in constants.py** — silent magic numbers |
| Adaptive tighten DV multipliers | main.py:1165 | 1.0, 1.6, 1.6 | N | **Hardcoded in logic, not in constants.py** |

### Pass 2 Filters

| Name | Location | Value | Optimized? | Issue |
|------|----------|-------|------------|-------|
| `RS_RANK_MIN_PERCENTILE` | constants.py:111 | 0 (disabled) | N | Gate exists in code; AGGRESSIVE and SELECTIVE versions also = 0 |
| `RS_RANK_MIN_PERCENTILE_AGGRESSIVE` | constants.py:109 | 0 | N | Redundant with RS_RANK_MIN_PERCENTILE |
| `RS_RANK_MIN_PERCENTILE_SELECTIVE` | constants.py:110 | 0 | N | Redundant |
| `MIN_CANDLES_FOR_ANALYSIS` | constants.py:46 | 60 | N | |
| `MIN_CANDLES_FOR_RS` | constants.py:47 | 252 | N | Requires full 1y of data |
| `VITALITY_LOOKBACK_DAYS` | constants.py:214 | 10 | N | |
| `VITALITY_MIN_RANGE_PCT` | constants.py:215 | 0.02 (2%) | N | |
| `MIN_ATR_PCT` | constants.py:221 | 2.5 | N | Used in universe_builder but NOT in per-ticker Pass 2 vitality check — gap |
| `LIQUIDITY_MIN_AVG_VOLUME` | constants.py:227 | 750,000 | N | Lower than PASS1_MIN_AVG_VOLUME (1M) — Pass 2 liquidity gate is LOOSER than Pass 1 |
| `LIQUIDITY_MIN_DOLLAR_VOLUME` | constants.py:228 | 25,000,000 | N | Same as Pass 1 — dollar-vol check is fully redundant |
| `EARNINGS_BLACKOUT_DAYS` | constants.py:234 | 7 | N | Forward only; also blocks -1 day (hardcoded in filters.py:200) |

### Scoring

| Name | Location | Value | Optimized? | Issue |
|------|----------|-------|------------|-------|
| `SCORE_WEIGHT_RS_RANK` | constants.py:126 | 25 | N | |
| `SCORE_WEIGHT_RR` | constants.py:127 | 17 | N | |
| `SCORE_WEIGHT_VOL` | constants.py:128 | 16 | N | |
| `SCORE_WEIGHT_REGIME` | constants.py:129 | 15 | N | |
| `SCORE_WEIGHT_TREND_DUR` | constants.py:130 | 10 | N | PULLBACK only — 0 for all other types |
| `SCORE_WEIGHT_COILING` | constants.py:131 | 7 | N | WATCHLIST only |
| `SCORE_WEIGHT_SECTOR` | constants.py:132 | 5 | N | |
| `SCORE_WEIGHT_SUPPORT_TIER` | constants.py:133 | 5 | N | PULLBACK only |
| `SCORE_WEIGHT_QUALITY` | constants.py:134 | 5 | N | |
| `SCORE_WEIGHT_RS_QUALITY` | constants.py:135 | 20 | N | **Additive bonus — not capped by weight sum**; can push raw score above 100 |
| Sum of primary weights | scoring.py | 25+17+16+15+10+7+5+5+5 = **105** | N | **Primary weights sum to 105, not 100** — comment in constants.py says "sum = 100" but it's wrong |
| `MIN_SETUP_SCORE` | constants.py:120 | 70 | N | |
| `MIN_SETUP_SCORE_DEFENSIVE` | constants.py:121 | 45 | N | **Never wired into score_and_filter_setups() — dead constant** |
| `SCORE_SELECTIVE_REGIME_FACTOR` | constants.py:136 | 0.53 | N | |
| `RS_TIER1_THRESHOLD` | constants.py:289 | 85 | N | |
| `RS_TIER1_MULTIPLIER` | constants.py:290 | 1.15 | N | |
| `SECTOR_TIER1_N` | constants.py:293 | 5 | N | TOP_SECTORS_N=8 but only top 5 get full points |
| `SECTOR_TIER2_FACTOR` | constants.py:294 | 0.8 | N | |
| `SECTOR_OUT_OF_TOP_FACTOR` | constants.py:295 | 0.4 | N | |
| `SELECTIVE_SETUP_WEIGHTS["PULLBACK"]` | constants.py:335 | 0.5 | N | Based on n=351 backtest trades |
| `SELECTIVE_SETUP_WEIGHTS["RES_BREAKOUT"]` | constants.py:336 | 1.0 | N | Based on n=191 |
| `SELECTIVE_HARD_FILTER` | constants.py:342 | False | N | |
| Extension penalty thresholds | scoring.py:586-589 | 1.5, 0.75 ATR | N | **Hardcoded in scoring.py, not in constants.py** |
| Extension penalty pts | scoring.py:587-589 | 4.0, 2.0 | N | **Hardcoded in scoring.py** |
| Vol component breakpoints | scoring.py:378-382 | 2.0, 1.5, 1.2 | N | **Hardcoded in scoring.py** |
| Vol component multipliers | scoring.py:379-382 | 1.0, 0.6, 0.3 | N | **Hardcoded in scoring.py** |
| PULLBACK vol baseline | scoring.py:388 | 0.3 of max_pts | N | **Hardcoded** |
| WATCHLIST proximity cap | scoring.py:369 | 1.5% | N | **Hardcoded** — should reference WATCHLIST_PROXIMITY_PCT |
| RS quality thresholds | scoring.py:432-450 | 0.0, 0.05, 0.10, 0.05 | N | **All hardcoded in scoring.py** |
| RS quality point values | scoring.py:433-451 | 6, 8, 4, 4, 6, 4, 4 | N | **All hardcoded in scoring.py** |
| WATCHLIST coiling gate in SELECTIVE | scoring.py:667 | coiling_score < 2 | N | **Hardcoded in scoring.py** |
| Trend duration breakpoints | scoring.py:468-474 | 10, 15, 20, 30 bars | N | **Hardcoded in scoring.py** |

### Engine 0 — Market Regime

| Name | Location | Value | Optimized? | Issue |
|------|----------|-------|------------|-------|
| `REGIME_WEIGHT_EMA20` | constants.py:169 | 20 | N | |
| `REGIME_WEIGHT_SMA50` | constants.py:170 | 15 | N | |
| `REGIME_WEIGHT_MA_STACK` | constants.py:171 | 15 | N | |
| `REGIME_WEIGHT_SLOPE` | constants.py:172 | 10 | N | |
| `REGIME_WEIGHT_BREADTH` | constants.py:173 | 20 | N | |
| `REGIME_WEIGHT_HL` | constants.py:174 | 10 | N | |
| `REGIME_WEIGHT_VIX` | constants.py:175 | 10 | N | |
| `REGIME_AGGRESSIVE_THRESHOLD` | constants.py:177 | 70 | N | |
| `REGIME_SELECTIVE_THRESHOLD` | constants.py:178 | 59 | **Y** | Optuna v4 trial #951; was 54 |
| Slope scale (live engine0.py) | engine0.py:130 | ±0.5% maps to 0–10 pts | N | **MISMATCH vs filters.py** |
| Slope scale (backtest filters.py) | filters.py:56 | ±1.0% maps to 0–10 pts | N | **Different formula than engine0** — same market, different score |
| VIX data period | engine0.py:143 | "3mo" | N | |
| VIX min bars | engine0.py:155 | 20 | N | |
| Breadth/HL neutral default | engine0.py:47 | 0.5 | N | |

### Engine 2 — VCP Breakout

| Name | Location | Value | Optimized? | Issue |
|------|----------|-------|------------|-------|
| `VCP_ATR_CONTRACTION_THRESHOLD` | constants.py:103 | 0.6 | N | |
| `VCP_TIGHT_RANGE_5D_PCT` | constants.py:23 | 0.03594 | **Y** | Optuna v4 trial #951 |
| `VCP_MIN_CONTRACTIONS_STRICT` | constants.py:258 | 3 | N | |
| `VCP_MIN_CONTRACTIONS_RELAXED` | constants.py:259 | 2 | N | |
| `ATR_STOP_MULTIPLIER` | constants.py:75 | 1.278 | **Y** | Optuna v4 trial #951 — shared with Engine 3 |
| `DRY_RESISTANCE_PROXIMITY_PCT` | constants.py:20 | 0.05 | N | 5% proximity for Path A |
| `KDE_BREAKOUT_UPPER_PCT` | constants.py:18 | 0.025 | N | 2.5% above resistance for BRK |
| `KDE_BREAKOUT_LOWER_PCT` | constants.py:19 | 0.001 | N | 0.1% below for near-breakout |
| `TRENDLINE_VOL_MULTIPLIER` | constants.py:56 | 1.2 | N | 120% of SMA for TDL breakout |
| BRK volume threshold (Path B) | engine2.py | 1.5× SMA50 | N | **Hardcoded in engine2** — not from constants |
| RS filter in BRK | engine2.py | rs_vs_spy > -0.05 | N | **Hardcoded in engine2** |
| Parabola lookback | engine2.py | 15 bars | N | **Hardcoded** |
| Volume dry-up: last N days | engine2.py | 3 bars, 50% of avg | N | **Hardcoded** |
| TDL relevance cap | engine2.py | 120% of close | N | **Hardcoded** |
| No-slice tolerance | engine2.py:84 | 1% | N | **Hardcoded** |
| Wick tolerance | engine2.py:117 | 1% | N | **Hardcoded** |
| Descending TDL lookback | engine2.py | 120 days | N | **Hardcoded** |
| `VOL_SURGE_MULTIPLIER` | constants.py:54 | 1.1078 | **Y** | Optuna v4 trial #951 |
| `KDE_VOL_MULTIPLIER` | constants.py:55 | 1.15 | N | |
| `TARGET_RR` | constants.py:79 | 4.346 | **Y** | Optuna trial #433 |
| `ENTRY_PRICE_MULTIPLIER` | constants.py:77 | 1.001 | N | |

### Engine 3 — Tactical Pullback

| Name | Location | Value | Optimized? | Issue |
|------|----------|-------|------------|-------|
| `CCI_STRICT_FLOOR` | constants.py:67 | -39.10 | **Y** | Optuna v4 trial #951; was -50 |
| `CCI_RLX_FLOOR` | constants.py:68 | -20.0 | N | Restored from overfit value -1.95 |
| `PB_ATR_STOP_MULTIPLIER` | constants.py:76 | 0.5 | N | Separate from shared ATR_STOP_MULTIPLIER=1.278 |
| `PB_MIN_TREND_BARS` | constants.py:69 | 10 | N | Hard floor only |
| `TRENDLINE_TOUCH_TOLERANCE_PCT` | constants.py:22 | 1.5% | N | |
| `RS_REJECT_THRESHOLD` | engine3.py:37 | -0.01219 | **Y** | Module-level constant — duplicated in constants.BACKTEST_RS_THRESHOLD_DEFAULT |
| `BACKTEST_RS_THRESHOLD_DEFAULT` | constants.py:311 | -0.01219 | **Y** | Duplicate of engine3.py:37 value |
| ZONE_TOLERANCE | engine3.py:109 | 0.025 (2.5%) | N | **Hardcoded in engine3** |
| Pivot low lookback | engine3.py:126 | 60 bars | N | **Hardcoded** |
| Pivot bounce bars | engine3.py:136 | 3 of next 5 | N | **Hardcoded** |
| Proximity for pivot match | engine3.py:143 | max(0.03, 1.2×ATR/price) | N | **Hardcoded** — creates wider tolerance for high-ATR stocks |
| Below-SMA50 relaxation | engine3.py | ×0.97 | N | **Hardcoded** |
| EMA distance relaxed | engine3.py | 4% of EMA | N | **Hardcoded** |
| EMA50 support tier requirement | engine3.py:100-101 | AGGRESSIVE + RS≥85 | N | **Hardcoded** |
| EMA20 support tier requirement | engine3.py:101 | AGGRESSIVE + RS≥90 + trend≥15 | N | **Hardcoded** |
| `SUPPORT_MAX_EXTENSION_ATR` | constants.py:148 | 2.5 | N | |
| `SUPPORT_TIER_SCORES` | constants.py:139-145 | KDE=5,CONS=4,SMA200=3,EMA50=3,EMA20=2 | N | |
| `BacktestParams.cci_threshold` | backtest_engine.py:130 | -54.5 | **Y** | Optuna v5 #433 — **different from CCI_STRICT_FLOOR=-39.10** |
| `BacktestParams.ema_distance` | backtest_engine.py:131 | 1.651 | **Y** | Optuna v5 |
| `BacktestParams.score_threshold` | backtest_engine.py:132 | 2.50 | N | Frozen — not in v5 search space |
| `BacktestParams.pullback_weight` | backtest_engine.py:136 | 1.842 | **Y** | |
| `BacktestParams.cooldown_days` | backtest_engine.py:139 | 4 | **Y** | |
| `BacktestParams.rs_threshold` | backtest_engine.py:127 | 0.066 | **Y** | **Entirely different from live RS_REJECT_THRESHOLD=-0.01219** |

### Engine 5 — Base Patterns

| Name | Location | Value | Optimized? | Issue |
|------|----------|-------|------------|-------|
| Cup depth range | engine5.py | 12–35% | N | **Hardcoded** |
| Right rim proximity | engine5.py | 15% of left peak | N | **Hardcoded** |
| Handle duration | engine5.py | 5–25 days | N | **Hardcoded** |
| Handle depth | engine5.py | 3–15% | N | **Hardcoded** |
| Flat base days | engine5.py | ≥25 | N | **Hardcoded** |
| Flat base depth | engine5.py | ≤12% | N | **Hardcoded** |
| Flat base close position | engine5.py | upper 75% | N | **Hardcoded** |
| Flat base vol factor | engine5.py | ≤90% of 50d avg | N | **Hardcoded** |
| Base quality minimum (live) | engine5.py | 25 | N | **Hardcoded in engine5** |
| `BacktestParams.base_quality_min` | backtest_engine.py:159 | 19 | **Y** | **Different from live engine's 25** |
| `BASE_BRK_MIN_VOL_RATIO` | constants.py:265 | 1.5 | N | |
| `BacktestParams.base_vol_ratio` | backtest_engine.py:158 | 1.425 | **Y** | Different from BASE_BRK_MIN_VOL_RATIO=1.5 |
| `BacktestParams.base_stop_atr` | backtest_engine.py:160 | 0.2 | **Y** | Very tight stop |
| `BacktestParams.base_weight` | backtest_engine.py:156 | 3.895 | **Y** | |
| `BacktestParams.base_trail_mult` | backtest_engine.py:157 | 6.995 | **Y** | Much wider than global TRAIL_ATR_MULT=4.25 |

### Engine 6 — Resistance Breakout

| Name | Location | Value | Optimized? | Issue |
|------|----------|-------|------------|-------|
| `RES_DECISIVE_MIN_PCT` | constants.py:269 | 0.02 | N | 2% — diagnostic confirmed |
| `RES_DECISIVE_ATR_FACTOR` | constants.py:270 | 0.5400 | **Y** | Optuna v4 trial #951 |
| `RES_STOP_ATR_FACTOR` | constants.py:271 | 0.8 | N | Live scanner default |
| `RES_BREAKOUT_VOL_MULT` | constants.py:272 | 2.0 | N | Live scanner default |
| `RES_MAX_GAP_PCT` | constants.py:273 | 0.036 | N | |
| `RES_LAUNCHPAD_BARS` | constants.py:268 | 5 | N | |
| `RES_SELECTIVE_REGIME_FACTOR` | constants.py:274 | 0.80 | N | **Declared but never imported/used anywhere — dead constant** |
| `BacktestParams.brk_vol_mult` | backtest_engine.py:142 | 3.0161 | **Y** | **50% higher than live RES_BREAKOUT_VOL_MULT=2.0** |
| `BacktestParams.brk_stop_atr` | backtest_engine.py:143 | 1.6675 | **Y** | **2× wider than live RES_STOP_ATR_FACTOR=0.8** |
| `BacktestParams.brk_gap_pct` | backtest_engine.py:145 | 0.036 | N | Matches RES_MAX_GAP_PCT |
| `BacktestParams.brk_trail_mult` | backtest_engine.py:146 | 6.9060 | **Y** | **Far above global TRAIL_ATR_MULT=4.25** |
| `BacktestParams.brk_donchian_n` | backtest_engine.py:150 | 87 | **Y** | Different from live _DONCHIAN_N_DEFAULT=63 |
| `BacktestParams.brk_pivot_strength` | backtest_engine.py:151 | 2 | **Y** | Same as live default |
| `BacktestParams.brk_atr_expansion` | backtest_engine.py:152 | 1.474 | **Y** | **Live _ATR_EXP_DEFAULT=0.0 (disabled)** |
| `BacktestParams.brk_min_consolidation` | backtest_engine.py:153 | 10 | **Y** | Different from live _MIN_CONSOL_DEFAULT=3 |
| `_MAX_EXTEND_PCT` | engine6.py:59 | 0.05 | N | **Hardcoded in engine6** |
| `_CONSOL_TOLERANCE` | engine6.py:60 | 0.08 | N | **Hardcoded in engine6** |
| `_DEDUP_THRESHOLD` | engine6.py:61 | 0.005 | N | **Hardcoded in engine6** |
| `_DONCHIAN_N_DEFAULT` | engine6.py:64 | 63 | N | Live scanner default |
| `_PIVOT_HISTORY_BARS` | engine6.py:62 | 252 | N | **Declared but never used — dead constant** |
| NEAR_PCT (watchlist) | engine6.py:332 | 0.05 | N | **Hardcoded** — 5% proximity |
| Live gap fallback | engine6.py:87 | 0.042 | N | **Hardcoded fallback when params=None** — differs from RES_MAX_GAP_PCT=0.036 |

### Engine 7 — Options Catalyst

| Name | Location | Value | Optimized? | Issue |
|------|----------|-------|------------|-------|
| `OPTIONS_MIN_ADV` | constants.py:184 | 500,000 | N | |
| `OPTIONS_MIN_PRICE` | constants.py:185 | 10.0 | N | |
| `OPTIONS_DTE_MIN` | constants.py:186 | 7 | N | |
| `OPTIONS_DTE_MAX` | constants.py:187 | 45 | N | |
| `OPTIONS_OTM_MAX_PCT` | constants.py:188 | 0.10 | N | |
| `OPTIONS_MIN_SCORE` | constants.py:189 | 45 | N | |
| `OPTIONS_VOL_OI_TARGET` | constants.py:190 | 1.0 | N | |
| `OPTIONS_CALL_VOL_TARGET` | constants.py:191 | 2000 | N | |
| `OPTIONS_SKEW_NEUTRAL` | constants.py:192 | 0.5 | N | |
| `OPTIONS_SKEW_MAX` | constants.py:193 | 0.9 | N | |
| `OPTIONS_IV_SLOPE_TARGET` | constants.py:194 | 0.30 | N | |

### Engine 8 — High Tight Flag

| Name | Location | Value | Optimized? | Issue |
|------|----------|-------|------------|-------|
| `HTF_LOOKBACK_DAYS` | constants.py:26 | 40 | N | |
| `HTF_MIN_RUNUP_PCT` | constants.py:27 | 0.80 | N | |
| `HTF_MAX_FLAG_DEPTH_PCT` | constants.py:28 | 0.25 | N | |
| `HTF_MIN_FLAG_BARS` | constants.py:29 | 5 | N | |
| `HTF_MAX_FLAG_BARS` | constants.py:30 | 20 | N | |
| `HTF_MAX_EXTEND_PCT` | constants.py:31 | 0.05 | N | |
| `HTF_MAX_RISK_PCT` | constants.py:32 | 0.35 | N | |

### Engine 9 — Low Cheat Entry

| Name | Location | Value | Optimized? | Issue |
|------|----------|-------|------------|-------|
| `LCE_MAX_DISTANCE_PCT` | constants.py:35 | 0.03 | N | |
| `LCE_VOL_CONTRACTION_RATIO` | constants.py:36 | 0.80 | N | |
| `LCE_MAX_RISK_PCT` | constants.py:37 | 0.15 | N | |
| `LCE_TIGHT_RANGE_CONTRACTION` | constants.py:38 | 0.70 | N | |
| `LCE_BREAKOUT_VOL_RATIO` | constants.py:262 | 1.0 | N | |

### Risk Management

| Name | Location | Value | Optimized? | Issue |
|------|----------|-------|------------|-------|
| `MIN_RISK_REWARD_RATIO` | constants.py:78 | 1.0 | N | Very loose — 1:1 minimum |
| `TARGET_RR` | constants.py:79 | 4.346 | **Y** | Optuna trial #433 |
| `ATR_STOP_MULTIPLIER` | constants.py:75 | 1.278 | **Y** | Shared Engine 2+3 (Engine 3 also has PB_ATR_STOP_MULTIPLIER=0.5) |
| `TRAIL_ATR_MULT` | constants.py:80 | 4.25 | **Y (frozen)** | |
| `VCP_TRAIL_ATR_MULT` | constants.py:89 | 4.25 | **Y (frozen)** | All 4 per-setup values frozen to same 4.25 |
| `PULLBACK_TRAIL_ATR_MULT` | constants.py:90 | 4.25 | **Y (frozen)** | Was 3.0 — major change, pending V5 300-trial optimization |
| `RES_BREAKOUT_TRAIL_ATR_MULT` | constants.py:91 | 4.25 | **Y (frozen)** | |
| `BASE_TRAIL_ATR_MULT` | constants.py:92 | 4.25 | **Y (frozen)** | |
| `RISK_PER_TRADE_PCT` | constants.py:95 | 1.25 | **Y (frozen)** | |
| `MAX_POSITION_SIZE_PCT` | constants.py:96 | 25.0 | **Y (frozen)** | |
| `MAX_OPEN_POSITIONS` | constants.py:97 | 5 | N | |
| `TRAIL_MODE` | constants.py:359 | "ema20" | N | |
| `ATR_ENTRY_EARLY_THRESHOLD` | constants.py:353 | 0.13 | **Y (frozen)** | |
| `ATR_ENTRY_EXTENDED_THRESHOLD` | constants.py:354 | 0.40 | **Y (frozen)** | |
| Engine6 risk gate | engine6.py:258 | risk > entry × 0.15 | N | **Hardcoded** — same value as LCE_MAX_RISK_PCT but not referenced |

### Cache / Timing

| Name | Location | Value | Optimized? | Issue |
|------|----------|-------|------------|-------|
| `RS_RANK_CACHE_TTL` | constants.py:372 | 86400 (24h) | N | |
| `RS_RANK_CACHE_REFRESH_THRESHOLD` | constants.py:374 | 72000 (20h) | N | |
| `RS_RANK_CACHE_MIN_TICKERS` | constants.py:375 | 200 | N | |
| `PRICE_CACHE_FRESH_DAYS` | constants.py:365 | 2 | N | |
| `PRICE_CACHE_MAX_STALE_DAYS` | constants.py:366 | 5 | N | |
| `CACHE_TTL_SUCCESS` | constants.py:159 | 14400 (4h) | N | |
| `CACHE_TTL_FAILURE` | constants.py:160 | 900 (15min) | N | |
| `ZONE_RECOMPUTE_N` | backtest_engine.py:108 | 5 | N | **Hardcoded in backtest_engine, not constants** |
| `WARMUP_BARS` | backtest_engine.py:107 | 252 | N | **Hardcoded in backtest_engine, not constants** |

---

## 2. CRITICAL ISSUES

### CRIT-1: Score weights sum to 105, not 100
**File:** constants.py:126–135
**Detail:** `25+17+16+15+10+7+5+5+5 = 105`. The comment says "sum of primary weights = 100". Additionally, `SCORE_WEIGHT_RS_QUALITY=20` is additive on top, meaning a perfect setup can raw-score `105 + 20 = 125` before the `min(100,...)` clamp. The score range [70, 100] is not linear — the effective discriminating range is compressed. Any regime/sector analysis of "score=70" means something different than intended.

---

### CRIT-2: Regime slope formula differs between engine0.py and filters.py
**Files:** engine0.py:130 vs filters.py:56
**Detail:** Live scanner uses `±0.005` (0.5%) midpoint to map slope to 0–10 pts. Backtest uses `±0.01` (1.0%) midpoint. At flat slope (0% over 5 bars): both give 5 pts — same neutral. But at +0.3% slope: live gives 8 pts, backtest gives 6.5 pts. The regime boundaries (SELECTIVE=59) were Optuna-tuned — it is unknown which formula was in use during tuning. Backtest regime scoring is softer: the same market conditions score lower in backtest than live.

---

### CRIT-3: BacktestParams RES_BREAKOUT parameters are substantially different from live production
**Files:** backtest_engine.py vs engine6.py and constants.py

| Parameter | Backtest (Optuna) | Live Production | Delta |
|-----------|------------------|-----------------|-------|
| `brk_vol_mult` | 3.016 | 2.0 | +50% |
| `brk_stop_atr` | 1.668 | 0.8 | +108% |
| `brk_donchian_n` | 87 | 63 | +38% |
| `brk_atr_expansion` | 1.474 | 0.0 (disabled) | filter off in live |
| `brk_min_consolidation` | 10 | 3 | +233% |
| `brk_trail_mult` | 6.906 | 4.25 | +62% |

Backtest performance is not representative of what the live scanner produces for RES_BREAKOUT.

---

### CRIT-4: `MIN_SETUP_SCORE_DEFENSIVE=45` is never used
**File:** constants.py:121, scoring.py
**Detail:** `score_and_filter_setups()` always passes `min_score=MIN_SETUP_SCORE` (70), regardless of regime. In DEFENSIVE, the regime scoring component is 0 pts, so all setups lose 15 pts. The constant `MIN_SETUP_SCORE_DEFENSIVE=45` is declared but has no code path that reads it. It is a dead constant that creates a false impression of DEFENSIVE-mode behavior.

---

### CRIT-5: RS_REJECT_THRESHOLD duplicated and diverged from BacktestParams
**Files:** engine3.py:37, constants.py:311, backtest_engine.py:127
**Detail:** Three places hold related values:
- Live engine3 module constant: `RS_REJECT_THRESHOLD = -0.01219` (very loose — stock barely underperforming SPY is OK)
- `BACKTEST_RS_THRESHOLD_DEFAULT` in constants.py: `-0.01219` (same as above)
- `BacktestParams.rs_threshold = 0.066` (positive — stock must actively outperform SPY)

The backtest is substantially stricter on RS than the live scanner. A setup with rs_score=-0.005 passes live Engine 3 but is rejected in backtest scored mode.

---

### CRIT-6: `RES_SELECTIVE_REGIME_FACTOR=0.80` declared but never used
**File:** constants.py:274
**Detail:** This constant is imported by neither scoring.py nor backtest_engine.py. The `SELECTIVE_SETUP_WEIGHTS["RES_BREAKOUT"] = 1.0` in the same file contradicts the intent of an 0.80 factor for SELECTIVE regime. The constant has no effect on any code path — it is a dead constant.

---

### CRIT-7: Live engine6 gap fallback hardcoded at 0.042, not RES_MAX_GAP_PCT=0.036
**File:** engine6.py:87
**Detail:** `_gap_pct = getattr(params, "brk_gap_pct", 0.042)`. When `params=None` (all live scanner calls go through `scan_resistance_breakout` without params), the fallback is `0.042`. But `RES_MAX_GAP_PCT = 0.036`. These are 17% different. The constant exists but the live scanner is not using it — only the backtest uses it via `BacktestParams.brk_gap_pct=0.036`.

---

## 3. SILENT BUGS

### SIL-1: Pass 1 volume gate (1M) is stricter than Pass 2 liquidity gate (750K) using different metrics
Pass 1 filters by `avg_vol_20d ≥ 1,000,000` (20-day average).
Pass 2 filters by `50-day median vol ≥ 750,000`.
These use different windows (20d vs 50d), different statistics (average vs median), and different thresholds. A ticker can theoretically pass Pass 1 and fail Pass 2, or fail Pass 1 but would have passed Pass 2. They are inconsistent gates of the same intent.

---

### SIL-2: WATCHLIST proximity scoring cap hardcoded at 1.5% in scoring.py — will silently diverge if WATCHLIST_PROXIMITY_PCT changes
`scoring.py:369` has `(1.5 - dist) / 1.5` literally hardcoded. If `WATCHLIST_PROXIMITY_PCT` is ever changed in constants.py, scoring will not update. Additionally, `NEAR_PCT=5%` in engine6 watchlist scan produces setups with 1.5–5% distance — those all score 0 on vol component despite passing the engine gate.

---

### SIL-3: `_PIVOT_HISTORY_BARS = 252` in engine6.py is never used
Defined at module level (engine6.py:62) but the live pivot detection calls `_find_pivot_highs(high_arr[:n-1], _pivot_str)` over the full array with no 252-bar cap. The watchlist version uses `_find_confirmed_pivot_highs(..., lookback=126)` with its own literal. The `_PIVOT_HISTORY_BARS` constant has zero effect on any code path.

---

### SIL-4: RS cache age computed with `datetime.utcnow()` — deprecated in Python 3.12+
`scoring.py:149` uses `datetime.utcnow()`. On Windows machines not set to UTC, clock drift is not a practical issue (both write and read use utcnow), but the function is deprecated in Python 3.12 and will raise a warning. More importantly, the cache timestamp is written as a naive UTC datetime but read as if it were local — if anyone adds timezone-aware logic, comparisons will break silently.

---

### SIL-5: `BacktestParams.score_threshold=2.50` was frozen from v4 and never re-evaluated against v5 parameters
The comment says "frozen at 2.50 (not in v5 search space)". This controls pullback signal acceptance in scored mode. v5 changed `cci_threshold` to -54.5 (from -39.10 in live) and `ema_distance` to 1.651 — these produce signals with different internal score distributions. The 2.50 gate was calibrated against v4 signal distributions, making it potentially mis-calibrated for v5.

---

### SIL-6: Below-SMA50 adaptive filter silently degrades to fixed thresholds with no indication in scan output
In `_compute_below_sma50_thresholds()`, if `len(vol_vals) < PASS1_BELOW_SMA50_MIN_SAMPLE`, the system falls back to fixed constants. The scan output records `"rs_source": "warm"/"cold"` but does not indicate whether the adaptive or fixed thresholds were used, making it impossible to diagnose scan-to-scan threshold drift.

---

### SIL-7: Engine 3 pivot proximity formula creates wider tolerance for high-ATR stocks
`engine3.py:143`: `_prox_pct = max(0.03, 1.2 * latr / ll)`.
For a $15 stock with ATR=$0.90 (6%): proximity = `max(0.03, 0.072)` = 7.2%.
For a $100 stock with ATR=$1.50 (1.5%): proximity = `max(0.03, 0.018)` = 3.0%.
High-volatility stocks get systematically easier structural support detection. This is directionally correct (wider ATR = wider zone) but the `1.2` multiplier is unjustified and hardcoded.

---

## 4. OPTUNA vs PRODUCTION MISALIGNMENTS

| Parameter | Backtest (Optuna) | Live Production | Severity |
|-----------|------------------|-----------------|----------|
| `brk_vol_mult` | 3.016 | 2.0 | **HIGH** — 50% lower bar in production |
| `brk_stop_atr` | 1.668 | 0.8 | **HIGH** — production stop is 2× tighter |
| `brk_donchian_n` | 87 | 63 | **MEDIUM** — different resistance lookback |
| `brk_atr_expansion` | 1.474 | 0.0 (disabled) | **HIGH** — quality filter completely off in production |
| `brk_min_consolidation` | 10 | 3 | **HIGH** — production allows minimal consolidation |
| `brk_trail_mult` | 6.906 | 4.25 | **HIGH** — production exits trades much earlier |
| `CCI_STRICT_FLOOR` | -39.10 (live) | -54.5 (BacktestParams) | **MEDIUM** — different oversold floors |
| `base_quality_min` | 19 (backtest) | 25 (live) | **MEDIUM** — production is stricter |
| `base_vol_ratio` | 1.425 | 1.5 | **LOW** — close enough |
| `rs_threshold` | 0.066 (backtest scored) | -0.01219 (live engine3) | **HIGH** — sign and magnitude differ completely |
| Regime slope ±range | ±1.0% (backtest filters.py) | ±0.5% (live engine0.py) | **MEDIUM** — regime scoring inconsistent |

**Root cause:** Optuna ran on `BacktestParams` which the live scanner does NOT use. The live scanner uses module-level defaults in each engine file. These were last synced manually at an unknown point and have since diverged significantly, especially for RES_BREAKOUT.

---

## 5. CONCLUSIONS

### Parameters That Are Solid
- All Engine 7 (Options) parameters — internally consistent, self-contained, not Optuna-tuned
- Engine 8 / 9 parameters (HTF, LCE) — manually set, clear rationale, no conflicts
- `REGIME_SELECTIVE_THRESHOLD=59` — Optuna-tuned, consistently used by engine0
- `TARGET_RR=4.346` — Optuna v4, consistent across all engine stop/target calculations
- `VCP_TIGHT_RANGE_5D_PCT=0.03594` — Optuna v4, referenced consistently
- Cache infrastructure (RS cache TTL, atomic writes) — correctly implemented
- `RES_MAX_GAP_PCT=0.036` — consistent with BacktestParams.brk_gap_pct (the only aligned RES param)

### Parameters That Must Be Fixed
1. **Score weight sum = 105** — either reduce to sum to 100 or document the intentional overflow and update the comment
2. **`MIN_SETUP_SCORE_DEFENSIVE=45`** — wire into `score_and_filter_setups()` or delete it
3. **`RES_SELECTIVE_REGIME_FACTOR=0.80`** — wire into scoring or delete it (dead constant)
4. **Live engine6 gap fallback = 0.042** — should use `RES_MAX_GAP_PCT=0.036`; live scanner bypasses the constant
5. **`RS_REJECT_THRESHOLD` duplication** — `engine3.py:37` should import from `constants.BACKTEST_RS_THRESHOLD_DEFAULT`, not redefine it
6. **WATCHLIST scoring 1.5% proximity cap** — should reference `WATCHLIST_PROXIMITY_PCT` not hardcode 1.5
7. **`_PIVOT_HISTORY_BARS=252` in engine6.py** — delete it (unused)

### Parameters That Should Be Re-Optimized
1. **All BacktestParams RES_BREAKOUT fields** — the live scanner runs a substantially different engine than what Optuna tested; either sync live defaults to Optuna values (recommended) or run new Optuna with live defaults as the starting point
2. **`BacktestParams.rs_threshold=0.066`** vs live `RS_REJECT_THRESHOLD=-0.01219` — the magnitude difference is too large to be intentional; one of them is wrong
3. **`PULLBACK_TRAIL_ATR_MULT=4.25`** — frozen pending V5 300-trial optimization that has not run yet; current value is based on trial-0 only (n=361 OOS)
4. **`CCI_RLX_FLOOR=-20`** — restored from overfit; its interaction with `BacktestParams.cci_threshold=-54.5` in scored mode is untested
5. **`REGIME_SELECTIVE_THRESHOLD=59`** — was Optuna-tuned, but the regime score formula itself differs between live (±0.5% slope) and backtest (±1.0% slope); the threshold may have been calibrated on the wrong formula
6. **`BacktestParams.score_threshold=2.50`** — was frozen in v4, not included in v5 search space, but v5 changed the signal score distribution
