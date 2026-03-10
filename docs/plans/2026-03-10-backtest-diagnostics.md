# Backtest Diagnostics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a V4 strategy baseline audit to the diagnostics system — run the existing backtest engine over the full ticker universe in a background job, cache results to disk, expose via 3 new API endpoints, and add a source toggle to DiagnosticsTab.

**Architecture:** `BacktestEngine` gains a `trail_mult_override` param to enforce V4's single multiplier; a new `run_backtest_universe()` function fans out across all tickers concurrently; results are adapted to analytics.py's trade dict shape and written to a JSON cache file; the frontend DiagnosticsTab switches between live and backtest sources. `analytics.py` is reused without modification.

**Tech Stack:** Python asyncio, FastAPI BackgroundTasks, yfinance, existing `BacktestEngine`, `analytics.py` (pure, unchanged), React useState, Tailwind CSS.

---

## Context

Working directory: `swing-trading-dashboard/`

Key files:
- `backend/constants.py` — all tunable values; V4 params already here
- `backend/backtest_engine.py` — `BacktestEngine` class (line 514), `_manage_open_trade()` (line 290), `_TRAIL_ATR_BY_SETUP` dict (line 51)
- `backend/analytics.py` — 4 pure functions; accepts trade dicts with keys: `ticker`, `setup_type`, `entry_price`, `stop_loss`, `close_price`, `status`, `regime_score`
- `backend/main.py` — FastAPI app; existing `/api/diagnostics/report` endpoint at line 2940; `EARNINGS_CACHE_FILE = "cache/earnings_cache.json"` pattern for cache paths
- `frontend/src/components/DiagnosticsTab.jsx` — diagnostics UI; currently fetches `/api/diagnostics/report` only
- `backend/tickers.py` — exports `SCAN_UNIVERSE` (809 tickers)

Design doc: `docs/plans/2026-03-10-backtest-diagnostics-design.md`

**IMPORTANT — analytics.py trade dict shape:**
Backtest `TradeRecord.to_dict()` uses `initial_stop` and `exit_price`; analytics.py expects `stop_loss` and `close_price`. An adapter is needed.

Run tests with: `cd swing-trading-dashboard/backend && python -m pytest tests/ -v`

---

## Task 1: Add backtest diagnostics constants to constants.py

**Files:**
- Modify: `swing-trading-dashboard/backend/constants.py` (append after line ~260)
- Test: `swing-trading-dashboard/backend/tests/test_backtest_diag_constants.py` (create)

**Step 1: Write the failing test**

```python
# swing-trading-dashboard/backend/tests/test_backtest_diag_constants.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_backtest_diag_constants_exist():
    from constants import (
        BACKTEST_DIAG_START_DATE,
        BACKTEST_DIAG_END_DATE,
        BACKTEST_V4_TRAIL_MULT,
    )
    assert BACKTEST_DIAG_START_DATE == "2023-01-01"
    assert BACKTEST_DIAG_END_DATE   == "2024-12-31"
    assert BACKTEST_V4_TRAIL_MULT   == 4.162

def test_backtest_v4_trail_mult_is_distinct_from_trail_atr_mult():
    """BACKTEST_V4_TRAIL_MULT is a separate constant — not an alias."""
    import constants
    # Both happen to have the same value, but they are independent names
    assert hasattr(constants, "BACKTEST_V4_TRAIL_MULT")
    assert hasattr(constants, "TRAIL_ATR_MULT")

def test_backtest_cache_file_constant_exists():
    from constants import BACKTEST_DIAG_CACHE_FILE
    assert BACKTEST_DIAG_CACHE_FILE == "cache/backtest_diagnostics.json"
```

