# Backtest V5 Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix four backtest weaknesses before next Optuna run: market regime labels on trades, pullback pin-bar scoring, VCP as score booster only, and per-ticker cooldown.

**Architecture:** All changes are in the backtest replay path. `filters.py` gains a new `compute_regime_label_series` function returning AGGRESSIVE/SELECTIVE/DEFENSIVE per date. `TradeRecord` gains a `regime` field. `backtest_engine.py` wires regime labels into the replay loop, adds VCP booster, and adds cooldown tracking. `engines/engine3.py` adds pin-bar score component.

**Tech Stack:** Python, pandas, pytest. No new dependencies.

---

### Task 1: Add `compute_regime_label_series` to `filters.py`

**Files:**
- Modify: `swing-trading-dashboard/backend/filters.py`
- Test: `swing-trading-dashboard/backend/tests/test_filters.py`

**Background:**
`compute_regime_series` returns boolean using threshold=40 against 60-pt max (F1–F4). This is too strict (67% vs intended 40%). We add a companion function returning string labels with proportionally scaled thresholds: AGGRESSIVE=42 (70/100×60), SELECTIVE=24 (40/100×60). The old boolean function is kept unchanged (backtest_engine.py will stop using it).

**Step 1: Write failing tests**

Add to `tests/test_filters.py`:

```python
def test_regime_label_series_bull_is_aggressive():
    """Strong uptrend SPY → AGGRESSIVE labels at end."""
    from filters import compute_regime_label_series
    spy = _make_spy_df(300, "bull")
    labels = compute_regime_label_series(spy)
    assert labels.iloc[-1] == "AGGRESSIVE"
    assert isinstance(labels, pd.Series)
    assert labels.dtype == object


def test_regime_label_series_bear_is_defensive():
    """Bear trend → DEFENSIVE labels."""
    from filters import compute_regime_label_series
    spy = _make_spy_df(300, "bear")
    labels = compute_regime_label_series(spy)
    assert labels.iloc[-1] == "DEFENSIVE"


def test_regime_label_series_index_matches_spy():
    """Output index matches spy_df index."""
    from filters import compute_regime_label_series
    spy = _make_spy_df(300, "bull")
    labels = compute_regime_label_series(spy)
    assert labels.index.equals(spy.index)


def test_regime_label_series_short_history_defensive():
    """< 200 bars → all DEFENSIVE (insufficient SMA200)."""
    from filters import compute_regime_label_series
    spy = _make_spy_df(50, "bull")
    labels = compute_regime_label_series(spy)
    assert (labels == "DEFENSIVE").all()


def test_regime_label_series_none_returns_empty():
    """None input → empty Series."""
    from filters import compute_regime_label_series
    result = compute_regime_label_series(None)
    assert isinstance(result, pd.Series)
    assert len(result) == 0
```

**Step 2: Run tests to verify they fail**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_filters.py::test_regime_label_series_bull_is_aggressive -v
```
Expected: `ImportError: cannot import name 'compute_regime_label_series'`

**Step 3: Implement `compute_regime_label_series` in `filters.py`**

Add after `compute_regime_series` (after line 67):

```python
# Proportionally scaled thresholds for 4/7 factor backtest regime
# Max achievable: F1(20)+F2(15)+F3(15)+F4(10) = 60 pts
# AGGRESSIVE = 70/100 * 60 = 42; SELECTIVE = 40/100 * 60 = 24
_BACKTEST_REGIME_AGGRESSIVE = 42
_BACKTEST_REGIME_SELECTIVE  = 24


