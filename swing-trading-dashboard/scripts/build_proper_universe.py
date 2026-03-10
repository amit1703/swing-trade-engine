"""
build_proper_universe.py — Full 1500-stock market universe construction pipeline.

Pipeline:
  Step 1: SEC fetch + pattern filter          (~fast)
  Step 2: Price/volume filter                 (~2 min)
  Step 3: RS screener over filtered universe  (~3 min, data truncated to cutoff)
  Step 4: Cache top 200                       (~20-40 min, new tickers only)
  Step 5: Save rs_ranked_tickers.json + rs_universe_full.json

Usage:
  python scripts/build_proper_universe.py              # full pipeline
  python scripts/build_proper_universe.py --dry-run    # steps 1-3 only
  python scripts/build_proper_universe.py --top-n 200  # how many to cache (default 200)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Path setup — works whether run from project root or backend/
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPTS_DIR.parent / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

from universe_builder import fetch_sec_tickers, filter_ticker_patterns, filter_price_volume  # noqa: E402
from wfo_cache import download_and_cache, cache_exists  # noqa: E402

# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------
_RS_RANKED_FILE = _SCRIPTS_DIR / "rs_ranked_tickers.json"
_RS_FULL_FILE = _SCRIPTS_DIR / "rs_universe_full.json"

# ---------------------------------------------------------------------------
# RS computation
# ---------------------------------------------------------------------------

RS_BATCH_SIZE = 100
RS_BATCH_DELAY = 1.0


def _compute_rs(close: pd.Series, spy_close: pd.Series) -> float:
    """O'Neil composite RS — data must already be truncated to cutoff.

    Returns float("-inf") if insufficient history for even the shortest period.
    """
    PERIODS = [63, 126, 189, 252]
    WEIGHTS = [0.40, 0.20, 0.20, 0.20]
    weighted = 0.0
    total_w = 0.0
    for period, weight in zip(PERIODS, WEIGHTS):
        if len(close) <= period or len(spy_close) <= period:
            continue
        tk_ret = close.iloc[-1] / close.iloc[-period] - 1.0
        spy_ret = spy_close.iloc[-1] / spy_close.iloc[-period] - 1.0
        weighted += weight * (tk_ret - spy_ret)
        total_w += weight
    return round(weighted / total_w, 4) if total_w > 0 else 0.0


def _strip_tz(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Remove timezone info from a DatetimeIndex."""
    if idx.tz is not None:
        return idx.tz_convert(None)
    return idx


def _extract_close(df: pd.DataFrame, ticker: str, multi: bool) -> pd.Series | None:
    """Extract close series for *ticker* from a yfinance download result.

    yfinance MultiIndex layout differs between single- and multi-ticker calls:
      - multi-ticker (group_by="ticker"): level 0 = ticker, level 1 = field
        e.g. columns = [("AAPL", "Adj Close"), ("AAPL", "Close"), ...]
      - single-ticker: level 0 = field, level 1 = ticker
        e.g. columns = [("Adj Close", "SPY"), ("Close", "SPY"), ...]
    """
    if multi:
        if not isinstance(df.columns, pd.MultiIndex):
            return None
        # Level 0 = ticker, level 1 = field
        if ticker not in df.columns.get_level_values(0):
            return None
        ticker_df = df[ticker]  # sub-DataFrame with flat columns (field names)
        close_col = "Adj Close" if "Adj Close" in ticker_df.columns else "Close"
        if close_col not in ticker_df.columns:
            return None
        close = ticker_df[close_col].dropna()
    else:
        # Single-ticker: may be MultiIndex(field, ticker) or flat
        if isinstance(df.columns, pd.MultiIndex):
            # level 0 = field, level 1 = ticker
            close_col = (
                "Adj Close"
                if "Adj Close" in df.columns.get_level_values(0)
                else "Close"
            )
            close = df[close_col].iloc[:, 0].dropna()  # first (only) ticker column
        else:
            close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
            close = df[close_col].dropna()

    if close.empty:
        return None
    idx = _strip_tz(close.index)
    close = close.copy()
    close.index = idx
    return close