**Step 2: Run test to verify it fails**

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_backtest_diag_constants.py -v
```

Expected: FAIL with `ImportError: cannot import name 'BACKTEST_DIAG_START_DATE'`

**Step 3: Add constants to constants.py**

Append to the end of `swing-trading-dashboard/backend/constants.py`:

```python
# ── V4 Backtest Diagnostics ───────────────────────────────────────────────────
BACKTEST_DIAG_START_DATE = "2023-01-01"   # fixed 2-year baseline window start
BACKTEST_DIAG_END_DATE   = "2024-12-31"   # fixed 2-year baseline window end
BACKTEST_V4_TRAIL_MULT   = 4.162          # strict V4 single trail multiplier (all setup types)
BACKTEST_DIAG_CACHE_FILE = "cache/backtest_diagnostics.json"   # relative to backend/
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_backtest_diag_constants.py -v
```

Expected: 3 PASSED

**Step 5: Commit**

```bash
git add backend/constants.py backend/tests/test_backtest_diag_constants.py
git commit -m "feat(backtest-diag): add V4 baseline diagnostic constants"
```

---

## Task 2: Add `trail_mult_override` to BacktestEngine

**Files:**
- Modify: `swing-trading-dashboard/backend/backtest_engine.py`
- Test: `swing-trading-dashboard/backend/tests/test_backtest_trail_override.py` (create)

**Context:**
- `BacktestEngine.__init__` is at line 528; add `trail_mult_override: float | None = None` as the last param
- `_manage_open_trade` is at line 290; the trail multiplier lookup is at lines 334–336
- Trade state dict is initialised at lines 753–761; add `"trail_mult_override": self.trail_mult_override` to it

**Step 1: Write the failing tests**

```python
# swing-trading-dashboard/backend/tests/test_backtest_trail_override.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_state(setup_type: str, trail_mult_override=None) -> dict:
    state = {
        "entry_price":        100.0,
        "trailing_stop":       95.0,
        "take_profit":        130.0,
        "entry_date":         "2024-01-01",
        "setup_type":          setup_type,
    }
    if trail_mult_override is not None:
        state["trail_mult_override"] = trail_mult_override
    return state


def test_override_forces_single_mult_for_vcp():
    """When trail_mult_override=4.162, VCP must NOT use its 2.0 mult."""
    from backtest_engine import _manage_open_trade
    state = _make_state("VCP", trail_mult_override=4.162)
    # close=108, ema20=95, atr14=1.0
    # With override=4.162: atr_trail = 108 - 4.162*1.0 = 103.838; ema20=95 → new_trail=103.838
    # With VCP mult=2.0:   atr_trail = 108 - 2.0*1.0  = 106.0;   ema20=95 → new_trail=106.0
    bar = {"date": "2024-01-02", "open": 107.0, "high": 109.0, "low": 106.0,
           "close": 108.0, "ema20": 95.0, "atr14": 1.0}
    _manage_open_trade(state, bar)
    # Must be 103.838 (override), not 106.0 (V5 VCP)
    assert abs(state["trailing_stop"] - (108.0 - 4.162 * 1.0)) < 0.01


def test_override_forces_single_mult_for_pullback():
    """When trail_mult_override=4.162, PULLBACK must NOT use its 3.0 mult."""
    from backtest_engine import _manage_open_trade
    state = _make_state("PULLBACK", trail_mult_override=4.162)
    bar = {"date": "2024-01-02", "open": 107.0, "high": 109.0, "low": 106.0,
           "close": 108.0, "ema20": 95.0, "atr14": 1.0}
    _manage_open_trade(state, bar)
    assert abs(state["trailing_stop"] - (108.0 - 4.162 * 1.0)) < 0.01


def test_no_override_preserves_v5_vcp_mult():
    """Without override, VCP still uses its V5 tight 2.0 multiplier."""
    from backtest_engine import _manage_open_trade
    state = _make_state("VCP")   # no trail_mult_override key
    bar = {"date": "2024-01-02", "open": 107.0, "high": 109.0, "low": 106.0,
           "close": 108.0, "ema20": 95.0, "atr14": 1.0}
    _manage_open_trade(state, bar)
    assert abs(state["trailing_stop"] - (108.0 - 2.0 * 1.0)) < 0.01


