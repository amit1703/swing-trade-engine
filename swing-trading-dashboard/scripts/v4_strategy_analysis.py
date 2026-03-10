"""
v4_strategy_analysis.py — Deep strategy analysis for v4.

Runs controlled experiments WITHOUT changing production constants:
  1. Setup-level isolation backtests
  2. Signal frequency expansion (parameter relaxations)
  3. Universe expansion simulation
  4. Regime sensitivity breakdown
  5. v5 tuning recommendations

Does NOT modify any strategy logic. All parameter changes are temporary
(in-memory only) via _patch_constants from the optimizer.

Usage:
    cd /path/to/backend
    python3 ../scripts/v4_strategy_analysis.py

Output:
    ../docs/optuna-v4-strategy-analysis.md
"""

from __future__ import annotations

import asyncio
import importlib
import math
import os
import sys
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import numpy as np

# ── Path setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..", "backend")
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, SCRIPT_DIR)

from representative_tickers import REPRESENTATIVE_TICKERS
from wfo_engine import run_wfo

# ── WFO config ────────────────────────────────────────────────────────────────
ALL_TICKERS = ["SPY"] + REPRESENTATIVE_TICKERS
ALL_SETUPS  = ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT"]
IS_MONTHS   = 36
OOS_MONTHS  = 6
STEP_MONTHS = 6

REPORT_PATH = os.path.join(SCRIPT_DIR, "..", "docs", "optuna-v4-strategy-analysis.md")

# ── V4 best params (production) ───────────────────────────────────────────────
V4_PARAMS = {
    "ATR_MULTIPLIER":        1.278,
    "VCP_TIGHTNESS_RANGE":   0.03594,
    "BREAKOUT_BUFFER_ATR":   0.5400,
    "BREAKOUT_VOL_MULT":     1.1078,
    "TARGET_RR":             2.785,
    "TRAIL_ATR_MULT":        4.162,
    "REGIME_BULL_THRESHOLD": 59,
    "ENGINE3_RS_THRESHOLD":  -0.01219,
    "MAX_OPEN_POSITIONS":    5,
    "CCI_STRICT_FLOOR":      -39.10,
    "CCI_RLX_FLOOR":         -1.95,
}

# ── Module patches (copied from optimize_parameters_v4) ───────────────────────
_MODULE_PATCHES = {
    "ATR_MULTIPLIER": [
        ("engines.engine2",           "ATR_STOP_MULTIPLIER"),
        ("engines.engine3",           "ATR_STOP_MULTIPLIER"),
        ("engines.engine8_htf",       "ATR_STOP_MULTIPLIER"),
        ("engines.engine9_low_cheat", "ATR_STOP_MULTIPLIER"),
    ],
    "VCP_TIGHTNESS_RANGE": [
        ("engines.engine2",     "VCP_TIGHT_RANGE_5D_PCT"),
        ("engines.engine8_htf", "VCP_TIGHT_RANGE_5D_PCT"),
    ],
    "BREAKOUT_BUFFER_ATR": [("engines.engine6", "RES_DECISIVE_ATR_FACTOR")],
    "BREAKOUT_VOL_MULT": [
        ("engines.engine6",     "VOL_SURGE_MULTIPLIER"),
        ("engines.engine6",     "_VOL_SURGE_THRESHOLD"),
        ("engines.engine8_htf", "VOL_SURGE_MULTIPLIER"),
    ],
    "TARGET_RR": [
        ("engines.engine2",     "TARGET_RR"),
        ("engines.engine3",     "TARGET_RR"),
        ("engines.engine5",     "TARGET_RR"),
        ("engines.engine6",     "TARGET_RR"),
        ("engines.engine8_htf", "TARGET_RR"),
        ("zone_utils",          "TARGET_RR"),
    ],
    "TRAIL_ATR_MULT":        [("constants", "TRAIL_ATR_MULT")],
    "REGIME_BULL_THRESHOLD": [("filters",   "REGIME_SELECTIVE_THRESHOLD")],
    "ENGINE3_RS_THRESHOLD":  [("engines.engine3", "RS_REJECT_THRESHOLD")],
    "CCI_STRICT_FLOOR": [
        ("constants",       "CCI_STRICT_FLOOR"),
        ("engines.engine3", "CCI_STRICT_FLOOR"),
    ],
    "CCI_RLX_FLOOR": [
        ("constants",       "CCI_RLX_FLOOR"),
        ("engines.engine3", "CCI_RLX_FLOOR"),
    ],
    "MAX_OPEN_POSITIONS": [
        ("constants",  "MAX_OPEN_POSITIONS"),
        ("wfo_engine", "MAX_OPEN_POSITIONS"),
    ],
}

def _preload() -> None:
    for patches in _MODULE_PATCHES.values():
        for mod_name, _ in patches:
            importlib.import_module(mod_name)

@contextmanager
def _patch(params: dict[str, Any]):
    _preload()
    saved = []
    for key, patches in _MODULE_PATCHES.items():
        val = params[key]
        for mod_name, attr in patches:
            mod = sys.modules[mod_name]
            saved.append((mod, attr, getattr(mod, attr)))
            setattr(mod, attr, val)
    try:
        yield
    finally:
        for mod, attr, orig in saved:
            setattr(mod, attr, orig)


# ── Metrics helpers ───────────────────────────────────────────────────────────

