"""
universe_sweep.py — Compare WFO performance across 4 ticker universes of increasing size.

Usage (run from backend/ directory):
    python ../scripts/universe_sweep.py                                # all 4 universes
    python ../scripts/universe_sweep.py --sizes 35 80                  # U1 and U2 only
    python ../scripts/universe_sweep.py --params-file ../config/best_parameters.json

Universes:
    U1 (35)  — REPRESENTATIVE_TICKERS (curated basket, not RS-filtered)
    U2 (80)  — Top 80 by RS score from rs_ranked_tickers.json (cached tickers only)
    U3 (120) — Top 120 by RS score from rs_ranked_tickers.json (cached tickers only)
    U4 (all) — All ranked tickers from rs_ranked_tickers.json (cached tickers only)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _BACKEND_DIR.parent

sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR))

# ── Paths ─────────────────────────────────────────────────────────────────────
_DEFAULT_PARAMS_FILE = _PROJECT_DIR / "config" / "best_parameters.json"
_RS_RANKED_FILE = _SCRIPTS_DIR / "rs_ranked_tickers.json"
_OUTPUT_FILE = _PROJECT_DIR / "docs" / "universe-sweep-results.json"

# ── Universe sizes ─────────────────────────────────────────────────────────────
_ALL_SIZES = [35, 80, 150, 300]  # 300 = "all ranked"; clipped to available

# ── Lazy imports (avoid startup cost, same pattern as optimize_parameters.py) ──
try:
    from wfo_engine import run_wfo
    from representative_tickers import REPRESENTATIVE_TICKERS
    from wfo_cache import cache_exists
except ImportError:
    run_wfo = None              # type: ignore[assignment]
    REPRESENTATIVE_TICKERS = []  # type: ignore[assignment]
    cache_exists = None         # type: ignore[assignment]

# ── Re-export helpers from optimize_parameters ────────────────────────────────
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


# ── Public helpers (tested independently) ─────────────────────────────────────

def _load_best_params(params_file: Path) -> dict:
    """
    Load parameters dict from best_parameters.json.

    Raises FileNotFoundError with a clear message if the file does not exist.
    """
    if not params_file.exists():
        raise FileNotFoundError(
            f"Best parameters not found at {params_file}. "
            "Run optimize_parameters.py first to generate best_parameters.json."
        )
    with params_file.open() as f:
        data = json.load(f)
    return data["parameters"]


def _load_rs_ranked_tickers(top_n: int | None = None) -> list[str]:
    """
    Load RS-ranked tickers from rs_ranked_tickers.json, filtering to cached tickers only.

    Args:
        top_n: Return only the top-N tickers (by RS rank). None = all cached.

    Raises FileNotFoundError if rs_ranked_tickers.json does not exist.
    """
    if not _RS_RANKED_FILE.exists():
        raise FileNotFoundError(
            f"RS ranked tickers not found: {_RS_RANKED_FILE}\n"
            "Run build_extended_cache.py first to generate this file."
        )
    with _RS_RANKED_FILE.open() as f:
        data = json.load(f)

    ranked = data["ranked"]  # list of {"ticker": ..., "rs_score": ...}

    # Filter to only tickers that are actually cached
    cached_tickers = [
        entry["ticker"]
        for entry in ranked
        if cache_exists(entry["ticker"])
    ]

    if top_n is not None:
        cached_tickers = cached_tickers[:top_n]

    return cached_tickers


def _build_universe(size: int) -> list[str]:
    """
    Build a ticker universe of the requested size.

    size == 35  → returns REPRESENTATIVE_TICKERS (curated; NOT RS-filtered)
    size >  35  → returns top-`size` RS-ranked cached tickers
    """
    if size == 35:
        return list(REPRESENTATIVE_TICKERS)
    return _load_rs_ranked_tickers(top_n=size)


def _universe_label(size: int) -> str:
    """Human-readable label for a universe size."""
    return f"U{_ALL_SIZES.index(size) + 1} ({size})" if size in _ALL_SIZES else f"U ({size})"


# ── Core sweep logic ──────────────────────────────────────────────────────────

async def _run_one_universe(
    size: int,
    params: dict,
    label: str,
) -> dict:
    """Run WFO for a single universe and return aggregated metrics."""
    tickers = _build_universe(size)
    # Deduplicate; SPY must be first
    spy_prefixed = ["SPY"] + [t for t in tickers if t != "SPY"]

    with _patch_constants(params):
        result = await run_wfo(
            tickers=spy_prefixed,
            setup_types=WFO_SETUP_TYPES,
            is_months=WFO_IS_MONTHS,
            oos_months=WFO_OOS_MONTHS,
            step_months=WFO_STEP_MONTHS,
            run_id=f"universe_sweep_{label}",
        )

    metrics = _aggregate_oos_metrics(result.windows)
    total_trades = metrics["total_trades"]
    trades_per_year = round(total_trades / 2.0, 1)

    score = _compute_robustness_score(
        expectancy=metrics["expectancy"],
        profit_factor=metrics["profit_factor"],
        total_trades=total_trades,
        max_drawdown_pct=metrics["max_drawdown_pct"],
    )

    return {
        "label": label,
        "n_tickers": len(tickers),
        "score": round(score, 4),
        "total_trades": total_trades,
        "trades_per_year": trades_per_year,
        "win_rate": metrics["win_rate"],
        "expectancy": metrics["expectancy"],
        "profit_factor": metrics["profit_factor"],
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "net_profit_pct": metrics["net_profit_pct"],
    }


def _print_table(results: list[dict]) -> None:
    """Print a formatted comparison table to stdout."""
    sep = "=" * 90
    hdr = f"{'Label':<14}{'Tickers':>8}{'Score':>8}{'Trades':>8}{'T/yr':>7}{'Win%':>7}{'E':>9}{'PF':>7}{'MaxDD%':>9}{'Net%':>8}"
    div = "-" * 90

    print(sep)
    print("  UNIVERSE SWEEP RESULTS")
    print(sep)
    print(hdr)
    print(div)
    for r in results:
        print(
            f"{r['label']:<14}"
            f"{r['n_tickers']:>8}"
            f"{r['score']:>8.4f}"
            f"{r['total_trades']:>8}"
            f"{r['trades_per_year']:>7.1f}"
            f"{r['win_rate']:>7.1f}"
            f"{r['expectancy']:>9.4f}"
            f"{r['profit_factor']:>7.2f}"
            f"{r['max_drawdown_pct']:>9.2f}"
            f"{r['net_profit_pct']:>8.2f}"
        )
    print(sep)


def _save_results(
    results: list[dict],
    params: dict,
    params_file: Path,
    output_file: Path = _OUTPUT_FILE,
) -> None:
    """Write results to docs/universe-sweep-results.json."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "params_source": str(params_file),
        "parameters": params,
        "rs_ranked_source": str(_RS_RANKED_FILE),
        "results": results,
    }
    output_file.write_text(json.dumps(payload, indent=2))
    print(f"\nResults saved to: {output_file}")