def _download_spy_for_cutoff(cutoff_start: str, cutoff_end: str) -> pd.Series:
    """Download SPY close series for the RS computation window."""
    df = yf.download(
        "SPY",
        start=cutoff_start,
        end=cutoff_end,
        interval="1d",
        auto_adjust=False,
        progress=False,
    )
    if df is None or df.empty:
        raise RuntimeError("Failed to download SPY for RS cutoff window")
    # Single-ticker download: yfinance returns MultiIndex(field, ticker) or flat columns
    if isinstance(df.columns, pd.MultiIndex):
        # level 0 = field, level 1 = ticker
        close_col = (
            "Adj Close"
            if "Adj Close" in df.columns.get_level_values(0)
            else "Close"
        )
        spy_close = df[close_col].iloc[:, 0].dropna()
    else:
        close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
        spy_close = df[close_col].dropna()
    spy_close = spy_close.copy()
    spy_close.index = _strip_tz(spy_close.index)
    return spy_close


def compute_rs_scores(
    tickers: List[str],
    cutoff_date: datetime,
) -> List[dict]:
    """Compute RS scores for all tickers using data up to cutoff_date.

    Returns a list of dicts: [{"ticker": ..., "rs_score": ...}, ...],
    sorted descending by rs_score. Tickers with insufficient history
    (rs_score == float("-inf")) are placed at the end.
    """
    cutoff_end = cutoff_date.strftime("%Y-%m-%d")
    cutoff_start = (cutoff_date - timedelta(days=1095)).strftime("%Y-%m-%d")
    cutoff_ts = pd.Timestamp(cutoff_date)

    print(f"  Downloading SPY for cutoff window {cutoff_start} → {cutoff_end}...")
    spy_close = _download_spy_for_cutoff(cutoff_start, cutoff_end)
    # Belt-and-suspenders: filter to <= cutoff
    spy_close = spy_close[spy_close.index <= cutoff_ts]
    if spy_close.empty:
        raise RuntimeError("SPY has no data up to cutoff date")

    total_batches = (len(tickers) + RS_BATCH_SIZE - 1) // RS_BATCH_SIZE
    scores: List[dict] = []

    for batch_idx in range(total_batches):
        start = batch_idx * RS_BATCH_SIZE
        batch = tickers[start : start + RS_BATCH_SIZE]
        print(f"  Batch {batch_idx + 1}/{total_batches}: {len(batch)} tickers...", flush=True)

        try:
            multi = len(batch) > 1
            if multi:
                df = yf.download(
                    batch,
                    start=cutoff_start,
                    end=cutoff_end,
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                    threads=True,
                    group_by="ticker",
                )
            else:
                df = yf.download(
                    batch[0],
                    start=cutoff_start,
                    end=cutoff_end,
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                )
        except Exception as exc:
            print(f"  WARNING: batch {batch_idx + 1} download failed: {exc}")
            for t in batch:
                scores.append({"ticker": t, "rs_score": float("-inf")})
            continue

        if df is None or df.empty:
            for t in batch:
                scores.append({"ticker": t, "rs_score": float("-inf")})
            if batch_idx < total_batches - 1:
                time.sleep(RS_BATCH_DELAY)
            continue

        for ticker in batch:
            try:
                close = _extract_close(df, ticker, multi)
                if close is None or close.empty:
                    scores.append({"ticker": ticker, "rs_score": float("-inf")})
                    continue
                # Truncate to cutoff (belt-and-suspenders)
                close = close[close.index <= cutoff_ts]
                if close.empty or len(close) < 63:
                    scores.append({"ticker": ticker, "rs_score": float("-inf")})
                    continue
                # Guard against zero prices (would produce inf RS)
                if (close <= 0).any():
                    scores.append({"ticker": ticker, "rs_score": float("-inf")})
                    continue
                rs = _compute_rs(close, spy_close)
                # Reject non-finite results (inf/-inf/nan from bad data)
                if not math.isfinite(rs):
                    scores.append({"ticker": ticker, "rs_score": float("-inf")})
                    continue
                scores.append({"ticker": ticker, "rs_score": rs})
            except Exception as exc:
                print(f"  WARNING: RS computation failed for {ticker}: {exc}")
                scores.append({"ticker": ticker, "rs_score": float("-inf")})

        if batch_idx < total_batches - 1:
            time.sleep(RS_BATCH_DELAY)

    # Sort: valid scores desc, then -inf tickers at end
    valid = sorted(
        [s for s in scores if s["rs_score"] != float("-inf")],
        key=lambda x: x["rs_score"],
        reverse=True,
    )
    invalid = [s for s in scores if s["rs_score"] == float("-inf")]
    return valid + invalid


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

