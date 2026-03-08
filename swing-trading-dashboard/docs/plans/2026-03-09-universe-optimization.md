# Universe Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Test universe sizes U1(35), U2(80), U3(150), U4(300) top-RS stocks with fixed v3 best params to find the largest universe that increases opportunity flow without degrading edge.

**Architecture:** Two scripts — `scripts/build_extended_cache.py` downloads candidates to Parquet cache and outputs a RS-ranked ticker list, then `scripts/universe_sweep.py` loads best params from `config/best_parameters.json`, applies them via `_patch_constants`, and runs WFO for each universe size. Output is a comparison table printed to stdout and saved to `docs/universe-sweep-results.json`.

**Tech Stack:** Python, yfinance (via `wfo_cache.download_and_cache`), Optuna study (read-only), asyncio, `wfo_engine.run_wfo`, parquet cache in `backend/data/price_cache/`

---

## Context

### Existing infrastructure
- `backend/wfo_cache.py`: `download_and_cache(tickers, job_id, progress)` — bulk yfinance download to parquet
- `backend/wfo_engine.py`: `run_wfo(tickers, setup_types, is_months, oos_months, step_months, run_id)` — WFO. Tickers **must** be cached first (`cache_exists()` check, skips missing).
- `backend/indicators/indicator_engine.py`: `_compute_rs_score(ticker_close, spy_df)` — O'Neil RS formula: `(63d×40%) + (126d×20%) + (189d×20%) + (252d×20%)`
- `backend/data/price_cache/`: 53 parquet files already (52 tickers + SPY)
- `scripts/optimize_parameters.py`: `_patch_constants`, `_aggregate_oos_metrics`, `_compute_robustness_score` — reuse these
- `scripts/representative_tickers.py`: U1 baseline (35 tickers)
- `config/best_parameters.json`: written by optimizer on finish — contains `parameters` dict with 8 params

### WFO config (same as Optuna v3)
```python
WFO_SETUP_TYPES = ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT"]
WFO_IS_MONTHS   = 36
WFO_OOS_MONTHS  = 6
WFO_STEP_MONTHS = 6
```

### Best params (trial #204, score=0.0939)
```json
{
  "ATR_MULTIPLIER":        1.3787,
  "VCP_TIGHTNESS_RANGE":   0.0426,
  "BREAKOUT_BUFFER_ATR":   0.4690,
  "BREAKOUT_VOL_MULT":     1.1120,
  "TARGET_RR":             2.6741,
  "TRAIL_ATR_MULT":        2.9582,
  "REGIME_BULL_THRESHOLD": 54,
  "ENGINE3_RS_THRESHOLD":  -0.0330
}
```

These are loaded from `config/best_parameters.json["parameters"]` at runtime.

### RS scoring from cache
RS can be computed directly from the cached parquet files without running the full indicator engine:
```python
import pandas as pd
from pathlib import Path

CACHE_DIR = Path("backend/data/price_cache")

def compute_rs_from_cache(ticker: str, spy_df: pd.DataFrame) -> float:
    """Compute O'Neil RS score from cached parquet data."""
    path = CACHE_DIR / f"{ticker}.parquet"
    if not path.exists():
        return float("-inf")
    df = pd.read_parquet(path)
    close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    close = df[close_col].dropna()
    spy_close_col = "Adj Close" if "Adj Close" in spy_df.columns else "Close"
    spy_close = spy_df[spy_close_col].dropna()

    PERIODS = [63, 126, 189, 252]
    WEIGHTS = [0.40, 0.20, 0.20, 0.20]
    weighted = 0.0; total_w = 0.0
    for period, weight in zip(PERIODS, WEIGHTS):
        if len(close) <= period or len(spy_close) <= period:
            continue
        tk_ret  = close.iloc[-1] / close.iloc[-period] - 1.0
        spy_ret = spy_close.iloc[-1] / spy_close.iloc[-period] - 1.0
        weighted += weight * (tk_ret - spy_ret)
        total_w  += weight
    return round(weighted / total_w, 4) if total_w > 0 else 0.0
```

---

## Candidate Ticker List (~300 large/mid-cap US stocks)

These will be used as the download pool for U2/U3/U4. Already-cached tickers are skipped. List chosen to cover S&P 500 sectors with adequate liquidity:

