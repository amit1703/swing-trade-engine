"""Tests for analytics.py — pure diagnostics functions."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_trade(ticker="AAPL", setup_type="VCP", entry=100.0, stop=95.0,
                exit_price=None, regime_score=75):
    """Build a minimal trade dict matching the DB shape."""
    return {
        "ticker":       ticker,
        "setup_type":   setup_type,
        "entry_price":  entry,
        "stop_loss":    stop,
        "close_price":  exit_price,
        "status":       "closed" if exit_price is not None else "active",
        "regime_score": regime_score,
    }


# ─── compute_live_diagnostics ─────────────────────────────────────────────

def test_empty_trades_returns_zero_stats():
    from analytics import compute_live_diagnostics
    result = compute_live_diagnostics([])
    assert result["total_trades"] == 0
    assert result["win_rate"] == 0.0
    assert result["profit_factor"] is None
    assert result["equity_curve_R"] == []


def test_single_win_correct_R():
    """entry=100, stop=90, exit=120 → R = (120-100)/(100-90) = 2.0"""
    from analytics import compute_live_diagnostics
    t = _make_trade(entry=100.0, stop=90.0, exit_price=120.0)
    r = compute_live_diagnostics([t])
    assert r["total_trades"] == 1
    assert r["win_rate"] == 1.0
    assert abs(r["avg_R"] - 2.0) < 0.001
    assert r["profit_factor"] is None   # no losing trades → None
    assert r["equity_curve_R"] == [2.0]


def test_single_loss_correct_R():
    """entry=100, stop=90, exit=85 → R = (85-100)/10 = -1.5"""
    from analytics import compute_live_diagnostics
    t = _make_trade(entry=100.0, stop=90.0, exit_price=85.0)
    r = compute_live_diagnostics([t])
    assert r["win_rate"] == 0.0
    assert abs(r["avg_R"] - (-1.5)) < 0.001


def test_profit_factor_two_trades():
    """1 win R=2.0, 1 loss R=-1.0 → PF = 2.0/1.0 = 2.0"""
    from analytics import compute_live_diagnostics
    win  = _make_trade(entry=100.0, stop=90.0, exit_price=120.0)  # R=2.0
    loss = _make_trade(entry=100.0, stop=90.0, exit_price=90.0)   # R=-1.0
    r = compute_live_diagnostics([win, loss])
    assert abs(r["profit_factor"] - 2.0) < 0.001


def test_expectancy_is_weighted_avg_R():
    """expectancy = win_rate * avg_win_R + (1-win_rate) * avg_loss_R"""
    from analytics import compute_live_diagnostics
    win  = _make_trade(entry=100.0, stop=90.0, exit_price=120.0)  # R=+2.0
    loss = _make_trade(entry=100.0, stop=90.0, exit_price=90.0)   # R=-1.0
    r = compute_live_diagnostics([win, loss])
    # win_rate=0.5, avg_win=2.0, avg_loss=-1.0 → expectancy = 0.5*2.0 + 0.5*(-1.0) = 0.5
    assert abs(r["expectancy"] - 0.5) < 0.001


def test_open_trades_excluded():
    """Open trades (status != 'closed') must not affect diagnostics."""
    from analytics import compute_live_diagnostics
    closed = _make_trade(entry=100.0, stop=90.0, exit_price=120.0)
    open_t = _make_trade(entry=100.0, stop=90.0, exit_price=None)
    r = compute_live_diagnostics([closed, open_t])
    assert r["total_trades"] == 1


def test_max_drawdown_sequence():
    from analytics import compute_live_diagnostics
    trades = [
        _make_trade(entry=100.0, stop=90.0, exit_price=120.0),   # R=+2
        _make_trade(entry=100.0, stop=90.0, exit_price=90.0),    # R=-1
        _make_trade(entry=100.0, stop=90.0, exit_price=130.0),   # R=+3
        _make_trade(entry=100.0, stop=90.0, exit_price=80.0),    # R=-2
    ]
    r = compute_live_diagnostics(trades)
    # cumulative: [2, 1, 4, 2] — peak=4, trough=2 → max_dd = -2
    assert r["max_drawdown"] <= 0
    assert abs(r["max_drawdown"] - (-2.0)) < 0.001
    assert len(r["equity_curve_R"]) == 4


# ─── compute_setup_breakdown ─────────────────────────────────────────────

def test_setup_breakdown_groups_by_type():
    from analytics import compute_setup_breakdown
    trades = [
        _make_trade("AAPL", "VCP",      entry=100, stop=90, exit_price=120),
        _make_trade("NVDA", "VCP",      entry=100, stop=90, exit_price=90),
        _make_trade("TSLA", "PULLBACK", entry=100, stop=95, exit_price=115),
    ]
    result = compute_setup_breakdown(trades)
    assert "VCP" in result
    assert "PULLBACK" in result
    assert result["VCP"]["total_trades"] == 2
    assert result["PULLBACK"]["total_trades"] == 1


def test_low_sample_flag_below_threshold():
    from analytics import compute_setup_breakdown
    trades = [_make_trade("AAPL", "VCP", entry=100, stop=90, exit_price=120)
              for _ in range(5)]
    result = compute_setup_breakdown(trades)
    assert result["VCP"]["low_sample"] is True


def test_low_sample_flag_above_threshold():
    from analytics import compute_setup_breakdown
    trades = [_make_trade("AAPL", "VCP", entry=100, stop=90, exit_price=120)
              for _ in range(20)]
    result = compute_setup_breakdown(trades)
    assert result["VCP"]["low_sample"] is False


# ─── compute_ticker_distribution ─────────────────────────────────────────

def test_ticker_distribution_sorted_by_contribution():
    from analytics import compute_ticker_distribution
    trades = [
        _make_trade("NVDA", "VCP", entry=100, stop=90, exit_price=150),  # R=5
        _make_trade("AAPL", "VCP", entry=100, stop=90, exit_price=110),  # R=1
        _make_trade("TSLA", "VCP", entry=100, stop=90, exit_price=90),   # R=-1
    ]
    result = compute_ticker_distribution(trades)
    assert result[0]["ticker"] == "NVDA"


def test_ticker_distribution_fields():
    from analytics import compute_ticker_distribution
    t = _make_trade("AAPL", "VCP", entry=100, stop=90, exit_price=120)
    result = compute_ticker_distribution([t])
    row = result[0]
    assert "ticker" in row
    assert "trade_count" in row
    assert "total_pnl" in row
    assert "pct_contribution" in row


# ─── compute_regime_performance ───────────────────────────────────────────

def test_regime_performance_buckets():
    from analytics import compute_regime_performance
    trades = [
        _make_trade(regime_score=80, exit_price=120.0),  # AGGRESSIVE
        _make_trade(regime_score=55, exit_price=90.0),   # SELECTIVE
        _make_trade(regime_score=30, exit_price=110.0),  # DEFENSIVE
    ]
    result = compute_regime_performance(trades)
    assert "AGGRESSIVE" in result
    assert "SELECTIVE" in result
    assert "DEFENSIVE" in result
    assert result["AGGRESSIVE"]["trades"] == 1
    assert result["SELECTIVE"]["trades"] == 1


def test_regime_performance_missing_score_goes_to_unknown():
    from analytics import compute_regime_performance
    t = {**_make_trade(), "regime_score": None}
    result = compute_regime_performance([t])
    assert "UNKNOWN" in result