ALREADY_CACHED_TICKERS = {
    "SPY", "AAPL", "ABT", "ADBE", "ALB", "ALNY", "AMAT", "AMD", "AMGN", "AMZN",
    "APO", "ASTS", "AVGO", "AXON", "AXP", "BA", "BAC", "BIIB", "BILL", "BKNG",
    "BLK", "BSX", "BX", "C", "CAT", "CDNS", "CELH", "CI", "CMG", "COST", "CRM",
    "CRWD", "CSCO", "CVS", "CVX", "DDOG", "DE", "DG", "DHR", "DKNG", "DVN",
    "DXCM", "ELV", "EMR", "ENPH", "EOG", "ETN", "FCX", "FIVN", "FSLR", "FTNT",
    "GE", "GILD", "GOOGL", "GS", "GWW", "HAL", "HCA", "HD", "HON", "HUBS",
    "IDXX", "INCY", "INSP", "INTC", "INTU", "ISRG", "JPM", "KKR", "KLAC", "LLY",
    "LMT", "LOW", "LRCX", "LULU", "MA", "MCD", "MDT", "MELI", "META", "MOH",
    "MPC", "MPWR", "MRK", "MRNA", "MS", "MSFT", "MU", "NEM", "NET", "NFLX",
    "NKE", "NOC", "NOW", "NTRA", "NVDA", "ON", "ORCL", "OXY", "PANW", "PCAR",
    "PFE", "PH", "PLTR", "PODD", "PSX", "PYPL", "QCOM", "RCL", "REGN", "RKLB",
    "RNG", "ROK", "ROST", "RTX", "SBUX", "SLB", "SNOW", "SNPS", "T", "TDG",
    "TEAM", "TJX", "TMDX", "TMO", "TSLA", "TWST", "TXN", "UBER", "ULTA", "UNH",
    "URI", "V", "VEEV", "VLO", "VRTX", "WFC", "WING", "WMT", "XOM", "YUM", "ZS",
}