```python
CANDIDATE_TICKERS = [
    # ALREADY CACHED (52 tickers + SPY — no re-download needed)
    # Technology
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","CRWD","PANW","SNOW",
    "ADBE","AMD","INTC","ORCL","QCOM","CRM","AVGO",
    # Financials
    "JPM","GS","V","MA","PYPL","BAC",
    # Healthcare
    "UNH","ISRG","IDXX","VEEV","LLY","MRK","PFE",
    # Consumer/Retail
    "HD","NKE","SBUX","MELI","SQ","COST","WMT","LOW",
    # Industrials
    "CAT","DE","URI","GWW","PCAR","BA",
    # Energy/Materials
    "XOM","CVX","FCX",
    # Growth/Tech
    "CELH","ENPH","DXCM","UBER","NFLX",
    # Telecom
    "T",

    # NEW — need to download (~248 more tickers for ~300 total pool)
    # Large-cap tech
    "AAON","ACN","AMAT","ANSS","APP","ASML","CDNS","CSCO","FTNT","INTU",
    "LRCX","MU","NOW","SNPS","TXN","ZS","PLTR","DDOG","NET","TEAM",
    # Semis / Hardware
    "SMCI","ON","MPWR","KLAC","AEHR","WOLF","SITM","RMBS","CRUS",
    # Financials
    "AXP","BLK","MS","WFC","C","BX","KKR","APO","COIN","HOOD",
    # Healthcare
    "TMO","DHR","ABT","BSX","MDT","ELV","CVS","CI","HCA","MOH",
    "REGN","MRNA","BIIB","GILD","AMGN","VRTX","INCY","ALNY",
    # Consumer Discretionary
    "AMZN","BKNG","RCL","CCL","MGM","WYNN","LVS","TJX","ROST","ULTA",
    "DG","DLTR","TSCO","YUM","MCD","CMG","DKNG",
    # Consumer Staples
    "PG","KO","PEP","MDLZ","CL","GIS","K","MKC","CHD",
    # Energy
    "OXY","EOG","SLB","HAL","MPC","PSX","VLO","DVN","FANG","PXD",
    # Industrials
    "RTX","LMT","NOC","GE","HON","MMM","EMR","ETN","ROK","PH","TDG",
    "AXON","LDOS","CACI","SAIC","BAH",
    # Materials
    "NEM","GOLD","ALB","MP","FSLR","ENPH",
    # REITs / Utilities (lower priority)
    "NEE","D","SO","DUK","XEL","AES",
    # Mid-cap growth
    "GTLB","BILL","MNDY","ZI","PCVX","RBRK","DOCS","RNG","HUBS","FIVN",
    "CELH","WING","BROS","CAVA","SHAK","LULU","ONON","SKX",
    "AXON","PODD","TMDX","INSP","NTRA","RXRX","TWST","ACLX",
    # Additional momentum names
    "SMTC","ASTS","LUNR","RKLB","IREN","MARA","CLSK","RIOT","HUT",
]
```

> **Note:** This list will have duplicates removed and already-cached tickers skipped in the script.

---

## Task 1: `scripts/build_extended_cache.py`

Downloads uncached candidate tickers to parquet and outputs RS-ranked ticker list.

**Files:**
- Create: `scripts/build_extended_cache.py`

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""
build_extended_cache.py — Download candidate tickers and output RS-ranked list.

Usage:
    cd swing-trading-dashboard/backend
    python ../scripts/build_extended_cache.py
    python ../scripts/build_extended_cache.py --dry-run   # show what would be downloaded

Outputs:
    - Downloads missing tickers to backend/data/price_cache/
    - Prints RS-ranked ticker list
    - Saves scripts/rs_ranked_tickers.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR))

import argparse
import pandas as pd
from wfo_cache import download_and_cache, cache_exists, load_ticker, CACHE_DIR

