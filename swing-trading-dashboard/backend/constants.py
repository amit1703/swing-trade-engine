"""
Central constants for the swing trading scanner.
All hardcoded parameters are defined here for easy tuning and testing.
"""

# ──────────────────────────────────────────────────────────────────────────
# RS Line & Strength Thresholds
# ──────────────────────────────────────────────────────────────────────────

RS_BLUE_DOT_TOLERANCE_PCT = 0.005  # 0.5% tolerance for RS 52-week high detection
RS_RATIO_SCALE = 100.0  # Scale factor for RS ratio (for display purposes)

# ──────────────────────────────────────────────────────────────────────────
# Price & Proximity Thresholds
# ──────────────────────────────────────────────────────────────────────────

PRICE_RESISTANCE_PROXIMITY_PCT = 0.03  # 3% proximity for entry calculations
KDE_BREAKOUT_UPPER_PCT = 0.025  # 2.5% above resistance for KDE breakouts
KDE_BREAKOUT_LOWER_PCT = 0.001  # 0.1% below resistance for near-breakout detection
DRY_RESISTANCE_PROXIMITY_PCT = 0.05  # 5% proximity for dry setups
WATCHLIST_PROXIMITY_PCT = 0.015  # 1.5% below resistance for watchlist items
TRENDLINE_TOUCH_TOLERANCE_PCT = 0.015  # 1.5% tolerance for ascending trendline touch check
VCP_TIGHT_RANGE_5D_PCT = 0.03594       # Optuna v4 best (trial #951); was 0.04259 (v3)

# ── Engine 8: High Tight Flag ──────────────────────────────────────────────
HTF_LOOKBACK_DAYS     = 40    # Trading days to look back for the prior strong move
HTF_MIN_RUNUP_PCT     = 0.80  # Minimum 80% gain from period low to period high
HTF_MAX_FLAG_DEPTH_PCT= 0.25  # Flag consolidation depth ≤ 25%
HTF_MIN_FLAG_BARS     = 5     # Minimum 5 trading days of flag consolidation
HTF_MAX_FLAG_BARS     = 20    # Maximum 20 trading days of flag consolidation
HTF_MAX_EXTEND_PCT    = 0.05  # Max overextension above flag high (5%)
HTF_MAX_RISK_PCT      = 0.35  # Max stop-loss as fraction of entry (wide for HTF pattern)

# ── Engine 9: Low Cheat Entry ──────────────────────────────────────────────
LCE_MAX_DISTANCE_PCT      = 0.03  # Price within 3% below resistance
LCE_VOL_CONTRACTION_RATIO = 0.80  # 5-bar avg volume ≤ 80% of 20-day avg
LCE_MAX_RISK_PCT          = 0.15  # Max stop-loss as fraction of entry for LCE setups
LCE_TIGHT_RANGE_CONTRACTION = 0.70  # recent 5-bar range < 70% of prior → tight flag

# ──────────────────────────────────────────────────────────────────────────
# Time Periods & Candle Counts
# ──────────────────────────────────────────────────────────────────────────

TRADING_DAYS_IN_YEAR = 252  # Standard trading days for annualized metrics
DAYS_3_MONTHS = 64  # Approximately 3 months of trading days
MIN_CANDLES_FOR_ANALYSIS = 60  # Minimum candles required for ticker analysis
MIN_CANDLES_FOR_RS = 252  # Minimum candles required for RS Line calculation

# ──────────────────────────────────────────────────────────────────────────
# Volume & Volatility Parameters
# ──────────────────────────────────────────────────────────────────────────

VOL_SMA_PERIOD = 50  # Period for volume SMA calculation
VOL_SURGE_MULTIPLIER = 1.1078  # Optuna v4 best (trial #951); was 1.1155 (v3)
KDE_VOL_MULTIPLIER = 1.15  # 115% of SMA for KDE breakout volume
TRENDLINE_VOL_MULTIPLIER = 1.2  # 120% of SMA for trendline breakout volume