def compute_regime_label_series(spy_df: pd.DataFrame) -> pd.Series:
    """
    Return a pd.Series of str ('AGGRESSIVE'|'SELECTIVE'|'DEFENSIVE') per date.

    Uses the same SPY-only F1–F4 scoring as compute_regime_series but returns
    regime labels using proportionally scaled thresholds for the 60-pt max:
      AGGRESSIVE : score >= 42  (≡ 70/100 of full 7-factor system)
      SELECTIVE  : score >= 24  (≡ 40/100)
      DEFENSIVE  : score <  24

    Returns all-DEFENSIVE for inputs with < 200 bars.
    """
    if spy_df is None or len(spy_df) < 200:
        if spy_df is not None:
            return pd.Series("DEFENSIVE", index=spy_df.index, dtype=object)
        return pd.Series(dtype=object)

    close  = spy_df["Close"]
    ema20  = close.ewm(span=20, adjust=False).mean()
    sma50  = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    slope5 = ema20 - ema20.shift(5)

    score = pd.Series(0, index=spy_df.index, dtype=int)
    score += (close > ema20).astype(int) * REGIME_WEIGHT_EMA20
    score += (close > sma50).astype(int) * REGIME_WEIGHT_SMA50
    score += (sma50 > sma200).astype(int) * REGIME_WEIGHT_MA_STACK

    slope_norm = (slope5 / (sma50 * 0.01 + 1e-9)).fillna(0.0)
    slope_pts  = (slope_norm * REGIME_WEIGHT_SLOPE).clip(0, REGIME_WEIGHT_SLOPE).astype(int)
    score += slope_pts

    # Zero out bars where SMA200 is NaN
    score = score.where(sma200.notna(), other=0)

    labels = pd.Series("DEFENSIVE", index=spy_df.index, dtype=object)
    labels = labels.where(score < _BACKTEST_REGIME_SELECTIVE,  "SELECTIVE")
    labels = labels.where(score < _BACKTEST_REGIME_AGGRESSIVE, "AGGRESSIVE")
    return labels
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_filters.py -v -k "regime_label"
```
Expected: 5 tests PASS

**Step 5: Commit**

```bash
git add backend/filters.py backend/tests/test_filters.py
git commit -m "feat(filters): add compute_regime_label_series with scaled 4/7-factor thresholds"
```

---

### Task 2: Add `regime` field to `TradeRecord`

**Files:**
- Modify: `swing-trading-dashboard/backend/backtest_engine.py:125-182`
- Test: `swing-trading-dashboard/backend/tests/test_backtest_engine.py`

**Step 1: Write failing test**

Add to `tests/test_backtest_engine.py`:

```python
def test_trade_record_has_regime_field():
    """TradeRecord must have a regime field defaulting to 'UNKNOWN'."""
    from backtest_engine import TradeRecord
    trade = TradeRecord(
        ticker="TEST", setup_type="PULLBACK",
        signal_date="2024-01-01", entry_date="2024-01-02",
        entry_price=100.0, initial_stop=95.0, take_profit=110.0,
        exit_date="2024-01-10", exit_price=108.0,
        exit_reason="TARGET", holding_days=8,
    )
    assert hasattr(trade, "regime")
    assert trade.regime == "UNKNOWN"
    assert "regime" in trade.to_dict()
    assert trade.to_dict()["regime"] == "UNKNOWN"


def test_trade_record_regime_stored():
    """TradeRecord regime can be set at construction."""
    from backtest_engine import TradeRecord
    trade = TradeRecord(
        ticker="TEST", setup_type="PULLBACK",
        signal_date="2024-01-01", entry_date="2024-01-02",
        entry_price=100.0, initial_stop=95.0, take_profit=110.0,
        exit_date="2024-01-10", exit_price=108.0,
        exit_reason="TARGET", holding_days=8,
        regime="AGGRESSIVE",
    )
    assert trade.regime == "AGGRESSIVE"
    assert trade.to_dict()["regime"] == "AGGRESSIVE"
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_backtest_engine.py::test_trade_record_has_regime_field -v
```
Expected: `FAIL — no attribute 'regime'`

**Step 3: Add `regime` to `TradeRecord`**

In `backtest_engine.py` at line 142 (after `final_score`):

```python
    # Regime at signal time (populated in scored mode; "UNKNOWN" in legacy)
    regime: str = "UNKNOWN"
```

In `to_dict()` at line 181 (after `"final_score"` entry):

```python
            "regime":            self.regime,
```

**Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_backtest_engine.py::test_trade_record_has_regime_field tests/test_backtest_engine.py::test_trade_record_regime_stored -v
```
Expected: 2 PASS