# ── Candidate pool (duplicates removed in code) ───────────────────────────────
CANDIDATE_TICKERS = [
    # Tech
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","CRWD","PANW","SNOW",
    "ADBE","AMD","INTC","ORCL","QCOM","CRM","AVGO","AMAT","CDNS","CSCO",
    "FTNT","INTU","LRCX","MU","NOW","SNPS","TXN","ZS","PLTR","DDOG","NET",
    "TEAM","ON","MPWR","KLAC","APP","ANSS",
    # Financials
    "JPM","GS","V","MA","PYPL","BAC","AXP","BLK","MS","WFC","C",
    "BX","KKR","APO","COIN",
    # Healthcare
    "UNH","ISRG","IDXX","VEEV","LLY","MRK","PFE","TMO","DHR","ABT",
    "BSX","MDT","ELV","CVS","CI","HCA","MOH","REGN","MRNA","BIIB",
    "GILD","AMGN","VRTX","INCY","ALNY","NTRA","PODD","INSP","TMDX",
    # Consumer Discretionary
    "HD","NKE","SBUX","MELI","SQ","COST","WMT","LOW","BKNG","RCL",
    "TJX","ROST","ULTA","DG","YUM","MCD","CMG","DKNG","LULU","ONON",
    "WING","CAVA","BROS","SKX",
    # Energy/Materials
    "XOM","CVX","FCX","OXY","EOG","SLB","HAL","MPC","PSX","VLO",
    "DVN","NEM","ALB","FSLR","ENPH",
    # Industrials
    "CAT","DE","URI","GWW","PCAR","BA","RTX","LMT","NOC","GE","HON",
    "ETN","TDG","AXON","PH","ROK","EMR",
    # Mid-cap growth / momentum
    "CELH","DXCM","UBER","NFLX","HUBS","GTLB","MNDY","ZI","DOCS",
    "FIVN","BILL","RNG","RXRX","TWST","RBRK","ASTS","RKLB",
    # Telecom
    "T",
]


def compute_rs_from_cache(ticker: str, spy_close: pd.Series) -> float:
    """O'Neil composite RS score from cached parquet vs SPY."""
    path = CACHE_DIR / f"{ticker}.parquet"
    if not path.exists():
        return float("-inf")
    try:
        df = pd.read_parquet(path)
    except Exception:
        return float("-inf")
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    if col not in df.columns:
        return float("-inf")
    close = df[col].dropna()

    PERIODS = [63, 126, 189, 252]
    WEIGHTS = [0.40, 0.20, 0.20, 0.20]
    weighted = 0.0; total_w = 0.0
    for period, weight in zip(PERIODS, WEIGHTS):
        if len(close) <= period or len(spy_close) <= period:
            continue
        tk_ret  = close.iloc[-1] / close.iloc[-period] - 1.0
        spy_ret = spy_close.iloc[-1] / spy_close.iloc[-period] - 1.0
        weighted += weight * (tk_ret - spy_ret)
        total_w  += weight
    return round(weighted / total_w, 4) if total_w > 0 else 0.0


def main(dry_run: bool = False) -> None:
    # Deduplicate candidate list
    seen: set = set()
    candidates = []
    for t in CANDIDATE_TICKERS:
        if t not in seen and t != "SPY":
            seen.add(t)
            candidates.append(t)

    missing = [t for t in candidates if not cache_exists(t)]
    print(f"Candidates: {len(candidates)}  |  Already cached: {len(candidates) - len(missing)}  |  To download: {len(missing)}")

    if missing and not dry_run:
        print(f"Downloading {len(missing)} tickers...")
        progress: dict = {}
        results = download_and_cache(missing, job_id="universe_build", progress=progress)
        failed = [t for t, ok in results.items() if not ok]
        if failed:
            print(f"  Failed ({len(failed)}): {failed}")
        print(f"  Done. Success: {len(missing) - len(failed)}/{len(missing)}")
    elif dry_run:
        print(f"DRY RUN — would download: {missing}")

    # Load SPY for RS computation
    spy_df = load_ticker("SPY")
    if spy_df is None:
        print("ERROR: SPY not cached — run wfo_cache first")
        sys.exit(1)
    spy_col = "Adj Close" if "Adj Close" in spy_df.columns else "Close"
    spy_close = spy_df[spy_col].dropna()

    # Score all cached candidates
    scored = []
    for t in candidates:
        if cache_exists(t):
            rs = compute_rs_from_cache(t, spy_close)
            scored.append((t, rs))

    scored.sort(key=lambda x: x[1], reverse=True)

    print(f"\nRS-ranked universe ({len(scored)} tickers):")
    print(f"{'Rank':>4}  {'Ticker':<8}  {'RS Score':>8}")
    print("-" * 26)
    for i, (t, rs) in enumerate(scored, 1):
        print(f"{i:>4}  {t:<8}  {rs:>8.4f}")

    # Save ranked list
    output = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "total_tickers": len(scored),
        "ranked": [{"ticker": t, "rs_score": rs} for t, rs in scored],
    }
    out_path = Path(__file__).parent / "rs_ranked_tickers.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show what would be downloaded without downloading")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
