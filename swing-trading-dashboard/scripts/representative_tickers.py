"""
Representative ticker basket for Optuna parameter optimization.

~35 tickers selected across sectors and market-cap ranges to expose
the optimizer to diverse market behaviours without full-universe cost.
Duplicates are stripped at import time.
"""

_RAW = [
    # Large-cap tech / mega-cap
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    # Momentum / high-growth
    "TSLA", "META", "CRWD", "PANW", "SNOW",
    # Mid-cap growth
    "CELH", "ENPH", "MELI", "SQ", "DXCM",
    # Industrials / cyclicals
    "CAT", "DE", "URI", "GWW", "PCAR",
    # Financials
    "JPM", "GS", "V", "MA", "PYPL",
    # Healthcare
    "UNH", "ISRG", "IDXX", "VEEV",
    # Energy / materials
    "XOM", "CVX", "FCX",
    # Consumer discretionary
    "HD", "NKE", "SBUX",
]

REPRESENTATIVE_TICKERS: list[str] = list(dict.fromkeys(_RAW))  # preserve order, deduplicate