def test_engine_stores_override_in_run():
    """BacktestEngine initialised with trail_mult_override stores it."""
    from backtest_engine import BacktestEngine
    eng = BacktestEngine("AAPL", "2023-01-01", "2023-06-01", trail_mult_override=4.162)
    assert eng.trail_mult_override == 4.162


def test_engine_default_override_is_none():
    """BacktestEngine without trail_mult_override defaults to None."""
    from backtest_engine import BacktestEngine
    eng = BacktestEngine("AAPL", "2023-01-01", "2023-06-01")
    assert eng.trail_mult_override is None
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_backtest_trail_override.py -v
```

Expected: FAIL with `TypeError` (unexpected keyword argument) or `AttributeError`

**Step 3: Implement the changes in backtest_engine.py**

**3a.** In `BacktestEngine.__init__` (line 538), add the new parameter:

```python
    def __init__(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        setup_types: Optional[List[str]] = None,
        run_id: Optional[str] = None,
        ticker_df: Optional[pd.DataFrame] = None,
        spy_df: Optional[pd.DataFrame] = None,
        earnings_dates: Optional[Dict[str, List[str]]] = None,
        trail_mult_override: Optional[float] = None,      # ← add this line
    ):
        self.ticker              = ticker.upper()
        self.start_date          = start_date
        self.end_date            = end_date
        self.setup_types         = setup_types or ["VCP", "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"]
        self.run_id              = run_id or str(uuid.uuid4())
        self.ticker_df           = ticker_df
        self.spy_df              = spy_df
        self.earnings_dates: Dict[str, List[str]] = earnings_dates or {}
        self.trail_mult_override = trail_mult_override    # ← add this line
```

**3b.** In `open_trades.append({...})` (lines 753–761), add the override to the state dict:

```python
            open_trades.append({
                "setup_type":         signal.get("setup_type", self.setup_types[0]),
                "signal_date":        T_date.strftime("%Y-%m-%d"),
                "entry_date":         next_date.strftime("%Y-%m-%d"),
                "entry_price":        entry_price,
                "initial_stop":       stop_loss,
                "trailing_stop":      stop_loss,
                "take_profit":        take_profit,
                "trail_mult_override": self.trail_mult_override,   # ← add this line
            })
```

**3c.** In `_manage_open_trade()` (lines 334–336), add override logic:

Replace:
```python
        setup_type = state.get("setup_type", "")
        mult_fn = _TRAIL_ATR_BY_SETUP.get(setup_type)
        mult = mult_fn() if mult_fn else _constants.TRAIL_ATR_MULT
```

With:
```python
        override = state.get("trail_mult_override")
        if override is not None:
            mult = override
        else:
            setup_type = state.get("setup_type", "")
            mult_fn = _TRAIL_ATR_BY_SETUP.get(setup_type)
            mult = mult_fn() if mult_fn else _constants.TRAIL_ATR_MULT
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_backtest_trail_override.py tests/test_trail_atr_mult.py -v
```

Expected: All tests PASS. The existing `test_trail_atr_mult.py` tests must still pass (V5 behavior unchanged when no override).

**Step 5: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_backtest_trail_override.py
git commit -m "feat(backtest-diag): add trail_mult_override param to BacktestEngine"
```

---

## Task 3: Add `run_backtest_universe()` to backtest_engine.py

**Files:**
- Modify: `swing-trading-dashboard/backend/backtest_engine.py` (append after the `BacktestEngine` class)
- Test: `swing-trading-dashboard/backend/tests/test_run_backtest_universe.py` (create)

**Context:**
`run_backtest_universe` runs `BacktestEngine` concurrently across many tickers using `asyncio.Semaphore(CONCURRENCY_LIMIT)` — the same pattern as the scanner. It returns a flat list of `TradeRecord.to_dict()` dicts (not `BacktestSummary` objects). Each ticker's trades are collected from `summary.trades` (list of `TradeRecord`).

**Step 1: Write the failing tests**