def run_pipeline(dry_run: bool = False, top_n: int = 200) -> None:
    today = datetime.utcnow().date()
    cutoff_date = datetime(today.year, today.month, today.day) - timedelta(days=730)
    cutoff_str = cutoff_date.strftime("%Y-%m-%d")
    generated_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")

    print(f"\n{'='*60}")
    print(f"Build Proper Universe  (cutoff: {cutoff_str})")
    if dry_run:
        print("DRY-RUN mode: steps 1-3 only, no cache download")
    print(f"{'='*60}\n")

    # ── Step 1: SEC fetch + pattern filter ───────────────────────────────────
    print("Step 1/5: Fetching SEC universe...")
    sec_df = fetch_sec_tickers()
    if sec_df.empty:
        print("ERROR: SEC fetch returned empty DataFrame. Aborting.")
        sys.exit(1)
    print(f"  → {len(sec_df)} raw tickers from SEC")

    candidates = filter_ticker_patterns(sec_df["ticker"].tolist())
    print(f"  → {len(candidates)} after pattern filter")

    # ── Step 2: Price/volume filter ──────────────────────────────────────────
    print("\nStep 2/5: Price/volume filter (min price=$10, min volume=500K)...")
    liquid = filter_price_volume(candidates, min_price=10.0, min_avg_volume=500_000)
    print(f"  → {len(liquid)} liquid stocks passed")

    universe_total = len(liquid)

    if universe_total == 0:
        print("ERROR: No liquid stocks found. Aborting.")
        sys.exit(1)

    # ── Step 3: RS screener ──────────────────────────────────────────────────
    print(f"\nStep 3/5: Computing RS scores (cutoff: {cutoff_str})...")
    all_scored = compute_rs_scores(liquid, cutoff_date)

    valid_scores = [s for s in all_scored if s["rs_score"] != float("-inf")]
    invalid_scores = [s for s in all_scored if s["rs_score"] == float("-inf")]
    print(f"  → {len(valid_scores)} RS scores computed ({len(invalid_scores)} excluded due to insufficient history)")

    if dry_run:
        print("\n[DRY-RUN] Skipping Step 4 (cache download) and Step 5 (file save).")
        print(f"\nTop 20 RS-ranked tickers (preview):")
        for i, entry in enumerate(all_scored[:20], 1):
            print(f"  {i:3d}. {entry['ticker']:8s}  RS={entry['rs_score']:+.4f}")
        print(f"\nDry-run complete. universe_total={universe_total}, valid_scores={len(valid_scores)}")
        return

    # ── Step 4: Cache top-N tickers ──────────────────────────────────────────
    print(f"\nStep 4/5: Caching top {top_n} tickers (full 10-year history)...")
    top_tickers = [s["ticker"] for s in all_scored[:top_n]]

    already_cached = [t for t in top_tickers if cache_exists(t)]
    need_download = [t for t in top_tickers if not cache_exists(t)]

    print(f"  Already cached: {len(already_cached)} / {top_n}")
    print(f"  Downloading {len(need_download)} new tickers...")

    if need_download:
        progress: dict = {}
        results = download_and_cache(
            need_download,
            job_id="build_proper_universe",
            progress=progress,
        )
        succeeded = sum(1 for v in results.values() if v)
        failed = sum(1 for v in results.values() if not v)
        print(f"  Downloaded: {succeeded} succeeded, {failed} failed")
    print("  → Done")

    # ── Step 5: Save results ──────────────────────────────────────────────────
    print("\nStep 5/5: Saving results...")

    # Build cached-only ranked list (for rs_ranked_tickers.json)
    cached_ranked = [
        {"ticker": s["ticker"], "rs_score": s["rs_score"]}
        for s in all_scored[:top_n]
        if cache_exists(s["ticker"])
    ]

    rs_ranked_data = {
        "generated_at": generated_at,
        "rs_cutoff_date": cutoff_str,
        "universe_source": "SEC EDGAR + yfinance liquidity filter",
        "universe_total": universe_total,
        "cached_top_n": top_n,
        "total_tickers": len(cached_ranked),
        "ranked": cached_ranked,
    }
    with open(_RS_RANKED_FILE, "w", encoding="utf-8") as f:
        json.dump(rs_ranked_data, f, indent=2)
    print(f"  → {_RS_RANKED_FILE} ({len(cached_ranked)} cached tickers)")

    # Build full universe file
    all_ranked_with_cache_flag = [
        {
            "ticker": s["ticker"],
            "rs_score": s["rs_score"] if s["rs_score"] != float("-inf") else None,
            "cached": cache_exists(s["ticker"]),
        }
        for s in all_scored
    ]

    rs_full_data = {
        "generated_at": generated_at,
        "rs_cutoff_date": cutoff_str,
        "universe_total": universe_total,
        "all_ranked": all_ranked_with_cache_flag,
    }
    with open(_RS_FULL_FILE, "w", encoding="utf-8") as f:
        json.dump(rs_full_data, f, indent=2)
    print(f"  → {_RS_FULL_FILE} ({universe_total} total)")

    print(f"\n{'='*60}")
    print("Pipeline complete!")
    print(f"  universe_total  : {universe_total}")
    print(f"  cached tickers  : {len(cached_ranked)}")
    print(f"  rs_cutoff_date  : {cutoff_str}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build proper swing-trading universe from SEC EDGAR (~1500 liquid stocks)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run steps 1-3 only (no cache download, no file save)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=200,
        metavar="N",
        help="Number of top RS stocks to cache (default: 200)",
    )
    args = parser.parse_args()
    run_pipeline(dry_run=args.dry_run, top_n=args.top_n)


if __name__ == "__main__":
    main()