```

**Step 2: Run dry-run to verify it works without downloading**

From `backend/` directory:
```bash
python ../scripts/build_extended_cache.py --dry-run
```
Expected: prints candidate count, already-cached count, list of missing tickers. No downloads. Exit 0.

**Step 3: Commit**

```bash
git add scripts/build_extended_cache.py
git commit -m "feat(universe): add build_extended_cache script — downloads candidates, outputs RS-ranked list"
```

---

## Task 2: `scripts/universe_sweep.py`

Runs WFO for each universe size with fixed best params and prints comparison table.

**Files:**
- Create: `scripts/universe_sweep.py`
- Reads: `config/best_parameters.json`, `scripts/rs_ranked_tickers.json`

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""
universe_sweep.py — Test universe sizes U1→U4 with fixed best parameters.

Prerequisite:
    1. Run optimize_parameters.py to completion (creates config/best_parameters.json)
    2. Run build_extended_cache.py to download candidates (creates scripts/rs_ranked_tickers.json)

Usage:
    cd swing-trading-dashboard/backend
    python ../scripts/universe_sweep.py
    python ../scripts/universe_sweep.py --params-file ../config/best_parameters.json
    python ../scripts/universe_sweep.py --sizes 35 80   # only run U1 and U2

Output:
    - Comparison table to stdout
    - docs/universe-sweep-results.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR  = _BACKEND_DIR.parent

sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR))

from wfo_engine import run_wfo
from wfo_cache import cache_exists
from representative_tickers import REPRESENTATIVE_TICKERS
from optimize_parameters import (
    _patch_constants,
    _aggregate_oos_metrics,
    _compute_robustness_score,
    WFO_SETUP_TYPES,
    WFO_IS_MONTHS,
    WFO_OOS_MONTHS,
    WFO_STEP_MONTHS,
    _preload_modules,
)

_DEFAULT_SIZES = [35, 80, 150, 300]
_OUTPUT_PATH   = _PROJECT_DIR / "docs" / "universe-sweep-results.json"
_RS_RANKED     = _SCRIPTS_DIR / "rs_ranked_tickers.json"


def _load_best_params(params_file: Path) -> dict:
    """Load best parameters from JSON file."""
    if not params_file.exists():
        raise FileNotFoundError(
            f"Best parameters not found at {params_file}. "
            "Run optimize_parameters.py first."
        )
    data = json.loads(params_file.read_text())
    return data["parameters"]


def _load_rs_ranked_tickers(top_n: int) -> list[str]:
    """Load top-N tickers by RS score from rs_ranked_tickers.json."""
    if not _RS_RANKED.exists():
        raise FileNotFoundError(
            f"RS ranked tickers not found at {_RS_RANKED}. "
            "Run build_extended_cache.py first."
        )
    data = json.loads(_RS_RANKED.read_text())
    ranked = [entry["ticker"] for entry in data["ranked"]]
    # Filter to only cached tickers
    cached = [t for t in ranked if cache_exists(t)]
    if len(cached) < top_n:
        print(f"  WARNING: only {len(cached)} cached tickers available (requested {top_n})")
    return cached[:top_n]


def _build_universe(size: int) -> list[str]:
    """Build ticker list for a given universe size."""
    if size <= 35:
        # U1: use representative tickers (fixed, not RS-filtered)
        return REPRESENTATIVE_TICKERS
    else:
        return _load_rs_ranked_tickers(size)


async def _run_universe(universe_label: str, tickers: list[str], params: dict) -> dict:
    """Run WFO for one universe size and return metrics."""
    print(f"\n  Running {universe_label}: {len(tickers)} tickers...")
    tickers_with_spy = ["SPY"] + [t for t in tickers if t != "SPY"]

    with _patch_constants(params):
        result = await run_wfo(
            tickers=tickers_with_spy,
            setup_types=WFO_SETUP_TYPES,
            is_months=WFO_IS_MONTHS,
            oos_months=WFO_OOS_MONTHS,
            step_months=WFO_STEP_MONTHS,
            run_id=f"universe_sweep_{universe_label.lower().replace(' ', '_')}",
        )

    metrics = _aggregate_oos_metrics(result.windows)
    score = _compute_robustness_score(
        expectancy=metrics["expectancy"],
        profit_factor=metrics["profit_factor"],
        total_trades=metrics["total_trades"],
        max_drawdown_pct=metrics["max_drawdown_pct"],
    )
    return {
        "label":          universe_label,
        "n_tickers":      len(tickers),
        "score":          round(score, 4),
        "total_trades":   metrics["total_trades"],
        "trades_per_year": round(metrics["total_trades"] / 2.0, 1),  # ~2 years OOS
        "win_rate":       metrics["win_rate"],
        "expectancy":     metrics["expectancy"],
        "profit_factor":  metrics["profit_factor"],
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "net_profit_pct": metrics["net_profit_pct"],
    }


def _print_table(results: list[dict]) -> None:
    """Print comparison table."""
    print("\n" + "=" * 90)
    print("  UNIVERSE SWEEP RESULTS")
    print("=" * 90)
    header = f"{'Label':<12} {'Tickers':>7} {'Score':>7} {'Trades':>7} {'T/yr':>5} {'Win%':>6} {'E':>7} {'PF':>5} {'MaxDD%':>7} {'Net%':>7}"
    print(header)
    print("-" * 90)
    for r in results:
        print(
            f"{r['label']:<12} {r['n_tickers']:>7} {r['score']:>7.4f} "
            f"{r['total_trades']:>7} {r['trades_per_year']:>5.1f} "
            f"{r['win_rate']:>6.1f} {r['expectancy']:>7.4f} "
            f"{r['profit_factor']:>5.2f} {r['max_drawdown_pct']:>7.2f} "
            f"{r['net_profit_pct']:>7.2f}"
        )
    print("=" * 90)


def main(params_file: Path, sizes: list[int]) -> None:
    _preload_modules()
    params = _load_best_params(params_file)

    print("Universe Sweep — Fixed params from:", params_file)
    print("Universe sizes:", sizes)
    print("Parameters:", {k: round(v, 4) if isinstance(v, float) else v for k, v in params.items()})

    results = []
    for size in sizes:
        universe = _build_universe(size)
        label = f"U{sizes.index(size) + 1} ({size})"
        result = asyncio.run(_run_universe(label, universe, params))
        results.append(result)
        print(f"  → score={result['score']:.4f} trades={result['total_trades']} t/yr={result['trades_per_year']}")

    _print_table(results)

    # Save results
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "params_source": str(params_file),
        "parameters": params,
        "results": results,
    }
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    print(f"\nSaved to {_OUTPUT_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Universe size sweep with fixed best params")
    parser.add_argument("--params-file", type=Path,
                        default=_PROJECT_DIR / "config" / "best_parameters.json",
                        help="Path to best_parameters.json (default: config/best_parameters.json)")
    parser.add_argument("--sizes", type=int, nargs="+", default=_DEFAULT_SIZES,
                        help="Universe sizes to test (default: 35 80 150 300)")
    args = parser.parse_args()
    main(params_file=args.params_file, sizes=args.sizes)
```