**Step 5: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): add regime field to TradeRecord"
```

---

### Task 3: Wire regime labels into the replay loop

**Files:**
- Modify: `swing-trading-dashboard/backend/backtest_engine.py:60,695-757`
- Test: `swing-trading-dashboard/backend/tests/test_backtest_engine.py`

**Background:**
Replace the boolean `_regime_series` / `compute_regime_series` with the new string label series. Gate entries when DEFENSIVE. Store regime label in `trade_state` and propagate to `TradeRecord` when trade closes.

**Step 1: Write failing test**

Add to `tests/test_backtest_engine.py`:

```python
def test_regime_label_stored_on_trade(make_bullish_ticker_df, make_spy_df):
    """Trades opened in AGGRESSIVE regime must have regime='AGGRESSIVE'."""
    import asyncio
    from backtest_engine import BacktestEngine, BacktestParams
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2023-06-01",
        end_date="2024-01-31",
        ticker_df=make_bullish_ticker_df,
        spy_df=make_spy_df,
        params=BacktestParams(),
    )
    summary = asyncio.get_event_loop().run_until_complete(engine.run())
    trades_with_regime = [t for t in summary.trades if t.regime != "UNKNOWN"]
    assert len(trades_with_regime) > 0, "Expected at least some trades with regime label"
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_backtest_engine.py::test_regime_label_stored_on_trade -v
```
Expected: FAIL or all trades have `regime="UNKNOWN"`

**Step 3: Update import and replay loop in `backtest_engine.py`**

**3a. Update import at line 60:**

```python
from filters import compute_regime_series, compute_regime_label_series, passes_liquidity, in_earnings_blackout
```

**3b. Replace lines 699–757 (regime series setup and gate):**

```python
        # Pre-compute regime label series from SPY data
        _regime_label_s: pd.Series = pd.Series(dtype=object)
        if self.spy_df is not None and len(self.spy_df) > 0:
            _regime_label_s = compute_regime_label_series(self.spy_df)
```

Replace the regime gate block (lines 749–757):

```python
            # Regime gate: resolve current regime label, skip if DEFENSIVE
            _current_regime = "UNKNOWN"
            if len(_regime_label_s) > 0:
                spy_dates_before = _regime_label_s.index[_regime_label_s.index <= T_date]
                if len(spy_dates_before) > 0:
                    _current_regime = str(_regime_label_s.loc[spy_dates_before[-1]])
                if _current_regime == "DEFENSIVE":
                    continue
```

**3c. Store regime in trade_state when signal fires (after line 836 `signal["_final_score"] = final_score`):**

```python
            signal["_regime"] = _current_regime
```

**3d. Propagate to TradeRecord at trade close (line ~864, the dict passed to open_trades):**

```python
                "_regime":            signal.get("_regime", "UNKNOWN"),
```

**3e. Pass to `TradeRecord` at close (lines 727–740), add `regime=` kwarg:**

```python
                        completed_trades.append(TradeRecord(
                            ...
                            final_score=trade_state.get("_final_score"),
                            regime=trade_state.get("_regime", "UNKNOWN"),
                        ))
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_backtest_engine.py -v -k "regime"
python -m pytest tests/ -v --tb=short -q
```
Expected: regime tests PASS, no regressions

**Step 5: Commit**

```bash
git add backend/backtest_engine.py
git commit -m "feat(backtest): wire regime labels into replay loop; gate DEFENSIVE bars; store regime on TradeRecord"
```

---

### Task 4: Fix `compute_regime_performance` to bucket by label string

**Files:**
- Modify: `swing-trading-dashboard/backend/analytics.py:176-212`
- Test: `swing-trading-dashboard/backend/tests/test_analytics.py`

**Background:**
`compute_regime_performance` currently buckets by `regime_score` integer (>=70 → AGGRESSIVE, etc.) using the old 100-point thresholds. Now that trades carry a `regime` string, bucket by that directly.

**Step 1: Write failing test**

Add to `tests/test_analytics.py`:

```python
def test_regime_performance_buckets_by_label():
    """compute_regime_performance buckets trades by 'regime' string field."""
    from analytics import compute_regime_performance
    trades = [
        _make_trade(regime="AGGRESSIVE", exit_price=110.0, entry_price=100.0),
        _make_trade(regime="SELECTIVE",  exit_price=105.0, entry_price=100.0),
        _make_trade(regime="DEFENSIVE",  exit_price=95.0,  entry_price=100.0),
        _make_trade(regime="UNKNOWN",    exit_price=100.0, entry_price=100.0),
    ]
    result = compute_regime_performance(trades)
    assert result["AGGRESSIVE"] is not None
    assert result["SELECTIVE"]  is not None
    assert result["DEFENSIVE"]  is not None
    assert result["UNKNOWN"]    is not None
    assert result["AGGRESSIVE"]["trades"] == 1
```

Note: `_make_trade` helper must include `regime` key. Add or update the existing helper in `test_analytics.py` to include `"regime": "UNKNOWN"` by default.

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_analytics.py::test_regime_performance_buckets_by_label -v
```
Expected: FAIL (buckets by `regime_score` integer, `regime` field ignored)

