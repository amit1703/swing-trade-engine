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
VCP_TIGHT_RANGE_5D_PCT = 0.025         # 2.5% close range over 5 days signals price compression

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
VOL_SURGE_MULTIPLIER = 1.5  # 150% of SMA for volume surge detection
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
CCI_STRICT_FLOOR = -50.0  # CCI oversold floor for strict pullback hook
CCI_RLX_FLOOR = -20.0  # CCI oversold floor for relaxed pullback hook

# ──────────────────────────────────────────────────────────────────────────
# Risk Management & Stop Loss
# ──────────────────────────────────────────────────────────────────────────

ATR_STOP_MULTIPLIER = 0.8  # ATR × multiplier below swing low (widened to prevent stop hunts)
ENTRY_PRICE_MULTIPLIER = 1.001  # 0.1% above current price for entry orders
MIN_RISK_REWARD_RATIO = 1.0  # Minimum acceptable R:R ratio for setups
TARGET_RR             = 2.0  # Default take-profit multiplier (change to 3.0 for 3:1 target)

# ──────────────────────────────────────────────────────────────────────────
# VCP Volatility Contraction (Task 13)
# ──────────────────────────────────────────────────────────────────────────

VCP_ATR_CONTRACTION_THRESHOLD = 0.6  # ATR today < ATR20_avg × 0.6 confirms compression

# ──────────────────────────────────────────────────────────────────────────
# Phase 3 — RS Ranking & Unified Scoring (Tasks 8, 9, 10)
# ──────────────────────────────────────────────────────────────────────────

RS_RANK_MIN_PERCENTILE  = 70    # gate: skip tickers with RS rank < 70
TOP_SECTORS_N           = 5     # top N sectors by avg RS score
MIN_SETUP_SCORE         = 70    # gate: discard setups with unified score < 70

# Score component weights (must sum to 100)
SCORE_WEIGHT_RS_RANK    = 30    # RS percentile rank
SCORE_WEIGHT_RR         = 20    # Reward-to-Risk ratio
SCORE_WEIGHT_VOL        = 20    # Volume surge / momentum
SCORE_WEIGHT_REGIME     = 15    # Market regime alignment
SCORE_WEIGHT_SECTOR     = 10    # Sector in top-5 by RS
SCORE_WEIGHT_QUALITY    = 5     # Pattern quality / confirmation signals
SCORE_WEIGHT_RS_QUALITY = 20    # RS momentum signals (improving, near-high, acceleration, tight range)
SCORE_SELECTIVE_REGIME_FACTOR = 0.53   # SELECTIVE regime earns 53% of AGGRESSIVE pts (~8/15)

# ──────────────────────────────────────────────────────────────────────────
# Data Processing
# ──────────────────────────────────────────────────────────────────────────

DATA_FETCH_PERIOD = "1y"  # Historical data lookback for each ticker (1y = 252 bars, covers all engines)
CONCURRENCY_LIMIT = 15  # Max concurrent yfinance API requests (lowered for stability)
BATCH_SAVE_SIZE = 100  # Batch size for database operations (if needed)
FETCH_MAX_RETRIES = 3  # Maximum retry attempts for data fetches
FETCH_BACKOFF_BASE = 1.0  # Base delay for exponential backoff (seconds)
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
REGIME_SELECTIVE_THRESHOLD  = 40   # 40–69  = SELECTIVE
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

MIN_ATR_PCT = 2.0           # ATR(14)/Close×100 minimum — filters low-vol stocks

# ──────────────────────────────────────────────────────────────────────────
# Liquidity Gate (Task 7) — enforced per-ticker before engines run
# ──────────────────────────────────────────────────────────────────────────

LIQUIDITY_MIN_AVG_VOLUME    = 500_000      # 50-day avg share volume minimum
LIQUIDITY_MIN_DOLLAR_VOLUME = 20_000_000   # price × avg volume (daily $) minimum

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