# ── Entry point ───────────────────────────────────────────────────────────────

async def main(sizes: list[int], params_file: Path) -> None:
    """Run universe sweep for the given sizes using params from params_file."""
    # Fail fast before any WFO work
    params = _load_best_params(params_file)
    _preload_modules()

    print(f"Loaded parameters from: {params_file}")
    print(f"Running sweep for universe sizes: {sizes}\n")

    results = []
    for size in sizes:
        # Determine label index based on _ALL_SIZES
        if size in _ALL_SIZES:
            idx = _ALL_SIZES.index(size) + 1
            label = f"U{idx} ({size})"
        else:
            label = f"U ({size})"

        print(f"Running {label} …")
        row = await _run_one_universe(size=size, params=params, label=label)
        results.append(row)
        print(f"  -> score={row['score']:.4f}, trades={row['total_trades']}")

    _print_table(results)
    _save_results(results, params=params, params_file=params_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="WFO universe sweep: compare U1-U4 universes with best parameters."
    )
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        default=_ALL_SIZES,
        metavar="N",
        help=f"Universe sizes to sweep (default: {_ALL_SIZES}). 35 = representative tickers.",
    )
    parser.add_argument(
        "--params-file",
        type=Path,
        default=_DEFAULT_PARAMS_FILE,
        metavar="PATH",
        help=f"Path to best_parameters.json (default: {_DEFAULT_PARAMS_FILE})",
    )
    args = parser.parse_args()

    # Late imports to avoid startup cost when running tests
    from wfo_engine import run_wfo                              # noqa: F811
    from representative_tickers import REPRESENTATIVE_TICKERS  # noqa: F811
    from wfo_cache import cache_exists                         # noqa: F811

    try:
        asyncio.run(main(sizes=args.sizes, params_file=args.params_file))
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
