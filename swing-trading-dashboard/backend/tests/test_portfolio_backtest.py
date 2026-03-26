import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ─────────────────────────────────────────────────────────────────────────────
# Regime Gating & Score Filtering Parity Tests
# Goal: ensure portfolio_backtest.py matches live-scanner behaviour exactly.
# ─────────────────────────────────────────────────────────────────────────────


def test_score_gate_parity_defensive_regime_rejected():
    """
    Score Gate Parity: A setup that scores ≥70 in AGGRESSIVE (full
    reg_pts = SCORE_WEIGHT_REGIME = 15) drops below 70 in DEFENSIVE (reg_pts = 0)
    and is strictly REJECTED by score_and_filter_setups(min_score=70).

    Calibration:
        RS rank 60  → ~13 pts
        RR 3.0      → ~10 pts
        vol 1.5×    → ~11 pts
        sector=Unknown → ~2 pts
        rs_vs_spy=0.08 + rs_improving + rs_near_high → 20 pts (RS quality, capped)
        ─────────────────────────────────────────────
        Non-regime subtotal ≈ 56 pts
        + AGGRESSIVE: +15 → ≈71  ✓  (≥70 accepted)
        + DEFENSIVE : + 0 → ≈56  ✓  (<70 rejected)
    """
    from scoring import compute_setup_score, score_and_filter_setups
    from constants import MIN_SETUP_SCORE, SCORE_WEIGHT_REGIME

    setup = {
        "ticker":       "TST",
        "setup_type":   "RES_BREAKOUT",
        "rr":           3.0,
        "volume_ratio": 1.5,
        "sector":       "Unknown",
        "rs_vs_spy":    0.08,
        "rs_improving": True,
        "rs_near_high": True,
    }
    rs_rank_map = {"TST": 60.0}

    # --- 1. In AGGRESSIVE, score must reach the 70 gate -----------------------
    agg_score = compute_setup_score(setup, 60.0, 0.85, "AGGRESSIVE", [])
    assert agg_score >= MIN_SETUP_SCORE, (
        f"AGGRESSIVE score {agg_score} should be ≥ {MIN_SETUP_SCORE}. "
        "Recalibrate setup if score components changed."
    )

    # --- 2. In DEFENSIVE, same setup loses all regime pts → below 70 ----------
    def_score = compute_setup_score(setup, 60.0, 0.20, "DEFENSIVE", [])
    assert def_score < MIN_SETUP_SCORE, (
        f"DEFENSIVE score {def_score} should be < {MIN_SETUP_SCORE}. "
        f"Expected SCORE_WEIGHT_REGIME={SCORE_WEIGHT_REGIME} pts to be absent in DEFENSIVE."
    )
    # The gap between regimes must be at least SCORE_WEIGHT_REGIME points
    assert (agg_score - def_score) >= SCORE_WEIGHT_REGIME, (
        f"Score gap {agg_score - def_score} should be ≥ SCORE_WEIGHT_REGIME={SCORE_WEIGHT_REGIME}. "
        "Regime component may not be zeroed out correctly in DEFENSIVE."
    )

    # --- 3. score_and_filter_setups must REJECT the setup in DEFENSIVE --------
    result_def = score_and_filter_setups(
        [dict(setup)], rs_rank_map,
        {"regime": "DEFENSIVE", "regime_score": 0.20},
        [], min_score=MIN_SETUP_SCORE,
    )
    assert len(result_def) == 0, (
        f"Expected 0 setups after DEFENSIVE score gate, got {len(result_def)}. "
        "Logic leakage: DEFENSIVE signal slipped through the min_score=70 filter."
    )

    # --- 4. Same setup ACCEPTED in AGGRESSIVE (no regression) -----------------
    result_agg = score_and_filter_setups(
        [dict(setup)], rs_rank_map,
        {"regime": "AGGRESSIVE", "regime_score": 0.85},
        [], min_score=MIN_SETUP_SCORE,
    )
    assert len(result_agg) == 1, (
        f"Expected 1 setup accepted in AGGRESSIVE, got {len(result_agg)}."
    )
    assert result_agg[0]["setup_score"] == agg_score


