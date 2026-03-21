# scripts/representative_tickers_v2.py
"""
Expanded representative ticker basket for v5 risk optimizer.

~80 tickers: all 35 from v1 plus mid/small-cap additions across sectors.
Raises AssertionError at import time if duplicates exist.
"""

_RAW = [
    # ── All 35 from v1 ────────────────────────────────────────────────────────
    # Large-cap tech / mega-cap
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    # Momentum / high-growth
    "TSLA", "META", "PANW",  # CRWD/SNOW removed: IPO 2019/2020, too new for IS=36m WFO
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

    # ── v2 additions ──────────────────────────────────────────────────────────
    # Mid-cap growth / momentum
    "SMCI", "DUOL", "APP", "AXON", "MNDY",
    # Small/mid momentum (HIMS/RKT removed: IPO 2019/2020, too new)
    "CAVA", "NTRA",
    # Cyclicals / energy
    "SLB", "MPC", "FANG", "NUE",
    # Healthcare (RVMD removed: IPO Feb 2020, too new)
    "PODD", "ALNY",
    # Financials
    "COIN", "HOOD", "IBKR",
    # Additional large-cap diversification
    "LLY", "ABBV", "NOW", "ADBE", "QCOM",
    "AMD", "MU", "AMAT", "LRCX",
    # Consumer / retail
    "COST", "TGT", "LULU",
    # Industrials add-ons
    "GNRC", "ENVA", "LFUS",
]

assert len(_RAW) == len(set(_RAW)), (
    f"Duplicate tickers in _RAW: "
    f"{[t for t in set(_RAW) if _RAW.count(t) > 1]}"
)

REPRESENTATIVE_TICKERS_V2: list[str] = list(_RAW)