**Step 2: Write tests**

File: `backend/tests/test_universe_sweep.py`

```python
"""Tests for universe_sweep.py helpers."""
import json
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import universe_sweep as sweep


def test_load_best_params_missing_raises(tmp_path):
    missing = tmp_path / "nonexistent.json"
    with pytest.raises(FileNotFoundError, match="best_parameters.json"):
        sweep._load_best_params(missing)


def test_load_best_params_returns_parameters(tmp_path):
    data = {"parameters": {"ATR_MULTIPLIER": 1.38, "TRAIL_ATR_MULT": 2.96}}
    p = tmp_path / "best.json"
    p.write_text(json.dumps(data))
    result = sweep._load_best_params(p)
    assert result["ATR_MULTIPLIER"] == 1.38
    assert result["TRAIL_ATR_MULT"] == 2.96


def test_load_rs_ranked_tickers_missing_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(sweep, "_RS_RANKED", tmp_path / "nonexistent.json")
    with pytest.raises(FileNotFoundError, match="rs_ranked_tickers.json"):
        sweep._load_rs_ranked_tickers(10)


def test_load_rs_ranked_tickers_filters_uncached(monkeypatch, tmp_path):
    ranked_data = {
        "ranked": [
            {"ticker": "AAPL", "rs_score": 0.15},
            {"ticker": "MSFT", "rs_score": 0.12},
            {"ticker": "NVDA", "rs_score": 0.10},
        ]
    }
    p = tmp_path / "rs_ranked.json"
    p.write_text(json.dumps(ranked_data))
    monkeypatch.setattr(sweep, "_RS_RANKED", p)
    # Only AAPL and NVDA are "cached"
    monkeypatch.setattr(sweep, "cache_exists", lambda t: t in {"AAPL", "NVDA"})
    result = sweep._load_rs_ranked_tickers(10)
    assert result == ["AAPL", "NVDA"]


def test_build_universe_u1_uses_representative():
    universe = sweep._build_universe(35)
    from representative_tickers import REPRESENTATIVE_TICKERS
    assert universe == REPRESENTATIVE_TICKERS


def test_build_universe_large_calls_rs_ranked(monkeypatch):
    monkeypatch.setattr(sweep, "_load_rs_ranked_tickers", lambda n: [f"T{i}" for i in range(n)])
    result = sweep._build_universe(80)
    assert len(result) == 80
    assert result[0] == "T0"
```