```python
# swing-trading-dashboard/backend/tests/test_run_backtest_universe.py
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_run_backtest_universe_is_importable():
    from backtest_engine import run_backtest_universe
    assert callable(run_backtest_universe)


def test_run_backtest_universe_empty_tickers_returns_empty():
    from backtest_engine import run_backtest_universe
    result = _run(run_backtest_universe([], "2023-01-01", "2023-03-01"))
    assert result == []


def test_run_backtest_universe_returns_list_of_dicts(monkeypatch):
    """With a mock engine that returns 2 trades, universe returns 2 dicts."""
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
    assert "initial_stop" in trade      # raw TradeRecord fields preserved
    assert "exit_price" in trade


def test_run_backtest_universe_passes_trail_override(monkeypatch):
    """trail_mult_override is forwarded to each BacktestEngine instance."""
    from backtest_engine import run_backtest_universe, BacktestEngine
    import backtest_engine as be

    seen_overrides = []

    async def fake_run(self):
        seen_overrides.append(self.trail_mult_override)
        from backtest_engine import compute_metrics
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
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_run_backtest_universe.py -v
```

Expected: FAIL with `ImportError: cannot import name 'run_backtest_universe'`

**Step 3: Implement `run_backtest_universe` in backtest_engine.py**

Append after the `BacktestEngine` class (after line ~797):

```python
# ─────────────────────────────────────────────────────────────────────────────
# Universe-level backtest runner
# ─────────────────────────────────────────────────────────────────────────────

async def run_backtest_universe(
    tickers: List[str],
    start_date: str,
    end_date: str,
    trail_mult_override: Optional[float] = None,
    progress_cb=None,
) -> List[dict]:
    """
    Run BacktestEngine concurrently over all tickers.

    Parameters
    ----------
    tickers             : list of ticker symbols
    start_date          : ISO date string "YYYY-MM-DD"
    end_date            : ISO date string "YYYY-MM-DD"
    trail_mult_override : when set, all engines use this single ATR trail mult
                          (bypasses V5 per-setup dict — use for V4 baseline audit)
    progress_cb         : optional async callable(done: int, total: int)
                          called after each ticker completes

    Returns
    -------
    Flat list of TradeRecord.to_dict() dicts across all tickers.
    """
    if not tickers:
        return []

    sem   = asyncio.Semaphore(CONCURRENCY_LIMIT)
    total = len(tickers)
    done  = 0
    all_trades: List[dict] = []
    lock  = asyncio.Lock()

    async def _run_one(ticker: str) -> List[dict]:
        nonlocal done
        async with sem:
            try:
                engine = BacktestEngine(
                    ticker=ticker,
                    start_date=start_date,
                    end_date=end_date,
                    trail_mult_override=trail_mult_override,
                )
                summary = await engine.run()
                return [t.to_dict() for t in summary.trades]
            except Exception as exc:
                logger.warning("run_backtest_universe: %s failed: %s", ticker, exc)
                return []
            finally:
                async with lock:
                    done += 1
                    if progress_cb is not None:
                        await progress_cb(done, total)

    results = await asyncio.gather(*[_run_one(t) for t in tickers])
    for batch in results:
        all_trades.extend(batch)
    return all_trades
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_run_backtest_universe.py tests/test_backtest_trail_override.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add backend/backtest_engine.py backend/tests/test_run_backtest_universe.py
git commit -m "feat(backtest-diag): add run_backtest_universe() to backtest_engine"
```

---

## Task 4: Backend — adapter, status dict, 3 new endpoints in main.py

**Files:**
- Modify: `swing-trading-dashboard/backend/main.py`
- Test: `swing-trading-dashboard/backend/tests/test_backtest_diag_endpoint.py` (create)

**Context:**
- Import `run_backtest_universe` from `backtest_engine` (already imported at line 165)
- Import `BACKTEST_DIAG_START_DATE`, `BACKTEST_DIAG_END_DATE`, `BACKTEST_V4_TRAIL_MULT`, `BACKTEST_DIAG_CACHE_FILE` from constants
- The cache file pattern follows `EARNINGS_CACHE_FILE = "cache/earnings_cache.json"` — same relative path style
- `analytics.py` functions are already imported at lines 157–163
- `SCAN_UNIVERSE` / `ACTIVE_UNIVERSE` is the ticker list to use
- Endpoints must be added after the existing `/api/diagnostics/report` (line 2940)

