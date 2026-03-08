"""
build_extended_cache.py — Download candidate tickers to the parquet price cache
and compute no-lookahead O'Neil RS scores for universe sweep.

Usage (run from backend/ directory):
    python ../scripts/build_extended_cache.py           # download + rank
    python ../scripts/build_extended_cache.py --dry-run # preview only
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Path setup — script lives in scripts/, backend/ is the working directory
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

from wfo_cache import cache_exists, download_and_cache, load_ticker  # noqa: E402

# ---------------------------------------------------------------------------
# Candidate universe
# ---------------------------------------------------------------------------
CANDIDATE_TICKERS = [
    # Tech (some already cached)
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "CRWD", "PANW", "SNOW",
    "ADBE", "AMD", "INTC", "ORCL", "QCOM", "CRM", "AVGO", "AMAT", "CDNS", "CSCO",
    "FTNT", "INTU", "LRCX", "MU", "NOW", "SNPS", "TXN", "ZS", "PLTR", "DDOG", "NET",
    "TEAM", "ON", "MPWR", "KLAC", "APP", "ANSS",
    # Financials
    "JPM", "GS", "V", "MA", "PYPL", "BAC", "AXP", "BLK", "MS", "WFC", "C",
    "BX", "KKR", "APO", "COIN",
    # Healthcare
    "UNH", "ISRG", "IDXX", "VEEV", "LLY", "MRK", "PFE", "TMO", "DHR", "ABT",
    "BSX", "MDT", "ELV", "CVS", "CI", "HCA", "MOH", "REGN", "MRNA", "BIIB",
    "GILD", "AMGN", "VRTX", "INCY", "ALNY", "NTRA", "PODD", "INSP", "TMDX",
    # Consumer Discretionary
    "HD", "NKE", "SBUX", "MELI", "SQ", "COST", "WMT", "LOW", "BKNG", "RCL",
    "TJX", "ROST", "ULTA", "DG", "YUM", "MCD", "CMG", "DKNG", "LULU", "ONON",
    "WING", "CAVA", "BROS", "SKX",
    # Energy/Materials
    "XOM", "CVX", "FCX", "OXY", "EOG", "SLB", "HAL", "MPC", "PSX", "VLO",
    "DVN", "NEM", "ALB", "FSLR", "ENPH",
    # Industrials
    "CAT", "DE", "URI", "GWW", "PCAR", "BA", "RTX", "LMT", "NOC", "GE", "HON",
    "ETN", "TDG", "AXON", "PH", "ROK", "EMR",
    # Mid-cap growth / momentum
    "CELH", "DXCM", "UBER", "NFLX", "HUBS", "GTLB", "MNDY", "ZI", "DOCS",
    "FIVN", "BILL", "RNG", "RXRX", "TWST", "RBRK", "ASTS", "RKLB",
    # Telecom
    "T",
]

# Deduplicate and remove SPY (benchmark, not ranked)
_seen: set[str] = set()
TICKERS: list[str] = []
for _t in CANDIDATE_TICKERS:
    _upper = _t.upper()
    if _upper != "SPY" and _upper not in _seen:
        _seen.add(_upper)
        TICKERS.append(_upper)


# ---------------------------------------------------------------------------
# RS scoring helpers
# ---------------------------------------------------------------------------

def _get_close(ticker: str) -> pd.Series | None:
    """Load cached parquet and return a Close price Series indexed by date."""
    df = load_ticker(ticker)
    if df is None or df.empty:
        return None
    # Handle MultiIndex columns (yfinance batch download artifact)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if "Close" not in df.columns:
        return None
    close = df["Close"].copy()
    # Ensure DatetimeIndex
    if not isinstance(close.index, pd.DatetimeIndex):
        close.index = pd.to_datetime(close.index)
    # Drop timezone info for consistent comparison
    if close.index.tz is not None:
        close.index = close.index.tz_convert(None)
    return close


def _period_return(close: pd.Series, n: int) -> float | None:
    """Compute n-day return as (last / n_days_ago) - 1, or None if not enough data."""
    if len(close) < n + 1:
        return None
    return float(close.iloc[-1] / close.iloc[-(n + 1)] - 1)


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download candidate tickers and compute no-lookahead RS scores."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded and existing RS scores; no actual download.",
    )
    args = parser.parse_args()

    # ── 1. Determine which tickers need downloading ────────────────────────
    missing = [t for t in TICKERS if not cache_exists(t)]
    already_cached = [t for t in TICKERS if cache_exists(t)]

    print(f"\n=== build_extended_cache ===")
    print(f"Total candidates  : {len(TICKERS)}")
    print(f"Already cached    : {len(already_cached)}")
    print(f"Need downloading  : {len(missing)}")

    if missing:
        print(f"\nTickers to download:")
        for i, t in enumerate(missing, 1):
            print(f"  {i:3d}. {t}")

    if args.dry_run:
        print("\n[DRY RUN] Skipping download. Computing RS scores from cached data only.\n")
    else:
        # ── 2. Download missing tickers ────────────────────────────────────
        if missing:
            print(f"\nDownloading {len(missing)} tickers (this may take several minutes)...")
            progress: dict = {}
            results = download_and_cache(missing, job_id="build_extended_cache", progress=progress)
            succeeded = [t for t, ok in results.items() if ok]
            failed = [t for t, ok in results.items() if not ok]
            print(f"  Downloaded successfully: {len(succeeded)}")
            if failed:
                print(f"  Failed (skipped)       : {len(failed)} — {failed}")
        else:
            print("\nAll tickers already cached — no download needed.")

    # ── 3. No-lookahead cutoff ─────────────────────────────────────────────
    cutoff_date = datetime.today() - timedelta(days=730)
    cutoff_str = cutoff_date.strftime("%Y-%m-%d")
    print(f"\nRS cutoff date (today - 730 days (≈ 2 years)): {cutoff_str}")

    # ── 4. Load SPY and truncate to cutoff ────────────────────────────────
    spy_close_full = _get_close("SPY")
    if spy_close_full is None:
        print("ERROR: SPY not in cache. Cannot compute RS scores.", file=sys.stderr)
        sys.exit(1)
    spy_close = spy_close_full[spy_close_full.index <= cutoff_date]
    if spy_close.empty:
        print("ERROR: SPY series is empty after applying cutoff.", file=sys.stderr)
        sys.exit(1)

    # ── 5. Compute RS scores for all candidates ───────────────────────────
    print(f"\nComputing RS scores for all {len(TICKERS)} candidates...")
    ranked: list[dict] = []
    skipped: list[str] = []

    for ticker in TICKERS:
        if not cache_exists(ticker):
            skipped.append(ticker)
            continue
        # Truncate stock data to cutoff (no-lookahead)
        stock_close = _get_close(ticker)
        if stock_close is None:
            print(f"  WARN: {ticker} — loaded but no usable close data, skipping")
            skipped.append(ticker)
            continue
        stock_close_full = stock_close
        # Monkey-patch: replace close with truncated version for scoring
        # We do this inline rather than modifying _get_close
        stock_close_truncated = stock_close_full[stock_close_full.index <= cutoff_date]
        if stock_close_truncated.empty or len(stock_close_truncated) < 253:
            skipped.append(ticker)
            continue

        # Compute RS using truncated series for both stock and SPY
        weights = [(63, 0.40), (126, 0.20), (189, 0.20), (252, 0.20)]
        score = 0.0
        valid = True
        for n, w in weights:
            stock_ret = _period_return(stock_close_truncated, n)
            spy_ret = _period_return(spy_close, n)
            if stock_ret is None or spy_ret is None:
                valid = False
                break
            score += w * (stock_ret - spy_ret)

        if valid:
            ranked.append({"ticker": ticker, "rs_score": round(score, 6)})
        else:
            skipped.append(ticker)

    # Sort descending by RS score (highest relative strength first)
    ranked.sort(key=lambda x: x["rs_score"], reverse=True)

    # ── 6. Print results table ────────────────────────────────────────────
    print(f"\n{'Rank':>4}  {'Ticker':<8}  {'RS Score':>10}")
    print("-" * 30)
    for i, entry in enumerate(ranked, 1):
        print(f"{i:>4}  {entry['ticker']:<8}  {entry['rs_score']:>10.4f}")

    if skipped:
        print(f"\nSkipped (not cached or insufficient history): {skipped}")

    # ── 7. Save JSON output ───────────────────────────────────────────────
    output = {
        "generated_at": datetime.now().isoformat(),
        "rs_cutoff_date": cutoff_str,
        "total_tickers": len(ranked),
        "ranked": ranked,
    }

    output_path = _SCRIPTS_DIR / "rs_ranked_tickers.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved RS rankings to: {output_path}")
    print(f"Total ranked: {len(ranked)} tickers")
    print("Done.")


if __name__ == "__main__":
    main()