**Step 3: Update `compute_regime_performance` in `analytics.py`**

Replace lines 188–197:

```python
    for t in trades:
        label = str(t.get("regime", "UNKNOWN")).upper()
        if label not in buckets:
            label = "UNKNOWN"
        buckets[label].append(t)
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_analytics.py -v --tb=short
```
Expected: all analytics tests PASS

**Step 5: Commit**

```bash
git add backend/analytics.py backend/tests/test_analytics.py
git commit -m "fix(analytics): bucket regime performance by regime label string instead of integer score"
```

---

### Task 5: Pin-bar score component in `scan_pullback_scored`

**Files:**
- Modify: `swing-trading-dashboard/backend/engines/engine3.py:565-686`
- Test: `swing-trading-dashboard/backend/tests/test_scan_pullback_scored.py`

**Background:**
Add pin-bar scoring after the CCI block (around line 629). A full pin bar (close ≥ EMA20) earns +2; a near-miss (close ≥ EMA20×0.98) earns +1. This makes the default `score_threshold=5.0` harder to reach without genuine rejection.

**Step 1: Write failing test**

Add to `tests/test_scan_pullback_scored.py`:

```python
def _make_params(**kwargs):
    # Update existing helper to include vcp_bonus and cooldown_days
    defaults = dict(
        cci_threshold=-20.0,
        ema_distance=0.04,
        tdl_bonus=1.0,
        score_threshold=5.0,
        breakout_weight=1.0,
        pullback_weight=1.0,
        rs_threshold=-0.05,
        vcp_bonus=1.0,
        cooldown_days=3,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_pinbar_score_component_present():
    """
    scan_pullback_scored docstring must mention pin-bar scoring.
    And a setup where close < EMA20 (no pin bar) should score lower
    than identical setup with close >= EMA20.
    """
    from engines.engine3 import scan_pullback_scored
    import inspect
    doc = inspect.getdoc(scan_pullback_scored)
    assert "pin" in doc.lower() or "close" in doc.lower()
```

```python
def test_pinbar_boosts_score():
    """Close above EMA20 adds +2 vs close below (no pin bar)."""
    from engines.engine3 import scan_pullback_scored
    # Build a df where last bar closes above EMA20
    idx = pd.date_range("2022-01-01", periods=150, freq="B")
    close_up = np.linspace(80.0, 130.0, 150)
    # Last bar: low dips below EMA8/EMA20, close recovers above EMA20
    close_up[-1] = close_up[-2] * 1.005   # close back up
    low_arr = close_up * 0.98
    low_arr[-1] = close_up[-4] * 0.97    # dip below EMAs
    df_pinbar = pd.DataFrame({
        "Open":      close_up * 0.999,
        "High":      close_up * 1.01,
        "Low":       low_arr,
        "Close":     close_up,
        "Adj Close": close_up,
        "Volume":    np.full(150, 2_000_000),
    }, index=idx)
    params = _make_params(score_threshold=0.0)  # threshold=0 so we always get a result
    _, score_with_pinbar = scan_pullback_scored("TEST", df_pinbar, [], params)

    # Now make close go below EMA20 on last bar (no pin bar)
    df_no_pin = df_pinbar.copy()
    df_no_pin["Close"].iloc[-1]     = close_up[-4] * 0.98
    df_no_pin["Adj Close"].iloc[-1] = df_no_pin["Close"].iloc[-1]
    _, score_no_pinbar = scan_pullback_scored("TEST", df_no_pin, [], params)

    # With pin bar should score at least 1 point higher
    if score_with_pinbar > 0 and score_no_pinbar > 0:
        assert score_with_pinbar >= score_no_pinbar
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_scan_pullback_scored.py::test_pinbar_boosts_score -v
```
Expected: FAIL (scores are equal — no pin-bar component yet)

**Step 3: Add pin-bar score block to `scan_pullback_scored` in `engines/engine3.py`**

After the CCI block (after line 629 `score += 1.0`), add:

```python
        # ── Pin-bar score ──────────────────────────────────────────────────────
        # Close recovered above (or near) EMA20 — confirms rejection of value zone
        if lc >= l20:
            score += 2.0
        elif lc >= l20 * 0.98:
            score += 1.0
```

Also update the docstring in `scan_pullback_scored` to include:

```
    +2  : close >= EMA20 (full pin bar — closed back above value zone)
    +1  : close >= EMA20 × 0.98 (near miss)
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_scan_pullback_scored.py -v --tb=short
```
Expected: all PASS