**Step 1: Write the failing tests**

```python
# swing-trading-dashboard/backend/tests/test_backtest_diag_endpoint.py
"""
Tests for the backtest diagnostics adapter and status dict.
Endpoints are tested via the adapter logic; full HTTP tests
are out of scope (require live yfinance data).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_adapter_maps_initial_stop_to_stop_loss():
    """initial_stop → stop_loss for analytics.py compatibility."""
    import importlib
    import main as m
    trade = {
        "ticker": "AAPL", "setup_type": "VCP",
        "entry_price": 100.0, "initial_stop": 93.0,
        "exit_price": 112.0, "exit_reason": "TARGET",
        "rr_achieved": 1.71, "is_win": True,
    }
    result = m._backtest_trade_to_analytics(trade)
    assert result["stop_loss"]   == 93.0
    assert result["close_price"] == 112.0
    assert result["status"]      == "closed"
    assert result["regime_score"] is None


def test_adapter_preserves_ticker_and_setup_type():
    import main as m
    trade = {"ticker": "MSFT", "setup_type": "PULLBACK",
             "entry_price": 200.0, "initial_stop": 190.0,
             "exit_price": 210.0}
    result = m._backtest_trade_to_analytics(trade)
    assert result["ticker"]     == "MSFT"
    assert result["setup_type"] == "PULLBACK"
    assert result["entry_price"] == 200.0


def test_backtest_diag_status_initial_state():
    import main as m
    s = m._backtest_diag_status
    assert "status" in s
    assert s["status"] in ("idle", "running", "completed", "failed")
    assert "done"  in s
    assert "total" in s
    assert "last_run" in s


def test_backtest_diag_cache_path_uses_constant():
    """BACKTEST_DIAG_CACHE_PATH is derived from the constant."""
    import main as m
    from constants import BACKTEST_DIAG_CACHE_FILE
    assert m.BACKTEST_DIAG_CACHE_PATH.endswith(BACKTEST_DIAG_CACHE_FILE.replace("/", os.sep))
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_backtest_diag_endpoint.py -v
```

Expected: FAIL with `AttributeError: module 'main' has no attribute '_backtest_trade_to_analytics'`

**Step 3: Implement in main.py**

**3a.** Add to the imports block (near the existing constants imports):

```python
from constants import (
    # ... existing imports ...
    BACKTEST_DIAG_START_DATE,
    BACKTEST_DIAG_END_DATE,
    BACKTEST_V4_TRAIL_MULT,
    BACKTEST_DIAG_CACHE_FILE,
)
```

**3b.** Add to the existing `from backtest_engine import ...` line:

```python
from backtest_engine import BacktestEngine, run_backtest_universe
```

**3c.** After the existing module-level constants (near line 391, after `_semaphore`), add:

```python
# ── Backtest diagnostics state ────────────────────────────────────────────────
BACKTEST_DIAG_CACHE_PATH = os.path.join(os.path.dirname(__file__), BACKTEST_DIAG_CACHE_FILE)

_backtest_diag_status: dict = {
    "status":   "idle",   # "idle" | "running" | "completed" | "failed"
    "done":     0,
    "total":    0,
    "last_run": None,     # ISO timestamp of last completed run
}


def _backtest_trade_to_analytics(tr: dict) -> dict:
    """Map TradeRecord.to_dict() fields to analytics.py contract."""
    return {
        "ticker":       tr["ticker"],
        "setup_type":   tr["setup_type"],
        "entry_price":  tr["entry_price"],
        "stop_loss":    tr["initial_stop"],   # initial_stop → stop_loss
        "close_price":  tr["exit_price"],     # exit_price  → close_price
        "status":       "closed",
        "regime_score": None,
    }
```