**Step 3: Run tests (verify they pass)**

```bash
cd backend
pytest tests/test_universe_sweep.py -v
```
Expected: 5 tests pass.

**Step 4: Run dry smoke test of main script (missing params file)**

```bash
cd backend
python ../scripts/universe_sweep.py --params-file /nonexistent.json 2>&1 | head -5
```
Expected: `FileNotFoundError: Best parameters not found...`

**Step 5: Commit**

```bash
git add scripts/universe_sweep.py backend/tests/test_universe_sweep.py
git commit -m "feat(universe): add universe_sweep script + tests — U1-U4 WFO comparison with fixed best params"
```

---

## Task 3: Run the full sweep (AFTER optimizer finishes)

> ⚠️ **Wait condition:** Tasks 1-2 can be implemented while the optimizer runs. Task 3 only executes AFTER PID 47158 exits and `config/best_parameters.json` is written.

**Step 1: Confirm optimizer finished**

```bash
ps aux | grep optimize_parameters | grep -v grep
# Expected: no output (process gone)
cat ../config/best_parameters.json | python3 -c "import json,sys; d=json.load(sys.stdin); print('Score:', d['best_score'])"
```

**Step 2: Download extended universe**

```bash
cd backend
python ../scripts/build_extended_cache.py
```
Expected: downloads ~200 new tickers, saves RS-ranked list to `scripts/rs_ranked_tickers.json`. Takes ~5-10 minutes.

**Step 3: Run universe sweep (U1 + U2 first as smoke test)**

```bash
cd backend
python ../scripts/universe_sweep.py --sizes 35 80
```
Expected: prints metrics for U1(35) and U2(80). U1 score should be close to 0.0939.

**Step 4: Run full sweep**

```bash
cd backend
python ../scripts/universe_sweep.py --sizes 35 80 150 300
```
Expected: full comparison table. Takes ~30-60 minutes (4 WFO runs).

**Step 5: Review and document findings**

After sweep completes, record in `docs/universe-sweep-results.md`:
- Which universe size maximizes score
- Trade frequency across sizes
- Edge degradation threshold (where PF and expectancy start dropping)
- Recommended universe size for v4

---

## Expected Outcomes

| Universe | Tickers | Expected behavior |
|---|---|---|
| U1 (35) | Representative (curated) | Baseline: ~40 trades/yr, score ~0.09 |
| U2 (80) | Top-80 RS | More trades, similar or better edge if RS filter is good |
| U3 (150) | Top-150 RS | Diminishing returns or slight edge decay begin |
| U4 (300) | Top-300 RS | More noise, potential edge degradation |

**Key insight to measure:** At what universe size does the increase in trade frequency stop compensating for the decrease in signal quality?

---

## Reference

- v3 best params: `docs/optuna-v3-final-report.md`
- v4 parameter proposals: `docs/optuna-v4-proposal-2026-03-08.md`
- WFO engine: `backend/wfo_engine.py`
- Cache system: `backend/wfo_cache.py`