# ──────────────────────────────────────────────────────────────────────────
# Technical Indicator Periods
# ──────────────────────────────────────────────────────────────────────────

TR_WINDOW = 14  # True Range period for ATR
EMA_SHORT = 8  # Short-term EMA period
EMA_LONG = 20  # Long-term EMA period
SMA_LONG = 50  # Long-term SMA period
CCI_PERIOD = 20  # Commodity Channel Index period
CCI_STRICT_FLOOR = -39.10  # Optuna v4 best (trial #951); was -50.0 (v3)
CCI_RLX_FLOOR = -20.0   # restored from v4 overfit (-1.95 came from 43 OOS trades)

# ──────────────────────────────────────────────────────────────────────────
# Risk Management & Stop Loss
# ──────────────────────────────────────────────────────────────────────────

ATR_STOP_MULTIPLIER = 1.278  # Optuna v4 best (trial #951); was 1.360 (v3)
ENTRY_PRICE_MULTIPLIER = 1.001  # 0.1% above current price for entry orders
MIN_RISK_REWARD_RATIO = 1.0  # Minimum acceptable R:R ratio for setups
TARGET_RR             = 4.346   # Optuna trial #433 tp_multiple (converged, CV=0.017)
TRAIL_ATR_MULT        = 4.25   # frozen: V5 trial-0=4.43, V4=4.162, Phase2 range [3.46,5.41]

# V5: Setup-specific trailing ATR multipliers.
# All frozen to 4.25 pending full V5 optimization (300 trials).
# V5 optimizer tests a single uniform trail_mult across all setup types;
# trial 0 (n=361 OOS) found 4.43 optimal. 4.25 is a conservative anchor
# within the Phase 2 suggested range [3.46, 5.41].
# Previous per-setup values: VCP=2.0, PULLBACK=3.0, RES=4.25, BASE=4.162
# Most impactful change: PULLBACK 3.0 → 4.25 (holds winners longer on dominant setup).
VCP_TRAIL_ATR_MULT          = 4.25   # frozen (was 2.0; V5 trial-0 uniform = 4.43)
PULLBACK_TRAIL_ATR_MULT     = 4.25   # frozen (was 3.0; most impactful — 90% of backtest trades)
RES_BREAKOUT_TRAIL_ATR_MULT = 4.25   # unchanged
BASE_TRAIL_ATR_MULT         = 4.25   # frozen (was 4.162; rounded to match uniform)

# ── Position Sizing (risk model) ───────────────────────────────────────────────
RISK_PER_TRADE_PCT    = 1.25  # frozen: V5 trial-0=1.45, Phase2 range [1.30,1.50]; was 1.0
MAX_POSITION_SIZE_PCT = 25.0  # frozen: V5 trial-0=24.6, Phase2 range [21.6,27.6]; was 20.0
MAX_OPEN_POSITIONS    = 5     # max concurrent open positions per ticker

# ──────────────────────────────────────────────────────────────────────────
# VCP Volatility Contraction (Task 13)
# ──────────────────────────────────────────────────────────────────────────

VCP_ATR_CONTRACTION_THRESHOLD = 0.6  # ATR today < ATR20_avg × 0.6 confirms compression

# ──────────────────────────────────────────────────────────────────────────
# Phase 3 — RS Ranking & Unified Scoring (Tasks 8, 9, 10)
# ──────────────────────────────────────────────────────────────────────────

RS_RANK_MIN_PERCENTILE  = 70    # gate: skip tickers with RS rank < 70
TOP_SECTORS_N           = 8     # top N sectors by avg RS (raised from 5; scoring uses SECTOR_TIER1_N=5 for tier 1)
# V5 note: Optuna diagnostics show a quality inflection near regime_score ≈ 59.
# This is NOT enforced as a hard gate. Instead, SELECTIVE regime earns only
# SCORE_SELECTIVE_REGIME_FACTOR (53%) of AGGRESSIVE regime points, which reduces
# setup scores in the 40–69 regime band. MIN_SETUP_SCORE = 70 then filters these
# lower-quality setups. The combination of these three constants produces the
# effective quality drop observed near ~59 — keeping the behaviour as a soft
# scoring effect preserves flexibility vs a hard cutoff.
MIN_SETUP_SCORE         = 70    # gate: discard setups with unified score < 70
LOW_SAMPLE_THRESHOLD    = 20    # min trades per setup type for reliable diagnostics