def test_defensive_regime_no_day_skip_vcp_excluded(monkeypatch):
    """
    Defensive Regime Behavior: during a DEFENSIVE regime portfolio_backtest must
    NOT hard-skip the entire day. It should still call _detect_signals_for_date
    for all free tickers, but VCP must be excluded from _setup_types_today.

    Two sub-scenarios:
      A. VCP-only config in DEFENSIVE → _setup_types_today is empty →
         `continue` fires (correct guard) → _detect_signals_for_date NOT called.
      B. VCP + other types in DEFENSIVE → _setup_types_today is non-empty →
         day proceeds → _detect_signals_for_date IS called (no hard-skip).
    """
    import asyncio
    import pandas as pd
    import numpy as np
    import portfolio_backtest as pb
    from portfolio_backtest import BacktestConfig, TickerSimState, run_portfolio_backtest_universe
    import backtest_engine as be

    # ── Build minimal synthetic price data (30 business days) ─────────────────
    dates = pd.date_range("2023-01-02", periods=30, freq="B")
    price = pd.Series(np.linspace(100, 110, 30), index=dates)
    vol   = pd.Series(np.ones(30) * 2_000_000, index=dates)
    ticker_df = pd.DataFrame({
        "Open":      price,
        "High":      price * 1.01,
        "Low":       price * 0.99,
        "Close":     price,
        "Adj Close": price,
        "Volume":    vol,
    }, index=dates)
    spy_df = pd.DataFrame({"Close": price, "Adj Close": price}, index=dates)
    flat_s = pd.Series(np.zeros(30), index=dates)

    def _make_state(ticker: str) -> TickerSimState:
        state = TickerSimState(
            ticker=ticker, ticker_df=ticker_df.copy(), spy_df=spy_df,
            adj_col="Adj Close", ticker_dates=dates,
            ema20_full=price, atr14_full=flat_s,
            sr_zones_cache=[],
            rs_ratio_s=flat_s, rs_52wh_s=flat_s,
            rs_score_s=flat_s, spy_3m_s=flat_s,
            params=None,
        )
        state.date_to_idx   = {d: i for i, d in enumerate(dates)}
        # RS rank 80% → clears the RS_RANK_MIN_PERCENTILE=0 gate
        state.rs_rank_cache = {d: 80.0 for d in dates}
        # All bars liquid
        state.liquidity_ok  = pd.Series(True, index=dates)
        return state

    async def fake_prepare(self, shared_spy_df=None):
        return _make_state(self.ticker)

    monkeypatch.setattr(be.BacktestEngine, "prepare", fake_prepare)

    # Force all dates to DEFENSIVE regime score (0.20 < REGIME_SELECTIVE_THRESHOLD=40)
    def_score_dict = {d: 0.20 for d in dates}
    def_label_dict = {d: "DEFENSIVE" for d in dates}
    monkeypatch.setattr(
        pb, "_compute_full_regime_dicts",
        lambda *a, **kw: (def_score_dict, def_label_dict),
    )

    # ── Scenario A: VCP-only config → day must be correctly skipped ───────────
    detect_calls_a: list = []

    def spy_detect_a(ts, T_date, full_idx, setup_types, regime=""):
        detect_calls_a.append(T_date)
        return None

    monkeypatch.setattr(pb, "_detect_signals_for_date", spy_detect_a)

    config_vcp_only = BacktestConfig(
        start_date="2023-01-02", end_date="2023-02-10",
        max_positions=2, setup_types=["VCP"],
    )
    asyncio.run(run_portfolio_backtest_universe(["T1"], config_vcp_only))

    assert len(detect_calls_a) == 0, (
        f"VCP-only DEFENSIVE config: _detect_signals_for_date should NOT be called "
        f"(_setup_types_today is empty → correct skip). Got {len(detect_calls_a)} calls."
    )

    # ── Scenario B: VCP + other types → day must NOT be skipped ──────────────
    detect_calls_b: list = []

    def spy_detect_b(ts, T_date, full_idx, setup_types, regime=""):
        detect_calls_b.append({"date": T_date, "regime": regime})
        return None

    monkeypatch.setattr(pb, "_detect_signals_for_date", spy_detect_b)

    config_mixed = BacktestConfig(
        start_date="2023-01-02", end_date="2023-02-10",
        max_positions=2,
        setup_types=["VCP", "PULLBACK", "BASE", "RES_BREAKOUT"],
    )
    asyncio.run(run_portfolio_backtest_universe(["T1", "T2"], config_mixed))

    # Must have fired for at least one ticker on at least one day
    assert len(detect_calls_b) > 0, (
        "DEFENSIVE days with non-VCP setup types were hard-skipped — "
        "_detect_signals_for_date was never called. Logic leakage: the backtest "
        "is incorrectly using a blanket `continue` to skip DEFENSIVE days entirely."
    )

    # Every recorded call must have passed the DEFENSIVE regime label through
    for call in detect_calls_b:
        assert call["regime"] == "DEFENSIVE", (
            f"Expected regime='DEFENSIVE' in spy call, got {call['regime']!r}. "
            "The regime label is not being forwarded to signal detection correctly."
        )


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