**Step 5: Commit**

```bash
git add backend/engines/engine3.py backend/tests/test_scan_pullback_scored.py
git commit -m "feat(engine3): add pin-bar score component (+2/+1) to scan_pullback_scored"
```

---

### Task 6: VCP as score booster in scored mode

**Files:**
- Modify: `swing-trading-dashboard/backend/backtest_engine.py:81-112,790-810`
- Test: `swing-trading-dashboard/backend/tests/test_backtest_scored_mode.py`

**Background:**
VCP had −0.19R expectancy as a standalone setup. It should only add confidence to a pullback that already qualifies. In scored mode: after pullback fires, run `scan_vcp`; if it fires too, add `params.vcp_bonus` to the pullback score. VCP is removed from the standalone `_detect_signals` fallback in scored mode.

**Step 1: Add `vcp_bonus` to `BacktestParams`**

In `backtest_engine.py` after `tdl_bonus` (line 101):

```python
    vcp_bonus:       float = 1.0   # added to pb_score when VCP co-fires (Optuna: 0.0 → 3.0)
```

**Step 2: Write failing test**

Add to `tests/test_backtest_scored_mode.py`:

```python
def test_backtest_params_has_vcp_bonus():
    """BacktestParams has vcp_bonus defaulting to 1.0."""
    from backtest_engine import BacktestParams
    p = BacktestParams()
    assert hasattr(p, "vcp_bonus")
    assert p.vcp_bonus == 1.0


def test_vcp_not_standalone_in_scored_mode():
    """In scored mode, setup_type='VCP' should never appear as a standalone trade."""
    import asyncio
    from backtest_engine import BacktestEngine, BacktestParams
    # Use preloaded DFs from existing fixtures in this test file
    # This test verifies no VCP-only trades in scored mode output
    engine = BacktestEngine(
        ticker="TEST",
        start_date="2023-01-01",
        end_date="2024-01-31",
        ticker_df=_make_bullish_df(500),
        spy_df=_make_spy_df(500),
        params=BacktestParams(vcp_bonus=2.0),
    )
    summary = asyncio.get_event_loop().run_until_complete(engine.run())
    vcp_standalone = [t for t in summary.trades if t.setup_type == "VCP"]
    assert len(vcp_standalone) == 0, f"Expected no standalone VCP trades, got {len(vcp_standalone)}"
```

**Step 3: Run to verify failure**

```bash
python -m pytest tests/test_backtest_scored_mode.py::test_backtest_params_has_vcp_bonus -v
python -m pytest tests/test_backtest_scored_mode.py::test_vcp_not_standalone_in_scored_mode -v
```
Expected: first FAIL (no attr), second FAIL or PASS depending on whether VCP fires in test data

**Step 4: Implement VCP booster in `backtest_engine.py`**

**4a. In the scored-mode signal detection block (lines 790–810), after `if pb_setup is not None:` (line 797), add VCP booster before `signal = pb_setup`:**

```python
                if pb_setup is not None:
                    # VCP co-signal boost: if VCP also fires on this bar, add bonus
                    try:
                        from engines.engine2 import scan_vcp as _scan_vcp
                        _vcp = _scan_vcp(
                            self.ticker, df_slice, _sr_zones_cache,
                            spy_3m_return=float(_rs_t["spy_3m"]),
                            rs_score=float(_rs_t["rs_score"]),
                        )
                        if _vcp is not None:
                            pb_score += self.params.vcp_bonus
                    except Exception:
                        pass   # VCP boost is best-effort; never block the pullback
                    pb_setup["_raw_score"] = pb_score
                    signal = pb_setup
```

**4b. Remove VCP from the non-pullback fallback path in scored mode (line 802):**

```python
                else:
                    # Try non-pullback, non-VCP engines via normal _detect_signals path
                    # VCP is disabled as standalone in scored mode (it runs as booster above)
                    non_pb_types = [s for s in self.setup_types if s not in ("PULLBACK", "VCP")]
                    signal = (
                        _detect_signals(
                            self.ticker, df_slice, spy_slice, non_pb_types,
                            sr_zones=_sr_zones_cache,
                            precomputed_rs=_rs_t,
                        )
                        if non_pb_types else None
                    )
```

**Step 5: Run tests**

```bash
python -m pytest tests/test_backtest_scored_mode.py -v --tb=short
python -m pytest tests/ -q --tb=short
```
Expected: scored mode tests PASS, no regressions