# Score component weights (upper bounds; raw sum = 120, capped to 100 in compute_setup_score)
SCORE_WEIGHT_RS_RANK    = 30    # RS percentile rank
SCORE_WEIGHT_RR         = 20    # Reward-to-Risk ratio
SCORE_WEIGHT_VOL        = 20    # Volume surge / momentum
SCORE_WEIGHT_REGIME     = 15    # Market regime alignment
SCORE_WEIGHT_SECTOR     = 10    # Full pts for top-SECTOR_TIER1_N sectors; see SECTOR_TIER2_FACTOR/SECTOR_OUT_OF_TOP_FACTOR
SCORE_WEIGHT_QUALITY    = 5     # Pattern quality / confirmation signals
SCORE_WEIGHT_RS_QUALITY = 20    # RS momentum signals (improving, near-high, acceleration, tight range)
SCORE_SELECTIVE_REGIME_FACTOR = 0.53   # SELECTIVE regime earns 53% of AGGRESSIVE pts (~8/15)

# ──────────────────────────────────────────────────────────────────────────
# Data Processing
# ──────────────────────────────────────────────────────────────────────────

DATA_FETCH_PERIOD = "1y"  # Historical data lookback for each ticker (1y = 252 bars, covers all engines)
CONCURRENCY_LIMIT = 64  # Backtest reads local parquet only — no network, safe to run high concurrency
BATCH_SAVE_SIZE = 100  # Batch size for database operations (if needed)
FETCH_MAX_RETRIES = 4  # Maximum retry attempts for data fetches
FETCH_BACKOFF_BASE = 5.0  # Base delay for exponential backoff (seconds) — longer for rate limits
CACHE_TTL_SUCCESS = 14400  # Seconds to cache a successful fetch (4 hours)
CACHE_TTL_FAILURE = 900    # Seconds to cache a failed fetch — retry sooner (15 min)
PIVOT_LOOKBACK_DAYS       = 252    # 1 full trading year — captures macro bases
PIVOT_TOUCH_MARGIN_PCT    = 0.020  # 2.0% — catches real double-tops (was 1.5%)
PIVOT_MIN_SEPARATION_DAYS = 7      # minimum bars between two matching highs
PIVOT_MIN_TOUCHES         = 2      # minimum pivots to form a valid zone

# ── Market Regime Scoring Weights (Task 2) ─────────────────────────────────
REGIME_WEIGHT_EMA20    = 20   # SPY close > EMA20
REGIME_WEIGHT_SMA50    = 15   # SPY close > SMA50
REGIME_WEIGHT_MA_STACK = 15   # SMA50 > SMA200
REGIME_WEIGHT_SLOPE    = 10   # EMA20 slope over 5 days
REGIME_WEIGHT_BREADTH  = 20   # % universe above SMA50
REGIME_WEIGHT_HL       = 10   # New 52-week highs vs lows ratio
REGIME_WEIGHT_VIX      = 10   # VIX below its 20-day SMA

REGIME_AGGRESSIVE_THRESHOLD = 70   # 70–100 = AGGRESSIVE
REGIME_SELECTIVE_THRESHOLD  = 59   # Optuna v4 best (trial #951); was 54 (v3)
                                    # 0–39   = DEFENSIVE (Engines 2 & 3 disabled)