**3d.** After the existing `/api/diagnostics/report` endpoint (after line 2974), add the three new endpoints:

```python
@app.post("/api/diagnostics/backtest/run", status_code=202)
async def run_backtest_diagnostics(background_tasks: BackgroundTasks):
    """
    Trigger a background V4 strategy baseline backtest over the full universe.
    Returns immediately. Poll /api/diagnostics/backtest/status for progress.
    Returns 409 if a run is already in progress.
    """
    global _backtest_diag_status
    if _backtest_diag_status["status"] == "running":
        raise HTTPException(status_code=409, detail="Backtest already running")

    tickers = list(ACTIVE_UNIVERSE) if ACTIVE_UNIVERSE else list(SCAN_UNIVERSE)

    async def _do_backtest():
        global _backtest_diag_status
        _backtest_diag_status.update({"status": "running", "done": 0, "total": len(tickers)})
        try:
            async def _progress(done: int, total: int):
                _backtest_diag_status["done"] = done

            raw_trades = await run_backtest_universe(
                tickers,
                BACKTEST_DIAG_START_DATE,
                BACKTEST_DIAG_END_DATE,
                trail_mult_override=BACKTEST_V4_TRAIL_MULT,
                progress_cb=_progress,
            )
            adapted = [_backtest_trade_to_analytics(t) for t in raw_trades]

            report = {
                "generated_at":       datetime.now(timezone.utc).isoformat(),
                "start_date":         BACKTEST_DIAG_START_DATE,
                "end_date":           BACKTEST_DIAG_END_DATE,
                "tickers_run":        len(tickers),
                "total_trades":       len(adapted),
                "summary":            compute_live_diagnostics(adapted),
                "setup_breakdown":    compute_setup_breakdown(adapted),
                "ticker_distribution": compute_ticker_distribution(adapted),
                "regime_performance": compute_regime_performance(adapted),
            }

            os.makedirs(os.path.dirname(BACKTEST_DIAG_CACHE_PATH), exist_ok=True)
            with open(BACKTEST_DIAG_CACHE_PATH, "w") as f:
                json.dump(report, f)

            now_iso = datetime.now(timezone.utc).isoformat()
            _backtest_diag_status.update({"status": "completed", "last_run": now_iso})
            log.info("Backtest diagnostics complete: %d trades from %d tickers",
                     len(adapted), len(tickers))
        except Exception as exc:
            _backtest_diag_status["status"] = "failed"
            log.error("Backtest diagnostics failed: %s", exc)

    background_tasks.add_task(_do_backtest)
    return {"status": "started", "message": f"V4 backtest running over {len(tickers)} tickers"}


@app.get("/api/diagnostics/backtest/status")
async def backtest_diagnostics_status():
    """Poll progress of the background V4 backtest run."""
    return {
        "status":   _backtest_diag_status["status"],
        "done":     _backtest_diag_status["done"],
        "total":    _backtest_diag_status["total"],
        "last_run": _backtest_diag_status["last_run"],
    }


@app.get("/api/diagnostics/backtest")
async def backtest_diagnostics_report():
    """
    Return the cached V4 baseline backtest diagnostics report.
    Returns 404 if no run has been completed yet.
    """
    if not os.path.exists(BACKTEST_DIAG_CACHE_PATH):
        raise HTTPException(
            status_code=404,
            detail="No backtest cache found. POST /api/diagnostics/backtest/run to generate.",
        )
    try:
        with open(BACKTEST_DIAG_CACHE_PATH, "r") as f:
            return json.load(f)
    except Exception as exc:
        log.error("Failed to read backtest diagnostics cache: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to read backtest cache")
```