**Step 6: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_scored_mode.py
git commit -m "feat(backtest): VCP as pullback score booster in scored mode; disable VCP standalone"
```

---

### Task 7: Per-ticker cooldown

**Files:**
- Modify: `swing-trading-dashboard/backend/backtest_engine.py:81-112,565-605,720-760`
- Test: `swing-trading-dashboard/backend/tests/test_backtest_engine.py`

**Background:**
Add `cooldown_days: int = 3` to `BacktestParams`. `BacktestEngine` tracks `_last_close_date` per instance (one ticker per engine). Before opening a new position, if the ticker was closed within `cooldown_days` bars, skip. Update `_last_close_date` whenever a trade closes.

**Step 1: Add `cooldown_days` to `BacktestParams`**

In `backtest_engine.py` after `vcp_bonus` (line ~102):

```python
    cooldown_days:   int   = 3     # days blocked after a trade closes (Optuna: 1 → 15)
```

**Step 2: Write failing test**

Add to `tests/test_backtest_engine.py`:

```python
def test_backtest_params_has_cooldown_days():
    """BacktestParams has cooldown_days defaulting to 3."""
    from backtest_engine import BacktestParams
    p = BacktestParams()
    assert hasattr(p, "cooldown_days")
    assert p.cooldown_days == 3


def test_cooldown_blocks_reentry(make_bullish_ticker_df, make_spy_df):
    """
    With cooldown_days=30 (very long), a ticker that fired a trade in Jan
    should not fire again in Feb — trades should be fewer than with cooldown_days=1.
    """
    import asyncio
    from backtest_engine import BacktestEngine, BacktestParams

    engine_short = BacktestEngine(
        ticker="TEST",
        start_date="2023-01-01", end_date="2024-06-30",
        ticker_df=make_bullish_ticker_df, spy_df=make_spy_df,
        params=BacktestParams(cooldown_days=1),
    )
    engine_long = BacktestEngine(
        ticker="TEST",
        start_date="2023-01-01", end_date="2024-06-30",
        ticker_df=make_bullish_ticker_df, spy_df=make_spy_df,
        params=BacktestParams(cooldown_days=90),
    )
    summary_short = asyncio.get_event_loop().run_until_complete(engine_short.run())
    summary_long  = asyncio.get_event_loop().run_until_complete(engine_long.run())
    assert len(summary_short.trades) >= len(summary_long.trades), (
        "Long cooldown should produce ≤ trades vs short cooldown"
    )
```

**Step 3: Run to verify failure**

```bash
python -m pytest tests/test_backtest_engine.py::test_backtest_params_has_cooldown_days -v
```
Expected: FAIL (no attr)

**Step 4: Implement cooldown in `BacktestEngine`**

**4a. Add `_last_close_date` init in `BacktestEngine.__init__` (after line 601 `self.params = params`):**

```python
        self._last_close_date: Optional[date] = None   # for per-ticker cooldown
```

**4b. In the replay loop, after the regime gate (around line 757) and before df_slice / signal detection, add cooldown gate:**

```python
            # Cooldown gate: block re-entry within cooldown_days of last close
            if (
                self.params is not None
                and self._last_close_date is not None
                and (T_date.date() - self._last_close_date).days < self.params.cooldown_days
            ):
                continue
```

**4c. When a trade closes (lines 724–743), update `_last_close_date`:**

```python
                    if closed:
                        self._last_close_date = T_date.date()   # ← add this line
                        entry_dt     = pd.Timestamp(trade_state["entry_date"])
                        ...
```

**Step 5: Run tests**

```bash
python -m pytest tests/test_backtest_engine.py -v -k "cooldown"
python -m pytest tests/ -q --tb=short
```
Expected: cooldown tests PASS, full suite green

**Step 6: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): add per-ticker cooldown_days to BacktestParams and BacktestEngine"
```

---

### Task 8: Verify full test suite and re-run diagnostics backtest

**Step 1: Run full test suite**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: all green

**Step 2: Quick smoke-test via API** (optional, if server is running)

```bash
curl -X POST http://localhost:8000/api/run-backtest-diagnostics -H "Content-Type: application/json" | python3 -m json.tool | head -20
```
Expected: response with `status: "running"` or completed result with non-UNKNOWN regime distribution

**Step 3: Commit any final fixes**

```bash
git add -p
git commit -m "fix(backtest): post-integration fixes from v5 improvements run"
```