# ──────────────────────────────────────────────────────────────────────────
# Engine 7 — Options Catalyst
# ──────────────────────────────────────────────────────────────────────────
OPTIONS_MIN_ADV            = 500_000     # options engine liquidity gate (separate from LIQUIDITY_MIN_AVG_VOLUME)
OPTIONS_MIN_PRICE          = 10.0        # Min share price (no penny stocks)
OPTIONS_DTE_MIN            = 7           # Min days to expiry
OPTIONS_DTE_MAX            = 45          # Max days to expiry
OPTIONS_OTM_MAX_PCT        = 0.10        # Max OTM % for strike filter (10%)
OPTIONS_MIN_SCORE          = 45          # Minimum OPTIONS_SCORE to flag
OPTIONS_VOL_OI_TARGET      = 1.0         # Vol/OI ratio at which component maxes out
OPTIONS_CALL_VOL_TARGET    = 2000        # Absolute call volume at which component maxes out
OPTIONS_SKEW_NEUTRAL       = 0.5         # Call/Put skew at neutral (50/50)
OPTIONS_SKEW_MAX           = 0.9         # Call/Put skew at which component maxes out
OPTIONS_IV_SLOPE_TARGET    = 0.30        # IV term slope delta at which component maxes out

# ──────────────────────────────────────────────────────────────────────────
# Scan Settings
# ──────────────────────────────────────────────────────────────────────────

MAX_TICKERS_PER_SCAN = 2000  # Safety limit on ticker universe size
SCAN_TIMEOUT_SECONDS = 600  # Maximum scan duration (10 minutes)

# ──────────────────────────────────────────────────────────────────────────
# Database
# ──────────────────────────────────────────────────────────────────────────

DB_PATH = "trading.db"
DB_TIMEOUT = 10.0  # SQLite timeout in seconds

# ──────────────────────────────────────────────────────────────────────────
# Price Vitality / Zombie-Stock Filter
# ──────────────────────────────────────────────────────────────────────────

VITALITY_LOOKBACK_DAYS = 10   # Trading days used for H-L range check
VITALITY_MIN_RANGE_PCT = 0.02  # Minimum H-L range (2%) to pass vitality

# ──────────────────────────────────────────────────────────────────────────
# Universe Pre-Filter
# ──────────────────────────────────────────────────────────────────────────

MIN_ATR_PCT = 2.5           # ATR(14)/Close×100 minimum — filters low-vol stocks

# ──────────────────────────────────────────────────────────────────────────
# Liquidity Gate (Task 7) — enforced per-ticker before engines run
# ──────────────────────────────────────────────────────────────────────────

LIQUIDITY_MIN_AVG_VOLUME    = 750_000      # raised from 500K — tighter volume gate
LIQUIDITY_MIN_DOLLAR_VOLUME = 25_000_000   # raised from 20M — tighter dollar volume gate

# ──────────────────────────────────────────────────────────────────────────
# Earnings Blackout (Task 1) — skip tickers with earnings within N days
# ──────────────────────────────────────────────────────────────────────────

EARNINGS_BLACKOUT_DAYS    = 7             # calendar days before earnings → skip
EARNINGS_CACHE_FILE       = "cache/earnings_cache.json"
EARNINGS_CACHE_TTL_HOURS  = 24            # refresh cache entries older than this

# ──────────────────────────────────────────────────────────────────────────
# Bulk Download (Task 5)
# ──────────────────────────────────────────────────────────────────────────

BULK_DOWNLOAD_BATCH_SIZE = 200            # tickers per yf.download() call

# ──────────────────────────────────────────────────────────────────────────────
# Walk-Forward Validation (WFO)
# ──────────────────────────────────────────────────────────────────────────────

WFO_CACHE_DIR         = "data/price_cache"   # relative to backend/
WFO_LOOKBACK_YEARS    = 10                   # years of history to download
WFO_MIN_HISTORY_YEARS = 5                    # minimum usable years before rejecting
WFO_BULK_BATCH_SIZE   = 100                  # tickers per yf.download() call

# ──────────────────────────────────────────────────────────────────────────
# Engine Hardening (2026-03-07)
# ──────────────────────────────────────────────────────────────────────────