**Note:** `datetime`, `timezone`, `json`, and `os` are already imported in `main.py`. Verify with `grep -n "^import json\|^import os\|from datetime" main.py`.

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_backtest_diag_endpoint.py -v
```

Expected: All 4 tests PASS.

**Step 5: Run full test suite to catch regressions**

```bash
python -m pytest tests/test_analytics.py tests/test_trail_atr_mult.py tests/test_backtest_trail_override.py tests/test_run_backtest_universe.py tests/test_backtest_diag_constants.py tests/test_backtest_diag_endpoint.py -v
```

Expected: All PASS.

**Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_backtest_diag_endpoint.py
git commit -m "feat(backtest-diag): add 3 backtest diagnostics endpoints + adapter"
```

---

## Task 5: Frontend — source toggle in DiagnosticsTab.jsx

**Files:**
- Modify: `swing-trading-dashboard/frontend/src/components/DiagnosticsTab.jsx`

**Context:**
Read the full current `DiagnosticsTab.jsx` before editing. The component currently fetches `/api/diagnostics/report` in a `useEffect`. The changes:
1. Add `source` state (`"live"` | `"backtest"`)
2. Add a toggle bar below the tab header
3. When `source === "live"`: current behavior unchanged
4. When `source === "backtest"`: three sub-states driven by an additional `backtestStatus` state

No new components — the same MetricCard, equity curve, breakdown table, ticker distribution, and regime performance sections are reused for both sources. The data shapes returned by both endpoints are identical.

**Step 1: Read the current file**

```bash
cat swing-trading-dashboard/frontend/src/components/DiagnosticsTab.jsx
```

Read it fully before making any edits.

**Step 2: Add source toggle state and fetch logic**

At the top of the component (inside the function body), add:

```jsx
const [source, setSource] = React.useState('live')  // 'live' | 'backtest'
const [backtestStatus, setBacktestStatus] = React.useState(null)  // null | status object
const [btRunning, setBtRunning] = React.useState(false)
const pollRef = React.useRef(null)
```

Replace the existing fetch `useEffect` with one that reacts to `source`:

```jsx
React.useEffect(() => {
  const controller = new AbortController()

  async function fetchData() {
    setLoading(true)
    setError(null)
    try {
      const url = source === 'live'
        ? '/api/diagnostics/report'
        : '/api/diagnostics/backtest'
      const res = await fetch(url, { signal: controller.signal })
      if (res.status === 404 && source === 'backtest') {
        setData(null)   // no cache yet — show "run backtest" prompt
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  fetchData()
  return () => controller.abort()
}, [source])
```

**Step 3: Add polling logic for backtest status**

Add a second `useEffect` that polls `/api/diagnostics/backtest/status` while `btRunning`:

```jsx
React.useEffect(() => {
  if (!btRunning) return
  pollRef.current = setInterval(async () => {
    try {
      const res = await fetch('/api/diagnostics/backtest/status')
      const s = await res.json()
      setBacktestStatus(s)
      if (s.status === 'completed' || s.status === 'failed') {
        setBtRunning(false)
        clearInterval(pollRef.current)
        if (s.status === 'completed') {
          // Fetch the completed report
          const r = await fetch('/api/diagnostics/backtest')
          if (r.ok) setData(await r.json())
        }
      }
    } catch (_) {}
  }, 3000)
  return () => clearInterval(pollRef.current)
}, [btRunning])
```

**Step 4: Add trigger handler**

```jsx
async function handleRunBacktest() {
  setBtRunning(true)
  setData(null)
  try {
    await fetch('/api/diagnostics/backtest/run', { method: 'POST' })
    const s = await fetch('/api/diagnostics/backtest/status').then(r => r.json())
    setBacktestStatus(s)
  } catch (err) {
    setBtRunning(false)
  }
}
```

**Step 5: Add the source toggle bar to the JSX**

Add a toggle bar immediately after the tab title `<div>` and before the content sections:

```jsx
{/* Source toggle */}
<div style={{ display: 'flex', gap: 4, padding: '12px 20px 0', borderBottom: '1px solid var(--card-border)' }}>
  {['live', 'backtest'].map(s => (
    <button
      key={s}
      onClick={() => { setSource(s); setData(null) }}
      style={{
        padding: '5px 14px', borderRadius: 6, fontSize: 11, fontWeight: 700,
        fontFamily: '"IBM Plex Mono", monospace', letterSpacing: '0.05em',
        border: source === s ? '1px solid var(--accent)' : '1px solid var(--border)',
        background: source === s ? 'rgba(245,166,35,0.12)' : 'transparent',
        color: source === s ? 'var(--accent)' : 'var(--muted)',
        cursor: 'pointer',
      }}
    >
      {s === 'live' ? 'Live Trades' : 'Backtest (V4 baseline)'}
    </button>
  ))}
</div>
```

**Step 6: Add backtest-specific states in the render**

In the backtest source section (when `source === 'backtest'` and `data === null`), show:

```jsx
{source === 'backtest' && !data && !loading && (
  <div style={{ padding: 40, textAlign: 'center' }}>
    {btRunning && backtestStatus ? (
      <>
        <div style={{ color: 'var(--muted)', fontSize: 12, marginBottom: 12 }}>
          Running V4 backtest — {backtestStatus.done} / {backtestStatus.total} tickers…
        </div>
        <div style={{ height: 4, background: 'var(--border)', borderRadius: 2, width: 300, margin: '0 auto' }}>
          <div style={{
            height: '100%', borderRadius: 2, background: 'var(--accent)',
            width: `${backtestStatus.total > 0 ? (backtestStatus.done / backtestStatus.total * 100) : 0}%`,
            transition: 'width 0.5s ease',
          }} />
        </div>
      </>
    ) : (
      <>
        <div style={{ color: 'var(--muted)', fontSize: 12, marginBottom: 16 }}>
          No V4 backtest data. Run the baseline to generate a strategy audit.
        </div>
        <button
          onClick={handleRunBacktest}
          disabled={btRunning}
          style={{
            padding: '8px 20px', borderRadius: 8, fontSize: 11, fontWeight: 700,
            fontFamily: '"IBM Plex Mono", monospace',
            background: 'rgba(245,166,35,0.15)', color: 'var(--accent)',
            border: '1px solid rgba(245,166,35,0.35)', cursor: 'pointer',
          }}
        >
          Run V4 Backtest
        </button>
      </>
    )}
  </div>
)}
```

**Step 7: Add metadata badge when backtest data is shown**

When `source === 'backtest' && data`, render a date-range badge at the top of the content area:

```jsx
{source === 'backtest' && data && (
  <div style={{ padding: '8px 20px', fontSize: 10, color: 'var(--muted)',
                fontFamily: '"IBM Plex Mono", monospace',
                borderBottom: '1px solid var(--card-border)' }}>
    V4 Baseline · {data.start_date} → {data.end_date} ·{' '}
    {data.tickers_run} tickers · generated {new Date(data.generated_at).toLocaleDateString()}
  </div>
)}
```

**Step 8: Verify UI behavior manually**

Start both servers:
```bash
# Terminal 1
cd swing-trading-dashboard/backend && python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2
cd swing-trading-dashboard/frontend && npm run dev
```

Open http://localhost:5173, navigate to DIAGNOSTICS tab.

Verify:
- "Live Trades" button selected by default — existing data renders
- Click "Backtest (V4 baseline)" — shows "No V4 backtest data" + "Run V4 Backtest" button (since no cache exists yet)
- Click "Run V4 Backtest" — button changes state, progress bar appears (polling)
- After run completes — report renders with metadata badge showing date range

**Step 9: Commit**

```bash
git add frontend/src/components/DiagnosticsTab.jsx
git commit -m "feat(backtest-diag): add source toggle to DiagnosticsTab — live vs V4 baseline"
```

---

## Final Verification

Run the full V5+backtest-diag test suite:

```bash
cd swing-trading-dashboard/backend
python -m pytest tests/test_analytics.py tests/test_trail_atr_mult.py tests/test_backtest_trail_override.py tests/test_run_backtest_universe.py tests/test_backtest_diag_constants.py tests/test_backtest_diag_endpoint.py -v
```

Expected: All pass.
