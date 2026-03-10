import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _run(coro):
    return asyncio.run(coro)


def test_run_backtest_universe_is_importable():
    from backtest_engine import run_backtest_universe
    assert callable(run_backtest_universe)


def test_run_backtest_universe_empty_tickers_returns_empty():
    from backtest_engine import run_backtest_universe
    result = _run(run_backtest_universe([], "2023-01-01", "2023-03-01"))
    assert result == []


def test_run_backtest_universe_returns_list_of_dicts(monkeypatch):
    """With a mock engine that returns 1 trade, universe returns 1 dict."""
    from backtest_engine import run_backtest_universe, TradeRecord, BacktestSummary
    import backtest_engine as be

    fake_trade = TradeRecord(
        ticker="FAKE",
        setup_type="VCP",
        signal_date="2023-01-10",
        entry_date="2023-01-11",
        entry_price=100.0,
        initial_stop=95.0,
        take_profit=115.0,
        exit_date="2023-01-20",
        exit_price=112.0,
        exit_reason="TARGET",
        holding_days=9,
    )
    fake_summary = BacktestSummary(
        run_id="test", ticker="FAKE", setup_type="VCP",
        start_date="2023-01-01", end_date="2023-03-01",
        total_trades=1, win_count=1, loss_count=0,
        win_rate=100.0, avg_rr=1.4, profit_factor=999.0,
        max_drawdown_pct=0.0, avg_holding_days=9.0,
        gross_profit=12.0, gross_loss=0.0, trades=[fake_trade],
    )

    async def fake_run(self):
        return fake_summary

    monkeypatch.setattr(be.BacktestEngine, "run", fake_run)
    result = _run(run_backtest_universe(["FAKE"], "2023-01-01", "2023-03-01"))

    assert len(result) == 1
    trade = result[0]
    assert trade["ticker"] == "FAKE"
    assert trade["setup_type"] == "VCP"
    assert "initial_stop" in trade
    assert "exit_price" in trade


def test_run_backtest_universe_passes_trail_override(monkeypatch):
    """trail_mult_override is forwarded to each BacktestEngine instance."""
    from backtest_engine import run_backtest_universe, compute_metrics
    import backtest_engine as be

    seen_overrides = []

    async def fake_run(self):
        seen_overrides.append(self.trail_mult_override)
        return compute_metrics("X", "VCP", "2023-01-01", "2023-03-01", [])

    monkeypatch.setattr(be.BacktestEngine, "run", fake_run)
    _run(run_backtest_universe(["FAKE1", "FAKE2"], "2023-01-01", "2023-03-01",
                               trail_mult_override=4.162))
    assert all(o == 4.162 for o in seen_overrides)
    assert len(seen_overrides) == 2


def test_run_backtest_universe_calls_progress_cb(monkeypatch):
    """progress_cb is called once per ticker with (done, total)."""
    from backtest_engine import run_backtest_universe, compute_metrics
    import backtest_engine as be

    progress_log = []

    async def fake_run(self):
        return compute_metrics("X", "VCP", "2023-01-01", "2023-03-01", [])

    monkeypatch.setattr(be.BacktestEngine, "run", fake_run)

    async def cb(done, total):
        progress_log.append((done, total))

    _run(run_backtest_universe(["A", "B", "C"], "2023-01-01", "2023-03-01",
                               progress_cb=cb))
    assert len(progress_log) == 3
    dones = [p[0] for p in progress_log]
    assert sorted(dones) == [1, 2, 3]
    assert all(p[1] == 3 for p in progress_log)
