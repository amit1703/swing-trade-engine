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

# ──────────────────────────────────────────────────────────────────────────
# Time Periods & Candle Counts
# ──────────────────────────────────────────────────────────────────────────

TRADING_DAYS_IN_YEAR = 252  # Standard trading days for annualized metrics
DAYS_3_MONTHS = 64  # Approximately 3 months of trading days
DAYS_52_WEEKS = 252  # 52-week high lookback (1 year)
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

# ──────────────────────────────────────────────────────────────────────────
# Risk Management & Stop Loss
# ──────────────────────────────────────────────────────────────────────────

ATR_STOP_MULTIPLIER = 0.2  # 20% of ATR below swing low for stop placement
ENTRY_PRICE_MULTIPLIER = 1.001  # 0.1% above current price for entry orders
MIN_RISK_REWARD_RATIO = 1.0  # Minimum acceptable R:R ratio for setups

# ──────────────────────────────────────────────────────────────────────────
# Data Processing
# ──────────────────────────────────────────────────────────────────────────

DATA_FETCH_PERIOD = "2y"  # Historical data lookback for each ticker (2y for S/R and SMA200 coverage)
CONCURRENCY_LIMIT = 15  # Max concurrent yfinance API requests (lowered for stability)
BATCH_SAVE_SIZE = 100  # Batch size for database operations (if needed)
FETCH_MAX_RETRIES = 3  # Maximum retry attempts for data fetches
FETCH_BACKOFF_BASE = 1.0  # Base delay for exponential backoff (seconds)

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