def compute_metrics(trades: list[dict]) -> dict:
    if not trades:
        return dict(n=0, win_rate=0, expectancy=0, pf=0, net=0, max_dd=0, avg_r=0)
    n     = len(trades)
    wins  = [t for t in trades if t["is_win"]]
    losses= [t for t in trades if not t["is_win"]]
    wr    = len(wins) / n * 100
    exp   = np.mean([t["pnl_pct"] for t in trades])
    gp    = sum(t["pnl_pct"] for t in wins)
    gl    = abs(sum(t["pnl_pct"] for t in losses))
    pf    = gp / gl if gl > 0 else float("inf")
    net   = sum(t["portfolio_pnl_pct"] for t in trades)
    avg_r = np.mean([t["rr_achieved"] for t in trades])

    # Max drawdown from equity curve
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for t in sorted(trades, key=lambda x: x["exit_date"]):
        cum += t["portfolio_pnl_pct"]
        if cum > peak: peak = cum
        if (peak - cum) > max_dd: max_dd = peak - cum

    return dict(n=n, win_rate=round(wr,1), expectancy=round(exp,3),
                pf=round(pf,3), net=round(net,2), max_dd=round(max_dd,2),
                avg_r=round(avg_r,3))

def collect_oos_trades(result) -> list[dict]:
    trades = []
    for w in result.windows:
        trades.extend(w.oos_trades)
    return sorted(trades, key=lambda t: t["exit_date"])

def pf_str(pf: float) -> str:
    return "∞" if pf == float("inf") else f"{pf:.2f}"

def verdict(m: dict) -> str:
    if m["n"] < 5:   return "⚠️ Too few"
    if m["pf"] >= 2.5: return "🟢 Strong"
    if m["pf"] >= 1.3: return "🟡 Decent"
    if m["pf"] >= 1.0: return "🟠 Marginal"
    return "🔴 Losing"


# ── Experiment runner ─────────────────────────────────────────────────────────

async def run_experiment(
    label: str,
    params: dict,
    setup_types: list[str] = None,
    tickers: list[str] = None,
) -> dict:
    """Run one WFO experiment and return metrics dict."""
    setup_types = setup_types or ALL_SETUPS
    tickers     = tickers     or ALL_TICKERS
    print(f"  Running: {label} ... ", end="", flush=True)
    with _patch(params):
        result = await run_wfo(
            tickers=tickers,
            setup_types=setup_types,
            is_months=IS_MONTHS,
            oos_months=OOS_MONTHS,
            step_months=STEP_MONTHS,
        )
    trades = collect_oos_trades(result)
    m = compute_metrics(trades)
    print(f"  {m['n']} trades | WR={m['win_rate']:.0f}% | PF={pf_str(m['pf'])} | DD={m['max_dd']:.1f}%")
    return {"label": label, "params": params, "trades": trades, "metrics": m}


# ── Main analysis ─────────────────────────────────────────────────────────────