# VCP contraction gates
VCP_MIN_CONTRACTIONS_STRICT  = 3   # Path A (DRY): >=3 progressive contractions required
VCP_MIN_CONTRACTIONS_RELAXED = 2   # Paths B/C/D (breakout): >=2 contractions required

# LCE mini-breakout trigger
LCE_BREAKOUT_VOL_RATIO = 1.0       # LCE: volume must be >= 1x 20-day avg on breakout bar

# BASE breakout filter
BASE_BRK_MIN_VOL_RATIO = 1.5       # BASE BRK signal: raised from 1.2x to 1.5x

# RES_BREAKOUT tighter filters
RES_LAUNCHPAD_BARS         = 5     # Pre-breakout consolidation bars (was 3)
RES_DECISIVE_MIN_PCT       = 0.02  # Decisive close minimum = 2% above zone (diagnostic: <2% → neg expectancy)
RES_DECISIVE_ATR_FACTOR    = 0.5400  # Optuna v4 best (trial #951); was 0.4725 (v3)
RES_STOP_ATR_FACTOR        = 0.8   # Stop = zone_lower − 0.8×ATR (was 0.2; allows normal retests)
RES_BREAKOUT_VOL_MULT      = 2.0   # Minimum breakout volume (×50d avg); diagnostic: <2x → neg expectancy
RES_MAX_GAP_PCT            = 0.036 # Skip T+1 entry if open > zone_upper × (1 + 3.6%); prevents gap-chasing [WFO v1: aligned with brk_gap_pct]
RES_SELECTIVE_REGIME_FACTOR = 0.80 # Score multiplier for RES_BREAKOUT in non-AGGRESSIVE regimes

# ──────────────────────────────────────────────────────────────────────────────
# Universe & Pre-Scan Filtering (2026-03-07)
# ──────────────────────────────────────────────────────────────────────────────

# Universe loader aging thresholds
UNIVERSE_MAX_AGE_DAYS  = 7     # hard cutoff: universe older than this → use tickers.py fallback
UNIVERSE_WARN_AGE_DAYS = 5     # soft: log WARNING if universe is aging but still usable

# Universe size sanity checks (logged as warnings, not hard stops)
UNIVERSE_MIN_SIZE      = 800   # warn if universe smaller (filter may be too tight)
UNIVERSE_MAX_SIZE      = 2_500 # warn if universe larger (filter may be too loose)

# RS tier 1 scoring boost
RS_TIER1_THRESHOLD  = 85    # RS rank >= 85 → Tier 1 (market leader)
RS_TIER1_MULTIPLIER = 1.15  # multiply RS score component by 1.15 for Tier 1 tickers

# Sector gate tiers (TOP_SECTORS_N=8 total; top SECTOR_TIER1_N=5 get full points)
SECTOR_TIER1_N           = 5    # top N sectors → full SCORE_WEIGHT_SECTOR pts (10)
SECTOR_TIER2_FACTOR      = 0.8  # sectors ranked 6–8 → 80% of sector points (8 pts)
SECTOR_OUT_OF_TOP_FACTOR = 0.4  # sectors outside top 8 → 40% of sector points (4 pts)

# Discovery layer — RS 60-70 emerging leaders bypass the RS >= 70 gate
DISCOVERY_RS_MIN        = 60    # lower RS bound (inclusive) for discovery candidates
DISCOVERY_RS_MAX        = 70    # upper RS bound (exclusive; 70 = regular gate floor)
DISCOVERY_52WK_HIGH_PCT = 0.03  # close must be within 3% of 52-week high
DISCOVERY_VOL_RATIO     = 1.5   # 5-day avg vol must be >= 1.5x 50-day avg
DISCOVERY_MAX_PCT       = 0.10  # cap discovery candidates at 10% of universe size

# ── V4 Backtest Diagnostics ───────────────────────────────────────────────────
BACKTEST_DIAG_START_DATE = "2020-01-01"   # extended to 5-year window for SELECTIVE analysis
BACKTEST_DIAG_END_DATE   = "2024-12-31"   # fixed 2-year baseline window end
BACKTEST_V4_TRAIL_MULT   = 4.162          # strict V4 single trail multiplier (all setup types)
BACKTEST_DIAG_CACHE_FILE = "cache/backtest_diagnostics.json"   # relative to backend/

