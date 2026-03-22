import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_backtest_config_defaults():
    from portfolio_backtest import BacktestConfig
    cfg = BacktestConfig()
    assert cfg.start_date == "2017-01-01"
    assert cfg.end_date == "2024-12-31"
    assert cfg.max_positions == 4
    assert cfg.ticker_count is None
    assert cfg.min_score == 0.0
    assert "PULLBACK" in cfg.setup_types
    assert "VCP" not in cfg.setup_types
    for st in ["BASE", "RES_BREAKOUT", "HTF", "LCE"]:
        assert st in cfg.setup_types


def test_ticker_sim_state_default_values():
    """Mutable fields have correct defaults on fresh construction."""
    from portfolio_backtest import TickerSimState
    import pandas as pd
    ts = TickerSimState(
        ticker="TEST",
        ticker_df=pd.DataFrame(),
        spy_df=pd.DataFrame(),
        adj_col="Close",
        ticker_dates=pd.DatetimeIndex([]),
        ema20_full=pd.Series(dtype=float),
        atr14_full=pd.Series(dtype=float),
        sr_zones_cache=[],
        rs_ratio_s=pd.Series(dtype=float),
        rs_52wh_s=pd.Series(dtype=float),
        rs_score_s=pd.Series(dtype=float),
        spy_3m_s=pd.Series(dtype=float),
        params=None,
    )
    assert ts.is_in_trade is False
    assert ts.last_close_date is None


def test_run_portfolio_backtest_universe_empty():
    """Empty ticker list returns empty list immediately."""
    import asyncio
    from portfolio_backtest import run_portfolio_backtest_universe, BacktestConfig
    result = asyncio.run(run_portfolio_backtest_universe([], BacktestConfig()))
    assert result == []


def test_backtest_engine_has_prepare_method():
    from backtest_engine import BacktestEngine
    engine = BacktestEngine("AAPL", "2023-01-01", "2023-03-01")
    assert hasattr(engine, "prepare")
    assert callable(engine.prepare)


def test_portfolio_cap_never_exceeded(monkeypatch):
    """
    With max_positions=2 and prepare() returning a TickerSimState that always
    fires a signal, never more than 2 positions are open at any time.
    """
    import asyncio
    import pandas as pd
    import numpy as np
    from portfolio_backtest import (
        BacktestConfig, TickerSimState, run_portfolio_backtest_universe
    )
    import backtest_engine as be

    # Build a minimal TickerSimState with synthetic price data
    dates = pd.date_range("2023-01-02", periods=50, freq="B")
    price = pd.Series(np.linspace(100, 110, 50), index=dates)
    vol   = pd.Series(np.ones(50) * 1_000_000, index=dates)
    df    = pd.DataFrame({
        "Open":      price,
        "High":      price * 1.01,
        "Low":       price * 0.99,
        "Close":     price,
        "Adj Close": price,
        "Volume":    vol,
    }, index=dates)
    spy_dates  = dates
    spy_price  = pd.Series(np.linspace(400, 410, 50), index=spy_dates)
    spy_df     = pd.DataFrame({"Close": spy_price, "Adj Close": spy_price}, index=spy_dates)
    flat_s     = pd.Series(np.zeros(50), index=dates)

    def _make_state(ticker):
        return TickerSimState(
            ticker=ticker, ticker_df=df.copy(), spy_df=spy_df,
            adj_col="Adj Close", ticker_dates=dates,
            ema20_full=price, atr14_full=flat_s,
            sr_zones_cache=[],
            rs_ratio_s=flat_s, rs_52wh_s=flat_s,
            rs_score_s=flat_s, spy_3m_s=flat_s,
            params=None,
        )

    # Monkeypatch prepare() to return our synthetic state
    tickers = [f"T{i}" for i in range(10)]

    async def fake_prepare(self, shared_spy_df=None):
        return _make_state(self.ticker)

    monkeypatch.setattr(be.BacktestEngine, "prepare", fake_prepare)

    # Monkeypatch _detect_signals_for_date to always return a PULLBACK signal
    import portfolio_backtest as pb

    def fake_detect(ts, T_date, full_idx, setup_types):
        if full_idx < 1:
            return None
        return {
            "setup_type": "PULLBACK",
            "stop_loss":  float(ts.ticker_df["Close"].iloc[full_idx]) * 0.95,
            "take_profit": float(ts.ticker_df["Close"].iloc[full_idx]) * 1.15,
            "_raw_score": 5.0,
        }

    monkeypatch.setattr(pb, "_detect_signals_for_date", fake_detect)

    config = BacktestConfig(
        start_date="2023-01-02", end_date="2023-03-31",
        max_positions=2, setup_types=["PULLBACK"],
    )
    # Monkeypatch compute_regime_label_series to always return AGGRESSIVE
    import filters
    mock_series = pd.Series(
        ["AGGRESSIVE"] * 50,
        index=spy_dates,
    )
    monkeypatch.setattr(filters, "compute_regime_label_series",
                        lambda df: mock_series)

    trades = asyncio.run(run_portfolio_backtest_universe(tickers, config))

    # If cap works: at most 2 positions opened simultaneously.
    # Note: tickers can cycle multiple times so total trades may exceed ticker count.
    assert isinstance(trades, list)  # sanity: result is a list
    # Verify max concurrent: track open periods
    if trades:
        opens  = pd.to_datetime([t["entry_date"] for t in trades])
        exits  = pd.to_datetime([t["exit_date"]  for t in trades])
        for d in pd.date_range(config.start_date, config.end_date, freq="B"):
            concurrent = sum(1 for o, e in zip(opens, exits) if o <= d <= e)
            assert concurrent <= config.max_positions, \
                f"{d}: {concurrent} concurrent positions > cap {config.max_positions}"
