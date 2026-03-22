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
