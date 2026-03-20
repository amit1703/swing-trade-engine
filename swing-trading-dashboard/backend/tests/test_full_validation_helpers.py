"""Tests for full system validation helpers — defined inline and tested here."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from constants import ATR_ENTRY_EARLY_THRESHOLD, ATR_ENTRY_EXTENDED_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# Helper: _setup_meta captures atr + entry (Task 1 contract)
# ─────────────────────────────────────────────────────────────────────────────

def test_setup_meta_captures_atr_and_entry():
    """_meta_keys must include 'atr' and 'entry' so trade dicts carry them."""
    import inspect
    from backtest_engine import BacktestEngine
    src = inspect.getsource(BacktestEngine.run)
    assert '"atr"' in src or "'atr'" in src, \
        "'atr' not found in BacktestEngine.run — add it to _meta_keys"
    assert '"entry"' in src or "'entry'" in src, \
        "'entry' not found in BacktestEngine.run — add it to _meta_keys"


# ─────────────────────────────────────────────────────────────────────────────
# Helper: _entry_quality
# ─────────────────────────────────────────────────────────────────────────────

def _entry_quality(trade: dict) -> str:
    """Classify entry quality: EARLY / OPTIMAL / EXTENDED / UNKNOWN."""
    meta      = trade.get("setup_meta", {})
    atr       = meta.get("atr", 0)
    sig_entry = meta.get("entry", None)
    fill      = trade.get("entry_price")
    if atr is None or atr <= 0 or sig_entry is None or fill is None:
        return "UNKNOWN"
    dist = (fill - sig_entry) / atr
    if dist < ATR_ENTRY_EARLY_THRESHOLD:
        return "EARLY"
    elif dist < ATR_ENTRY_EXTENDED_THRESHOLD:
        return "OPTIMAL"
    else:
        return "EXTENDED"


def test_entry_quality_early():
    t = {"entry_price": 100.05, "setup_meta": {"atr": 1.0, "entry": 100.0}}
    assert _entry_quality(t) == "EARLY"   # 0.05 ATR < 0.1


def test_entry_quality_optimal():
    t = {"entry_price": 100.3, "setup_meta": {"atr": 1.0, "entry": 100.0}}
    assert _entry_quality(t) == "OPTIMAL"  # 0.3 ATR in [0.1, 0.5)


def test_entry_quality_extended():
    t = {"entry_price": 101.0, "setup_meta": {"atr": 1.0, "entry": 100.0}}
    assert _entry_quality(t) == "EXTENDED"  # 1.0 ATR >= 0.5


def test_entry_quality_unknown_no_atr():
    t = {"entry_price": 100.0, "setup_meta": {"entry": 100.0}}
    assert _entry_quality(t) == "UNKNOWN"


def test_entry_quality_threshold_boundary_early_optimal():
    """Just above EARLY threshold goes to OPTIMAL."""
    t = {"entry_price": 100.0 + (ATR_ENTRY_EARLY_THRESHOLD + 0.01) * 1.0,
         "setup_meta": {"atr": 1.0, "entry": 100.0}}
    assert _entry_quality(t) == "OPTIMAL"


# ─────────────────────────────────────────────────────────────────────────────
# Helper: _stats
# ─────────────────────────────────────────────────────────────────────────────

def _stats(trades: list) -> dict:
    if not trades:
        return {"n": 0, "win_rate": 0.0, "avg_r": 0.0, "expectancy": 0.0,
                "profit_factor": 0.0, "max_dd": 0.0, "avg_hold": 0.0}
    # Sort by exit_date for deterministic, chronologically-correct drawdown
    sorted_t = sorted(trades, key=lambda t: t.get("exit_date", t.get("entry_date", "")))
    rr   = [t["rr_achieved"] for t in sorted_t]
    wins = [r for r in rr if r > 0]
    loss = [r for r in rr if r <= 0]
    pnl  = [t.get("portfolio_pnl_pct", 0.0) for t in sorted_t]
    hold = [t.get("holding_days", 0) for t in sorted_t]

    win_rate   = len(wins) / len(rr) * 100
    avg_r      = float(np.mean(rr))
    avg_win    = float(np.mean(wins)) if wins else 0.0
    avg_loss   = float(np.mean(loss)) if loss else 0.0
    expectancy = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss

    gp = sum(p for p in pnl if p > 0)
    gl = abs(sum(p for p in pnl if p < 0))
    pf = (gp / gl) if gl > 0 else float("inf")

    eq, peak, max_dd = 1.0, 1.0, 0.0
    for p in pnl:
        eq *= (1 + p / 100)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    return {
        "n":             len(trades),
        "win_rate":      win_rate,
        "avg_r":         avg_r,
        "expectancy":    expectancy,
        "profit_factor": pf,
        "max_dd":        max_dd,
        "avg_hold":      float(np.mean(hold)),
    }


def test_stats_empty():
    s = _stats([])
    assert s["n"] == 0
    assert s["win_rate"] == 0.0


def test_stats_two_trades():
    trades = [
        {"rr_achieved": 2.0,  "portfolio_pnl_pct": 0.4,  "holding_days": 10,
         "exit_date": "2020-02-01"},
        {"rr_achieved": -1.0, "portfolio_pnl_pct": -0.2, "holding_days": 5,
         "exit_date": "2020-03-01"},
    ]
    s = _stats(trades)
    assert s["n"] == 2
    assert abs(s["win_rate"] - 50.0) < 0.01
    assert abs(s["avg_r"] - 0.5) < 0.001
    assert s["max_dd"] > 0   # drawdown occurred after the loss


def test_stats_all_wins():
    trades = [
        {"rr_achieved": 1.5, "portfolio_pnl_pct": 0.3, "holding_days": 8,
         "exit_date": "2020-01-10"},
        {"rr_achieved": 2.0, "portfolio_pnl_pct": 0.4, "holding_days": 12,
         "exit_date": "2020-01-20"},
    ]
    s = _stats(trades)
    assert s["win_rate"] == 100.0
    assert s["profit_factor"] == float("inf")
    assert s["max_dd"] == 0.0


def test_stats_drawdown_is_chronological():
    """Drawdown should reflect temporal order (sorted by exit_date)."""
    # Win first, then loss — drawdown occurs
    trades = [
        {"rr_achieved": 1.0,  "portfolio_pnl_pct": 0.2,  "holding_days": 5,
         "exit_date": "2020-01-10"},
        {"rr_achieved": -1.0, "portfolio_pnl_pct": -0.5, "holding_days": 5,
         "exit_date": "2020-02-10"},
    ]
    s = _stats(trades)
    assert s["max_dd"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Helper: _capital_curve
# ─────────────────────────────────────────────────────────────────────────────

def _capital_curve(trades: list, start_year: int = 2020, end_year: int = 2024) -> dict:
    """Year-end equity starting at 1.0. Sorted by exit_date (P&L realized at exit)."""
    if not trades:
        return {y: 1.0 for y in range(start_year, end_year + 1)}
    sorted_trades = sorted(trades, key=lambda t: t.get("exit_date", t.get("entry_date", "")))
    equity, idx, n = 1.0, 0, len(sorted_trades)
    result = {}
    for year in range(start_year, end_year + 1):
        cutoff = f"{year}-12-31"
        while idx < n and sorted_trades[idx].get("exit_date", sorted_trades[idx].get("entry_date", "")) <= cutoff:
            equity *= (1 + sorted_trades[idx].get("portfolio_pnl_pct", 0.0) / 100)
            idx += 1
        result[year] = round(equity, 4)
    return result


def test_capital_curve_empty():
    curve = _capital_curve([])
    assert all(v == 1.0 for v in curve.values())
    assert set(curve.keys()) == {2020, 2021, 2022, 2023, 2024}


def test_capital_curve_grows():
    trades = [
        {"exit_date": "2020-06-01", "portfolio_pnl_pct": 0.5},
        {"exit_date": "2021-03-01", "portfolio_pnl_pct": 0.5},
    ]
    curve = _capital_curve(trades)
    assert curve[2020] > 1.0
    assert curve[2021] > curve[2020]
    assert curve[2021] == curve[2022]   # no trades after 2021


def test_capital_curve_loss_reduces_equity():
    trades = [{"exit_date": "2020-06-01", "portfolio_pnl_pct": -1.0}]
    curve = _capital_curve(trades)
    assert curve[2020] < 1.0


def test_capital_curve_uses_exit_date_not_entry_date():
    """Trade entered in Dec 2020 but exited in Jan 2021 must NOT count in 2020."""
    trades = [
        {"entry_date": "2020-12-15", "exit_date": "2021-01-10", "portfolio_pnl_pct": 0.5},
    ]
    curve = _capital_curve(trades)
    assert curve[2020] == 1.0        # not yet exited in 2020
    assert curve[2021] > 1.0        # exited in 2021