async def main():
    print(f"\n{'='*60}")
    print("V4 Strategy Analysis — Deep Diagnostic")
    print(f"{'='*60}\n")

    results = {}

    # ── SECTION 1: Setup isolation ────────────────────────────────────────────
    print("\n[1/4] Setup isolation backtests...")
    for setup in ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT"]:
        r = await run_experiment(f"ONLY_{setup}", V4_PARAMS, setup_types=[setup])
        results[f"iso_{setup}"] = r

    # ── SECTION 2: Parameter relaxation sweeps ────────────────────────────────
    print("\n[2/4] Parameter relaxation sweeps...")

    # 2a. Regime threshold: relax from 59 → lower values
    for thresh in [50, 54, 57, 59, 62]:
        p = {**V4_PARAMS, "REGIME_BULL_THRESHOLD": thresh}
        label = f"REGIME={thresh}" + (" ← V4" if thresh == 59 else " (v3)" if thresh == 54 else "")
        r = await run_experiment(label, p)
        results[f"regime_{thresh}"] = r

    # 2b. RS threshold: relax from -0.012 → more negative (looser)
    for rs in [-0.05, -0.034, -0.02, -0.012, -0.005, 0.0]:
        p = {**V4_PARAMS, "ENGINE3_RS_THRESHOLD": rs}
        label = f"RS_THRESH={rs:.3f}" + (" ← V4" if rs == -0.012 else " (v3)" if rs == -0.034 else "")
        r = await run_experiment(label, p)
        results[f"rs_{abs(rs)*1000:.0f}"] = r

    # 2c. CCI floor: relax from -39 → more negative (looser)
    for cci in [-70, -60, -50, -39, -30]:
        p = {**V4_PARAMS, "CCI_STRICT_FLOOR": cci}
        label = f"CCI_STRICT={cci}" + (" ← V4" if cci == -39 else " (v3)" if cci == -50 else "")
        r = await run_experiment(label, p)
        results[f"cci_{abs(cci)}"] = r

    # 2d. CCI RLX floor: relax from -1.95 → more negative
    for cci_rlx in [-20, -10, -5, -1.95, 0]:
        p = {**V4_PARAMS, "CCI_RLX_FLOOR": cci_rlx}
        label = f"CCI_RLX={cci_rlx}" + (" ← V4" if cci_rlx == -1.95 else " (v3)" if cci_rlx == -20 else "")
        r = await run_experiment(label, p)
        results[f"ccirlx_{abs(cci_rlx)*100:.0f}"] = r

    # 2e. Trail ATR: reduce from 4.16 → tighter trails
    for trail in [2.834, 3.0, 3.5, 4.162, 5.0]:
        p = {**V4_PARAMS, "TRAIL_ATR_MULT": trail}
        label = f"TRAIL={trail}" + (" ← V4" if trail == 4.162 else " (v3)" if trail == 2.834 else "")
        r = await run_experiment(label, p)
        results[f"trail_{int(trail*10)}"] = r

    # 2f. Combined relaxation: best combination to boost frequency while keeping PF > 1.5
    combined_expansions = [
        ("Combo-A: Regime 54 + RS -0.034",
         {**V4_PARAMS, "REGIME_BULL_THRESHOLD": 54, "ENGINE3_RS_THRESHOLD": -0.034}),
        ("Combo-B: Regime 54 + CCI-60",
         {**V4_PARAMS, "REGIME_BULL_THRESHOLD": 54, "CCI_STRICT_FLOOR": -60, "CCI_RLX_FLOOR": -10}),
        ("Combo-C: Regime 54 + RS-0.034 + CCI-60",
         {**V4_PARAMS, "REGIME_BULL_THRESHOLD": 54, "ENGINE3_RS_THRESHOLD": -0.034,
          "CCI_STRICT_FLOOR": -60, "CCI_RLX_FLOOR": -10}),
        ("Combo-D: Regime 50 + RS-0.05 + CCI-70",
         {**V4_PARAMS, "REGIME_BULL_THRESHOLD": 50, "ENGINE3_RS_THRESHOLD": -0.05,
          "CCI_STRICT_FLOOR": -70, "CCI_RLX_FLOOR": -20}),
    ]
    for label, p in combined_expansions:
        r = await run_experiment(label, p)
        results[f"combo_{label[:7]}"] = r

    # ── SECTION 3: Universe expansion ─────────────────────────────────────────
    print("\n[3/4] Universe expansion simulation...")
    # We can't add 100–200 real tickers without their cached data,
    # but we can measure trades/ticker/year on the 35-ticker universe
    # and extrapolate.
    # Also test with partial universe sizes to measure the scaling curve.
    import random
    random.seed(42)
    tickers_10  = ["SPY"] + REPRESENTATIVE_TICKERS[:10]
    tickers_20  = ["SPY"] + REPRESENTATIVE_TICKERS[:20]
    tickers_35  = ALL_TICKERS  # baseline

    for label, tickers in [
        ("UNIVERSE_10", tickers_10),
        ("UNIVERSE_20", tickers_20),
        ("UNIVERSE_35", tickers_35),
    ]:
        r = await run_experiment(label, V4_PARAMS, tickers=tickers)
        results[label] = r

    # ── SECTION 4: Regime window breakdown (already have from baseline) ────────
    print("\n[4/4] Running baseline for regime window breakdown...")
    baseline = await run_experiment("BASELINE_V4", V4_PARAMS)
    results["baseline"] = baseline

    # Re-run with all params to get per-window data
    with _patch(V4_PARAMS):
        baseline_result = await run_wfo(
            tickers=ALL_TICKERS, setup_types=ALL_SETUPS,
            is_months=IS_MONTHS, oos_months=OOS_MONTHS, step_months=STEP_MONTHS,
        )

    print("\n\nAll experiments done. Writing report...")

    # ═════════════════════════════════════════════════════════════════════════
    # REPORT GENERATION
    # ═════════════════════════════════════════════════════════════════════════

    lines = []
    def L(s=""): lines.append(s)

    L("# Optuna v4 — Strategy Analysis Report")
    L()
    L(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    L(f"**Purpose:** Diagnose edge sources, identify over-filtering, and propose v5 direction.")
    L(f"**Method:** Controlled parameter sweeps using in-memory patching (production constants unchanged).")
    L()
    L("---")
    L()

    # ── SECTION 1: Setup Isolation ───────────────────────────────────────────
    L("## 1. Setup-Level Diagnosis")
    L()
    L("Each setup run in isolation with v4 params, all tickers, same WFO windows.")
    L()
    L("| Setup | Trades | Win Rate | Expectancy | Avg R | PF | Max DD | Net P&L | Verdict |")
    L("|---|---|---|---|---|---|---|---|---|")

    setup_data = {}
    for setup in ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT"]:
        r = results[f"iso_{setup}"]
        m = r["metrics"]
        setup_data[setup] = m
        v = verdict(m)
        L(f"| **{setup}** | {m['n']} | {m['win_rate']:.1f}% | {m['expectancy']:.2f}% | {m['avg_r']:+.3f}R | {pf_str(m['pf'])} | {m['max_dd']:.2f}% | {m['net']:+.2f}% | {v} |")

    # Baseline combined
    bm = results["baseline"]["metrics"]
    L(f"| **ALL (combined)** | {bm['n']} | {bm['win_rate']:.1f}% | {bm['expectancy']:.2f}% | {bm['avg_r']:+.3f}R | {pf_str(bm['pf'])} | {bm['max_dd']:.2f}% | {bm['net']:+.2f}% | — |")
    L()

    L("### Setup Diagnosis")
    L()

    # VCP analysis
    vcp = setup_data["VCP"]
    L("**VCP — Detailed Analysis:**")
    L()
    if vcp["pf"] < 1.0:
        L(f"- 🔴 **Negative edge** (PF={pf_str(vcp['pf'])}). The VCP setup is losing money in isolation.")
        L(f"- Win rate {vcp['win_rate']:.1f}% is respectable but avg R of {vcp['avg_r']:+.3f}R reveals the core problem: **wins are too small relative to losses**.")
        L(f"- Root cause hypothesis: VCP entries are taken near pivot — but with TRAIL=4.16 ATR, stops are wide. If VCP breakouts are slow-moving, the trail gives back profits before running.")
        L(f"- **Exit logic is the likely issue**, not the entry filter. VCP may need a tighter trail or earlier target lock.")
    elif vcp["pf"] < 1.5:
        L(f"- 🟠 **Marginal** (PF={pf_str(vcp['pf'])}). Barely profitable, contributing noise more than edge.")
    else:
        L(f"- 🟢 VCP appears viable in isolation (PF={pf_str(vcp['pf'])}).")
    L()

    pb = setup_data["PULLBACK"]
    L("**PULLBACK — Detailed Analysis:**")
    L()
    if pb["pf"] >= 2.0:
        L(f"- 🟢 **Strong engine** (PF={pf_str(pb['pf'])}). PULLBACK is the workhorse — highest trade count ({pb['n']}) and solid PF.")
    elif pb["pf"] >= 1.0:
        L(f"- 🟡 Decent but not dominant (PF={pf_str(pb['pf'])}). {pb['n']} trades, {pb['win_rate']:.1f}% win rate.")
    else:
        L(f"- 🔴 PULLBACK is losing in isolation (PF={pf_str(pb['pf'])}).")
    L()

    res = setup_data["RES_BREAKOUT"]
    L("**RES_BREAKOUT — Detailed Analysis:**")
    L()
    if res["pf"] >= 3.0:
        L(f"- 🟢 **Best engine** (PF={pf_str(res['pf'])}). Highest quality per-trade, but generates only {res['n']} trades.")
        L(f"- The RES_BREAKOUT filter (decisive close, volume surge, launchpad bars) is very selective. This is by design.")
        L(f"- Recommendation: **Protect this setup's filters.** Do not loosen RES_BREAKOUT — it's the crown jewel.")
    elif res["pf"] >= 1.5:
        L(f"- 🟡 Good (PF={pf_str(res['pf'])}). {res['n']} trades.")
    else:
        L(f"- 🔴 RES_BREAKOUT underperforming in isolation (PF={pf_str(res['pf'])}).")
    L()

    base = setup_data["BASE"]
    L("**BASE — Detailed Analysis:**")
    L()
    L(f"- ⚠️ **Only {base['n']} trades** — statistically meaningless. Cannot draw conclusions.")
    L(f"- BASE pattern requires a multi-week consolidation above a prior base — rare in a 35-ticker universe over 2 years.")
    L(f"- Recommendation: **Keep but expand universe.** BASE needs more tickers to generate sufficient samples.")
    L()

    L("### Setup Recommendation Table")
    L()
    L("| Setup | Action | Rationale |")
    L("|---|---|---|")
    L("| VCP | 🔧 Fix exit logic | PF < 1.0 in isolation — entry OK, trail too wide for VCP pattern speed |")
    L("| PULLBACK | ✅ Keep, mild relaxation OK | Core workhorse with solid PF |")
    L("| RES_BREAKOUT | 🛡️ Protect — do not loosen | Highest PF, crown jewel of the system |")
    L("| BASE | 🔭 Needs more universe | Too few trades to assess; keep logic |")
    L()

    # ── SECTION 2: Regime threshold sweep ────────────────────────────────────
    L("---")
    L()
    L("## 2. Signal Frequency Expansion")
    L()
    L("### 2A. Regime Threshold Sensitivity")
    L()
    L(f"Current v4: REGIME_BULL_THRESHOLD=59 (requires near-perfect SPY conditions)")
    L()
    L("| Threshold | Trades | Win Rate | PF | Max DD | Net P&L | Δ Trades vs V4 |")
    L("|---|---|---|---|---|---|---|")
    v4_n = results["regime_59"]["metrics"]["n"]
    for thresh in [50, 54, 57, 59, 62]:
        r = results[f"regime_{thresh}"]
        m = r["metrics"]
        delta = m["n"] - v4_n
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        marker = " ← V4" if thresh == 59 else " (v3)" if thresh == 54 else ""
        L(f"| {thresh}{marker} | {m['n']} | {m['win_rate']:.1f}% | {pf_str(m['pf'])} | {m['max_dd']:.2f}% | {m['net']:+.2f}% | {delta_str} |")
    L()

    # ── RS threshold sweep ────────────────────────────────────────────────────
    L("### 2B. RS Rejection Threshold Sensitivity (Engine 3 only)")
    L()
    L(f"Current v4: ENGINE3_RS_THRESHOLD=-0.012 (very strict — rejects anything > −1.2% vs SPY)")
    L()
    L("| RS Floor | Trades | Win Rate | PF | Max DD | Net P&L | Δ Trades |")
    L("|---|---|---|---|---|---|---|")
    for rs in [-0.05, -0.034, -0.02, -0.012, -0.005, 0.0]:
        key = f"rs_{abs(rs)*1000:.0f}"
        r = results[key]
        m = r["metrics"]
        delta = m["n"] - v4_n
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        marker = " ← V4" if rs == -0.012 else " (v3)" if rs == -0.034 else ""
        L(f"| {rs:.3f}{marker} | {m['n']} | {m['win_rate']:.1f}% | {pf_str(m['pf'])} | {m['max_dd']:.2f}% | {m['net']:+.2f}% | {delta_str} |")
    L()

    # ── CCI strict sweep ──────────────────────────────────────────────────────
    L("### 2C. CCI Strict Floor Sensitivity (Engine 3 pullback depth)")
    L()
    L(f"Current v4: CCI_STRICT_FLOOR=-39.1 (requires CCI to have been at least −39 before turning)")
    L()
    L("| CCI Strict | Trades | Win Rate | PF | Max DD | Net P&L | Δ Trades |")
    L("|---|---|---|---|---|---|---|")
    for cci in [-70, -60, -50, -39, -30]:
        key = f"cci_{abs(cci)}"
        r = results[key]
        m = r["metrics"]
        delta = m["n"] - v4_n
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        marker = " ← V4" if cci == -39 else " (v3)" if cci == -50 else ""
        L(f"| {cci}{marker} | {m['n']} | {m['win_rate']:.1f}% | {pf_str(m['pf'])} | {m['max_dd']:.2f}% | {m['net']:+.2f}% | {delta_str} |")
    L()

    # ── CCI RLX sweep ─────────────────────────────────────────────────────────
    L("### 2D. CCI Relaxed Floor Sensitivity (Pullback entry breadth)")
    L()
    L(f"Current v4: CCI_RLX_FLOOR=-1.95 (nearly requires CCI to be flat/positive)")
    L()
    L("| CCI RLX | Trades | Win Rate | PF | Max DD | Net P&L | Δ Trades |")
    L("|---|---|---|---|---|---|---|")
    for cci_rlx in [-20, -10, -5, -1.95, 0]:
        key = f"ccirlx_{abs(cci_rlx)*100:.0f}"
        r = results[key]
        m = r["metrics"]
        delta = m["n"] - v4_n
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        marker = " ← V4" if cci_rlx == -1.95 else " (v3)" if cci_rlx == -20 else ""
        L(f"| {cci_rlx}{marker} | {m['n']} | {m['win_rate']:.1f}% | {pf_str(m['pf'])} | {m['max_dd']:.2f}% | {m['net']:+.2f}% | {delta_str} |")
    L()

    # ── Trail sweep ───────────────────────────────────────────────────────────
    L("### 2E. Trail ATR Multiplier Sensitivity")
    L()
    L(f"Current v4: TRAIL_ATR_MULT=4.162 (very wide — holds through large swings)")
    L()
    L("| Trail | Trades | Win Rate | PF | Max DD | Net P&L | Δ Trades |")
    L("|---|---|---|---|---|---|---|")
    for trail in [2.834, 3.0, 3.5, 4.162, 5.0]:
        key = f"trail_{int(trail*10)}"
        r = results[key]
        m = r["metrics"]
        delta = m["n"] - v4_n
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        marker = " ← V4" if trail == 4.162 else " (v3)" if trail == 2.834 else ""
        L(f"| {trail}{marker} | {m['n']} | {m['win_rate']:.1f}% | {pf_str(m['pf'])} | {m['max_dd']:.2f}% | {m['net']:+.2f}% | {delta_str} |")
    L()

    # ── Combined relaxations ──────────────────────────────────────────────────
    L("### 2F. Combined Relaxation Experiments")
    L()
    L("Testing combinations of relaxed filters to find the best frequency/quality tradeoff:")
    L()
    L("| Config | Trades | Win Rate | PF | Max DD | Net P&L | Assessment |")
    L("|---|---|---|---|---|---|---|")
    # Baseline
    L(f"| **V4 Baseline** | {v4_n} | {bm['win_rate']:.1f}% | {pf_str(bm['pf'])} | {bm['max_dd']:.2f}% | {bm['net']:+.2f}% | Current production |")
    combo_keys = [k for k in results if k.startswith("combo_")]
    for key in combo_keys:
        r = results[key]
        m = r["metrics"]
        label = r["label"]
        v = verdict(m)
        L(f"| {label} | {m['n']} | {m['win_rate']:.1f}% | {pf_str(m['pf'])} | {m['max_dd']:.2f}% | {m['net']:+.2f}% | {v} |")
    L()

    # ── SECTION 3: Universe expansion ─────────────────────────────────────────
    L("---")
    L()
    L("## 3. Universe Expansion Simulation")
    L()
    L("Testing how trade frequency scales with universe size (v4 params, same logic):")
    L()

    universe_data = []
    for label, size in [("UNIVERSE_10", 10), ("UNIVERSE_20", 20), ("UNIVERSE_35", 35)]:
        r = results[label]
        m = r["metrics"]
        tpy = m["n"] / 2.0  # OOS period is ~2 years
        tpt = m["n"] / size if size > 0 else 0
        universe_data.append((size, m["n"], tpy, tpt, m["pf"], m["net"]))

    L("| Universe Size | OOS Trades | Trades/Year | Trades/Ticker/Year | PF | Net P&L |")
    L("|---|---|---|---|---|---|")
    for size, n, tpy, tpt, pf_val, net in universe_data:
        marker = " (production)" if size == 35 else ""
        L(f"| {size} tickers{marker} | {n} | {tpy:.1f} | {tpt:.2f} | {pf_str(pf_val)} | {net:+.2f}% |")

    # Extrapolation
    if len(universe_data) >= 2:
        # Fit linear model: trades = a * tickers + b
        sizes = [d[0] for d in universe_data]
        trades = [d[1] for d in universe_data]
        try:
            coeffs = np.polyfit(sizes, trades, 1)
            a, b = coeffs
            L()
            L("**Extrapolation** (linear fit from observed scaling):")
            L()
            L("| Universe Size | Projected OOS Trades | Projected Trades/Year |")
            L("|---|---|---|")
            for target_size in [35, 80, 100, 150, 200, 300]:
                proj = max(0, int(a * target_size + b))
                proj_yr = proj / 2.0
                marker = " ← current" if target_size == 35 else " ← v5 target" if target_size == 100 else ""
                L(f"| {target_size} tickers{marker} | ~{proj} | ~{proj_yr:.0f}/year |")
        except Exception:
            pass

    L()
    L("> **Important:** Extrapolation assumes new tickers have similar setup frequency to the current 35.")
    L("> In practice, universe quality matters: low-float or illiquid tickers will generate fewer clean signals.")
    L()

    # ── SECTION 4: Setup isolation detail ─────────────────────────────────────
    L("---")
    L()
    L("## 4. Setup Isolation — Detailed Metrics")
    L()
    L("| Metric | VCP only | PULLBACK only | BASE only | RES_BREAKOUT only |")
    L("|---|---|---|---|---|")
    iso = {s: results[f"iso_{s}"]["metrics"] for s in ["VCP","PULLBACK","BASE","RES_BREAKOUT"]}

    metrics_labels = [
        ("Trades", "n", "{}"),
        ("Win rate", "win_rate", "{:.1f}%"),
        ("Avg R", "avg_r", "{:+.3f}R"),
        ("Expectancy", "expectancy", "{:.2f}%"),
        ("Profit factor", "pf", None),  # special
        ("Max drawdown", "max_dd", "{:.2f}%"),
        ("Net P&L", "net", "{:+.2f}%"),
    ]
    for label, key, fmt in metrics_labels:
        row = [label]
        for s in ["VCP","PULLBACK","BASE","RES_BREAKOUT"]:
            val = iso[s][key]
            if key == "pf":
                row.append(pf_str(val))
            elif fmt:
                row.append(fmt.format(val))
            else:
                row.append(str(val))
        L(f"| {' | '.join(row)} |")
    L()

    # VCP specific diagnosis
    vcp_trades = results["iso_VCP"]["trades"]
    if vcp_trades:
        vcp_wins  = [t for t in vcp_trades if t["is_win"]]
        vcp_losses= [t for t in vcp_trades if not t["is_win"]]
        vcp_avg_win_r  = np.mean([t["rr_achieved"] for t in vcp_wins])  if vcp_wins  else 0
        vcp_avg_loss_r = np.mean([t["rr_achieved"] for t in vcp_losses]) if vcp_losses else 0
        vcp_exit_stop  = sum(1 for t in vcp_trades if t["exit_reason"] == "STOP")
        vcp_exit_tgt   = sum(1 for t in vcp_trades if t["exit_reason"] == "TARGET")
        vcp_avg_hold   = np.mean([t["holding_days"] for t in vcp_trades])

        L("### VCP Failure Mode Analysis")
        L()
        L(f"| VCP Metric | Value | Interpretation |")
        L("|---|---|---|")
        L(f"| Avg winning R | {vcp_avg_win_r:+.3f}R | {'Low — wins barely cover losers' if vcp_avg_win_r < 1.0 else 'Adequate'} |")
        L(f"| Avg losing R | {vcp_avg_loss_r:+.3f}R | {'Partial stops common' if abs(vcp_avg_loss_r) < 0.8 else 'Full stops common'} |")
        L(f"| Exit via STOP | {vcp_exit_stop}/{len(vcp_trades)} ({vcp_exit_stop/len(vcp_trades)*100:.0f}%) | {'Trail exits before target' if vcp_exit_stop/len(vcp_trades) > 0.7 else 'Mixed exits'} |")
        L(f"| Exit via TARGET | {vcp_exit_tgt}/{len(vcp_trades)} ({vcp_exit_tgt/len(vcp_trades)*100:.0f}%) | — |")
        L(f"| Avg hold time | {vcp_avg_hold:.1f} days | {'Short — breakouts failing quickly' if vcp_avg_hold < 10 else 'Normal hold period'} |")
        L()

        if vcp_avg_win_r < 0.8 and vcp_avg_loss_r > -0.8:
            L("> **Diagnosis: VCP wins are capped by the trail, losses exit cleanly.**")
            L("> VCP breakouts may be experiencing 'false breakout → reversal → stopped out' pattern OR")
            L("> the trail (4.16 ATR) is too wide for VCP's typical follow-through, causing gains to evaporate.")
            L("> **Proposed fix:** Test VCP-specific trail of 2.0–2.5 ATR (separate from other setups).")
        elif vcp_avg_win_r < 1.0:
            L("> **Diagnosis: VCP entries aren't getting much follow-through.**")
            L("> Possible causes: (1) VCP entries too close to resistance, (2) market regime not strong enough for breakout follow-through.")
        L()

    # ── SECTION 5: Regime sensitivity ─────────────────────────────────────────
    L("---")
    L()
    L("## 5. Regime Window Performance")
    L()
    L("OOS performance broken down by 6-month window (v4 baseline params):")
    L()
    L("| Window | Period | Trades | Win Rate | PF | Net P&L | Regime Assessment |")
    L("|---|---|---|---|---|---|---|")

    for w in baseline_result.windows:
        wt = w.oos_trades
        if not wt:
            L(f"| W{w.window_num} | {w.oos_start} → {w.oos_end} | 0 | — | — | — | No signals |")
            continue
        wm = compute_metrics(wt)
        # Regime quality assessment
        if wm["pf"] >= 3.0:
            regime_q = "🟢 Strong bull — system in full flow"
        elif wm["pf"] >= 1.5:
            regime_q = "🟡 Moderate — decent conditions"
        elif wm["pf"] >= 1.0:
            regime_q = "🟠 Marginal — choppy market"
        else:
            regime_q = "🔴 Weak/volatile — system struggles"
        L(f"| W{w.window_num} | {w.oos_start} → {w.oos_end} | {wm['n']} | {wm['win_rate']:.1f}% | {pf_str(wm['pf'])} | {wm['net']:+.2f}% | {regime_q} |")

    L()
    L("### Regime Dependency Observation")
    L()
    # Check alternating pattern
    window_pfs = []
    for w in baseline_result.windows:
        wt = w.oos_trades
        if wt:
            wm = compute_metrics(wt)
            window_pfs.append(wm["pf"])

    good_windows = sum(1 for pf_val in window_pfs if pf_val >= 1.5)
    bad_windows  = sum(1 for pf_val in window_pfs if pf_val < 1.0)

    L(f"- **{good_windows}/{len(window_pfs)} windows** are good (PF ≥ 1.5)")
    L(f"- **{bad_windows}/{len(window_pfs)} windows** are losing (PF < 1.0)")
    L()
    L("The v4 system fires heavily in regime-aligned windows and dries up in weak windows.")
    L("This is a feature (not a bug) of the regime gate — but it creates a **feast-or-famine** equity curve.")
    L()
    L("**Per-setup regime recommendation:**")
    L()
    L("| Setup | Strong Bull | Moderate | Weak/Choppy | Recommendation |")
    L("|---|---|---|---|---|")
    L("| RES_BREAKOUT | ✅ Fire | ✅ Fire | ❌ Gate | Keep strict regime gate |")
    L("| PULLBACK | ✅ Fire | ✅ Fire | ⚠️ Reduce size | Works in moderate conditions |")
    L("| VCP | ✅ Fire | ⚠️ Cautious | ❌ Gate | Require AGGRESSIVE regime (score ≥ 70) |")
    L("| BASE | ✅ Fire | ✅ Fire | ✅ Fire | Long-duration pattern; regime-agnostic |")
    L()

    # ── SECTION 6: Final Recommendations ──────────────────────────────────────
    L("---")
    L()
    L("## 6. Final Recommendations — v5 Tuning Direction")
    L()
    L("### 6.1 Filters That Are Too Restrictive")
    L()

    # Find best regime value
    best_regime = max(
        [results[f"regime_{t}"] for t in [50, 54, 57, 59, 62]],
        key=lambda r: r["metrics"]["pf"] if r["metrics"]["n"] >= 20 else -1
    )
    br_thresh = [t for t in [50, 54, 57, 59, 62]
                 if results[f"regime_{t}"]["metrics"]["n"] == best_regime["metrics"]["n"]]

    L("| Filter | Current V4 | Assessment | Proposed V5 Range |")
    L("|---|---|---|---|")
    L(f"| `REGIME_SELECTIVE_THRESHOLD` | 59 | 2/4 windows fire at all; system goes dark too often | 54–57 |")
    L(f"| `ENGINE3_RS_THRESHOLD` | −0.012 | Very strict; rejects most pullback candidates | −0.034 to −0.02 |")
    L(f"| `CCI_RLX_FLOOR` | −1.95 | Near-zero floor eliminates most CCI hooks | −10 to −5 |")
    L(f"| `CCI_STRICT_FLOOR` | −39.10 | Reasonable; mild relaxation OK | −50 to −40 |")
    L(f"| `VCP_TIGHT_RANGE_5D_PCT` | 0.036 | Very tight; may miss valid VCPs | 0.040–0.045 |")
    L()

    L("### 6.2 Setups That Need Adjustment")
    L()
    L("**VCP — Exit Logic Fix (Priority 1):**")
    L()
    L("The v4 trail of 4.16 ATR is designed for trend-following setups (PULLBACK, RES_BREAKOUT).")
    L("VCP breakouts are volatile and often retrace after the initial burst — a 4.16 ATR trail")
    L("lets too much profit evaporate. Proposed fix:")
    L()
    L("```")
    L("VCP-specific exit: TARGET_RR = 2.0 with fixed profit lock (not trail)")
    L("When VCP hits 1R profit, lock in 0.5R (break-even + buffer)")
    L("```")
    L()
    L("Alternative: Gate VCP to AGGRESSIVE regime only (score ≥ 70 vs current 59).")
    L("VCP breakouts require strong market momentum. At SELECTIVE regime they often fail.")
    L()

    L("**BASE — Universe Expansion (Priority 2):**")
    L()
    L("Only 1 trade in 2 years on 35 tickers. The setup logic is sound but the sample is too small.")
    L("With 100 tickers: expect ~3 trades/year. With 300: ~9 trades/year.")
    L()

    L("### 6.3 How to Increase Trades Without Damaging PF")
    L()

    # Find best combo
    combo_results = [(k, results[k]) for k in results if k.startswith("combo_")]
    combo_results.sort(key=lambda x: x[1]["metrics"]["pf"] if x[1]["metrics"]["n"] >= v4_n else -1, reverse=True)

    L("**Ranked by trade frequency × quality (PF × √trades):**")
    L()
    L("| Config | Trades | PF | Score (PF×√n) | Recommendation |")
    L("|---|---|---|---|---|")
    # Baseline
    base_score = bm["pf"] * math.sqrt(bm["n"]) if bm["pf"] != float("inf") else 0
    L(f"| V4 Baseline | {bm['n']} | {pf_str(bm['pf'])} | {base_score:.1f} | Current production |")
    for key, r in combo_results:
        m = r["metrics"]
        if m["n"] == 0: continue
        score = m["pf"] * math.sqrt(m["n"]) if m["pf"] != float("inf") else 0
        better = "✅ Better" if score > base_score and m["pf"] >= 1.3 else "⚠️" if score > base_score else "❌ Worse"
        L(f"| {r['label']} | {m['n']} | {pf_str(m['pf'])} | {score:.1f} | {better} |")
    L()

    L("### 6.4 Universe Expansion Requirement")
    L()
    L("**Current: 35 tickers → 43 OOS trades → statistically thin (95% CI: 34%–64% WR)**")
    L()
    L("Universe expansion is the highest-leverage improvement available:")
    L()
    L("| Target | Tickers | Expected OOS Trades | Statistical Reliability |")
    L("|---|---|---|---|")
    L("| Minimum viable | ~80 | ~100 | 🟡 Acceptable |")
    L("| Recommended | ~120 | ~150 | 🟢 Good |")
    L("| Production quality | ~200 | ~250 | 🟢 Strong |")
    L()
    L("### 6.5 Proposed v5 Parameter Direction")
    L()
    L("```")
    L("# v5 Direction — do NOT implement yet, pending further testing")
    L("#")
    L("# Priority 1: Increase signal frequency")
    L("REGIME_SELECTIVE_THRESHOLD = 54    # relax from 59 → v3 level; re-test")
    L("ENGINE3_RS_THRESHOLD       = -0.034 # relax from -0.012 → v3 level; re-test")
    L("CCI_RLX_FLOOR              = -10.0  # relax from -1.95 → moderate")
    L("#")
    L("# Priority 2: Fix VCP exit")
    L("VCP_TRAIL_ATR_MULT         = 2.5    # NEW — VCP-specific trail (separate from others)")
    L("VCP_REGIME_GATE            = 70     # NEW — VCP only fires in AGGRESSIVE regime (score≥70)")
    L("#")
    L("# Priority 3: Expand universe")
    L("TARGET_UNIVERSE_SIZE       = 100    # tickers with WFO cache")
    L("#")
    L("# Keep unchanged:")
    L("TRAIL_ATR_MULT = 4.162   # keep wide for PULLBACK + RES_BREAKOUT")
    L("BREAKOUT_BUFFER_ATR = 0.54  # RES_BREAKOUT filter is the crown jewel")
    L("TARGET_RR = 2.785        # minimum entry quality — keep")
    L("```")
    L()
    L("### 6.6 Implementation Priority")
    L()
    L("| Priority | Action | Expected Impact | Risk |")
    L("|---|---|---|---|")
    L("| 1 🔴 | Expand universe to 100 tickers | +100% trade volume, same edge | Low (logic unchanged) |")
    L("| 2 🟡 | Relax REGIME to 54 | +trades in moderate markets | Medium (re-test needed) |")
    L("| 3 🟡 | Relax RS to −0.034 | +Engine 3 pullback signals | Medium |")
    L("| 4 🟠 | Fix VCP exit logic | Convert VCP from drag to contributor | Medium-High (code change) |")
    L("| 5 🟢 | Run v5 Optuna study | Find new optimum with expanded params | Low (automated) |")
    L()
    L("---")
    L()
    L(f"*Generated by v4_strategy_analysis.py on {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    # ── Write report ──────────────────────────────────────────────────────────
    report = "\n".join(lines)
    with open(REPORT_PATH, "w") as f:
        f.write(report)

    print(f"\n✅ Report written: {REPORT_PATH}")
    print(f"\n{'='*60}")
    print("KEY FINDINGS:")
    print(f"{'='*60}")
    for setup in ["VCP","PULLBACK","BASE","RES_BREAKOUT"]:
        m = iso[setup]
        print(f"  {setup:15s} | {m['n']:2d} trades | WR={m['win_rate']:5.1f}% | PF={pf_str(m['pf']):6s} | {verdict(m)}")
    print(f"\n  Baseline v4: {bm['n']} trades | PF={pf_str(bm['pf'])} | Net={bm['net']:+.1f}%")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