# V5 Scored-mode defaults (Optuna-tunable, used as BacktestParams defaults)
BACKTEST_RS_THRESHOLD_DEFAULT = -0.01219   # V4 Optuna best; RS_REJECT_THRESHOLD in engine3

# ── SELECTIVE Regime Setup Filtering ──────────────────────────────────────────
# Controls which setup types are allowed / penalized in SELECTIVE regime.
# Populated after running the 2020-2024 backtest and reviewing selective_analysis.

SELECTIVE_MIN_SAMPLE      = 30    # minimum trades to classify a setup (raised from 20)
SELECTIVE_EXPECTANCY_FLOOR = 0.10  # minimum expectancy (R) to classify as STRONG

# Per-setup score weights in SELECTIVE regime.
#   1.0  = no change (full score)
#   0.5  = 50% score penalty — setup needs to be stronger to survive MIN_SETUP_SCORE gate
#   0.0  = effectively blocked in soft mode; hard-blocked when SELECTIVE_HARD_FILTER=True
# Derived from 2020-2024 legacy-mode backtest (828 tickers, full universe):
#   PULLBACK:     n=351  win=48%  exp=+0.106R → WEAK  (below 0.10R floor, keep 0.5 penalty)
#   RES_BREAKOUT: n=191  win=35%  exp=+0.164R → EDGE  (≈ AGGRESSIVE +0.175R — full weight)
#   BASE:         n=4    → INSUFFICIENT DATA — no penalty until more data
#   HTF:          n=1    → INSUFFICIENT DATA — no penalty until more data
#
# Weight=0.5 on PULLBACK means score×0.5 < 70 for all setups (max score=100),
# effectively pausing new entries in SELECTIVE regime. Revisit when PULLBACK
# expectancy in SELECTIVE rises above SELECTIVE_EXPECTANCY_FLOOR=0.10R.
# RES_BREAKOUT: diagnostic confirmed edge in SELECTIVE (n=191, +0.164R) — weight=1.0.
SELECTIVE_SETUP_WEIGHTS: dict = {
    "PULLBACK":     0.5,   # WEAK:  exp=+0.106R — effectively blocks in soft mode
    "RES_BREAKOUT": 1.0,   # EDGE:  exp=+0.164R — same as AGGRESSIVE, full weight
}

# Hard filter mode: if True, setups with weight == 0.0 are skipped entirely.
# If False (default), weight is applied as a score multiplier and the
# MIN_SETUP_SCORE gate naturally filters out penalized setups.
SELECTIVE_HARD_FILTER: bool = False

# ──────────────────────────────────────────────────────────────────────────
# ATR-Normalized Entry Quality Thresholds (Task 1)
# ──────────────────────────────────────────────────────────────────────────

# ATR-normalized entry quality thresholds (used in frontend scanner filter)
# entryAtrDist = (livePrice - entry) / atr
#   < EARLY_THRESHOLD  → EARLY  (hasn't reached entry yet or barely touched)
#   < EXTENDED_THRESHOLD → OPTIMAL (within range — good R:R)
#   >= EXTENDED_THRESHOLD → EXTENDED (chasing — hide by default)
ATR_ENTRY_EARLY_THRESHOLD:    float = 0.13  # frozen: V5 trial-0=0.132, Phase2 range [0.106,0.157]; was 0.1
ATR_ENTRY_EXTENDED_THRESHOLD: float = 0.40  # frozen: V5 trial-0=0.394, Phase2 range [0.304,0.484]; was 0.5

# ── Trade management mode ─────────────────────────────────────────────────────
# "ema20" = dynamic EMA20-based trail (Phase 1 initial stop → Phase 2 EMA20 trail)
# "atr"   = legacy fixed ATR multiplier trail (A/B fallback)
TRAIL_MODE: str = "ema20"
