# Portfolio-Coordinated Backtest — Design Spec

## Goal

Replace the current per-ticker independent backtest with a portfolio-level simulation:
- Global cap of N concurrent positions (default 4) across all tickers
- When a slot opens, the highest-scoring available signal fills it
- Configurable via UI (date range, universe size, max positions, min score, setup types)
- Fix "V4 baseline" label and make results reflect actual config used

---

## Problem With Current Implementation

`run_backtest_universe` spawns one `BacktestEngine` per ticker, each running independently.
`MAX_OPEN_POSITIONS = 5` is a **per-ticker** cap — not portfolio-wide. With 700 tickers, up to
~60 positions can be open simultaneously. This is not a portfolio simulation; it is a signal
quality audit that ignores capital constraints entirely.

---

## Architecture

**Files changed:**

| File | Change |
|------|--------|
| `backend/portfolio_backtest.py` | New — `TickerSimState`, `BacktestConfig`, `run_portfolio_backtest_universe()` |
| `backend/backtest_engine.py` | Add `BacktestEngine.prepare()` async method returning `TickerSimState` |
| `backend/main.py` | Endpoint accepts optional config body; calls new runner; updated labels |
| `frontend/src/components/DiagnosticsTab.jsx` | Config panel UI; label fix; passes config to API |

---

## backend/portfolio_backtest.py (new)

### BacktestConfig

```python
@dataclass
class BacktestConfig:
    start_date:    str            = "2017-01-01"
    end_date:      str            = "2024-12-31"
    max_positions: int            = 4
    ticker_count:  Optional[int]  = None   # None = full universe
    min_score:     float          = 0.0
    setup_types:   List[str]      = field(default_factory=lambda: [
        "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"
    ])
    # VCP is intentionally excluded from defaults — VCP is disabled in the live
    # scanner and used only as a co-signal bonus score. The UI does not expose a
    # VCP checkbox. This is a deliberate design decision.
```

### TickerSimState

Produced by `BacktestEngine.prepare()`. Immutable data + mutable runtime state in one object.
Runtime state fields are reset to defaults at the start of every portfolio run (see Phase 2).

```python
@dataclass
class TickerSimState:
    # ── Immutable data (set once during prepare) ──────────────────────────────
    ticker:          str
    ticker_df:       pd.DataFrame   # full df with pre-computed indicator columns
    spy_df:          pd.DataFrame   # shared SPY df (same object across all tickers)
    adj_col:         str            # "Adj Close" or "Close"
    ticker_dates:    pd.DatetimeIndex   # this ticker's own trading dates
    ema20_full:      pd.Series
    atr14_full:      pd.Series
    sr_zones_cache:  list
    rs_ratio_s:      pd.Series
    rs_52wh_s:       pd.Series
    rs_score_s:      pd.Series
    spy_3m_s:        pd.Series
    params:          Optional[BacktestParams]  # forwarded for scored-mode signal detection
    # ── Mutable runtime state (reset before each portfolio run) ───────────────
    is_in_trade:     bool           = False
    last_close_date: Optional[date] = None
```

Note: `regime_label_s` is **not** stored per-ticker. A single `regime_label_s: pd.Series`
is computed from SPY once in Phase 1 and passed to the coordinated loop.

### run_portfolio_backtest_universe()

```python
async def run_portfolio_backtest_universe(
    tickers: List[str],
    config: BacktestConfig,
    params: Optional[BacktestParams] = None,
    progress_cb=None,
) -> List[dict]:
```

**Phase 1 — Parallel data loading:**

```python
# 1a. Fetch SPY once, shared across all ticker states
spy_df = await _fetch_spy(config.start_date)

# 1b. Compute regime label series from SPY — used globally in Phase 2
regime_label_s: pd.Series = compute_regime_label_series(spy_df) if spy_df is not None else pd.Series(dtype=object)

# 1c. Prepare all tickers concurrently (semaphore = CONCURRENCY_LIMIT)
sem = asyncio.Semaphore(CONCURRENCY_LIMIT)
ticker_states: List[TickerSimState] = []

async def _prepare_one(ticker):
    async with sem:
        engine = BacktestEngine(ticker, config.start_date, config.end_date,
                                setup_types=config.setup_types, params=params)
        state = await engine.prepare(shared_spy_df=spy_df)
        if state is not None:
            ticker_states.append(state)
        if progress_cb:
            await progress_cb(...)

await asyncio.gather(*[_prepare_one(t) for t in tickers])
```

**Phase 2 — Coordinated day-by-day replay:**

```python
# Reset all mutable state before replay (makes function safe to call multiple times)
for ts in ticker_states:
    ts.is_in_trade = False
    ts.last_close_date = None

# Build union trading calendar — sorted union of all ticker date indices
all_union_dates = sorted(set().union(*[set(ts.ticker_dates) for ts in ticker_states]))
start_ts = pd.Timestamp(config.start_date)
end_ts   = pd.Timestamp(config.end_date)
replay_dates = [d for d in all_union_dates if start_ts <= d <= end_ts]

open_positions: List[dict] = []   # each: {"trade_state": dict, "ticker_state": TickerSimState}
completed_trades: List[dict] = []

for T_date in replay_dates:

    # ── Step 1: advance all open positions ───────────────────────────────
    still_open = []
    for pos in open_positions:
        ts = pos["ticker_state"]
        # Skip advance if this ticker has no bar on T_date (e.g. different holiday)
        if T_date not in ts.ticker_dates:
            still_open.append(pos)
            continue
        full_idx = ts.ticker_dates.get_loc(T_date)
        ema20_T = float(ts.ema20_full.iloc[full_idx])
        atr14_T = float(ts.atr14_full.iloc[full_idx]) if ts.atr14_full is not None else 0.0
        bar = {
            "date":  T_date.strftime("%Y-%m-%d"),
            "open":  float(ts.ticker_df["Open"].iloc[full_idx]),
            "high":  float(ts.ticker_df["High"].iloc[full_idx]),
            "low":   float(ts.ticker_df["Low"].iloc[full_idx]),
            "close": float(ts.ticker_df[ts.adj_col].iloc[full_idx]),
            "ema20": ema20_T if not np.isnan(ema20_T) else 0.0,
            "atr14": atr14_T if not np.isnan(atr14_T) else 0.0,
        }
        closed, exit_price, exit_reason = _manage_open_trade(pos["trade_state"], bar)
        if closed:
            completed_trades.append(_build_trade_record(pos, T_date, exit_price, exit_reason))
            ts.is_in_trade = False
            ts.last_close_date = T_date.date()
        else:
            still_open.append(pos)
    open_positions = still_open

    # ── Step 2: check available slots ────────────────────────────────────
    available = config.max_positions - len(open_positions)
    if available <= 0:
        continue

    # ── Step 3: resolve regime — skip signal collection if DEFENSIVE ─────
    # regime_label_s is indexed by SPY dates; find latest SPY date <= T_date
    spy_dates_before = regime_label_s.index[regime_label_s.index <= T_date]
    current_regime = str(regime_label_s.loc[spy_dates_before[-1]]) if len(spy_dates_before) > 0 else "UNKNOWN"
    if current_regime == "DEFENSIVE":
        continue

    # ── Step 4: collect signals from all free tickers ────────────────────
    candidates = []
    for ts in ticker_states:
        if ts.is_in_trade:
            continue
        # Ticker must have a bar on T_date AND a next bar (T+1 open for entry price)
        if T_date not in ts.ticker_dates:
            continue
        full_idx = ts.ticker_dates.get_loc(T_date)
        if full_idx + 1 >= len(ts.ticker_dates):
            continue   # T_date is the last bar for this ticker — no entry possible

        # Cooldown gate
        if ts.last_close_date is not None:
            cooldown = ts.params.cooldown_days if ts.params is not None else 0
            if (T_date.date() - ts.last_close_date).days < cooldown:
                continue

        # Liquidity gate
        df_slice = ts.ticker_df.iloc[:full_idx + 1]
        if not passes_liquidity(df_slice):
            continue

        # Signal detection — scored mode (PULLBACK via scan_pullback_scored) or legacy
        signal = _detect_signals_for_date(ts, T_date, full_idx, config.setup_types)
        if signal is None:
            continue

        score = signal.get("_final_score")
        score = score if score is not None else 0.0
        if score < config.min_score:
            continue

        candidates.append((score, signal, ts, full_idx))

    # ── Step 5: fill slots — best score first ────────────────────────────
    candidates.sort(key=lambda x: -x[0])
    for score, signal, ts, full_idx in candidates[:available]:
        next_idx = full_idx + 1
        next_date = ts.ticker_dates[next_idx]
        entry_price = float(ts.ticker_df["Open"].iloc[next_idx])
        # Guard: valid entry
        stop_loss   = signal.get("stop_loss", 0.0)
        take_profit = signal.get("take_profit", 0.0)
        if stop_loss <= 0 or stop_loss >= entry_price or take_profit <= entry_price:
            continue
        open_positions.append(_build_open_position(signal, ts, T_date, next_date, entry_price))
        ts.is_in_trade = True

# ── Step 6: force-close any positions still open at end_date ─────────────────
for pos in open_positions:
    ts = pos["ticker_state"]
    last_date = ts.ticker_dates[ts.ticker_dates <= end_ts][-1] if any(ts.ticker_dates <= end_ts) else None
    if last_date is not None:
        last_idx = ts.ticker_dates.get_loc(last_date)
        exit_price = float(ts.ticker_df[ts.adj_col].iloc[last_idx])
        completed_trades.append(_build_trade_record(pos, last_date, exit_price, "end_of_period"))
    ts.is_in_trade = False

return completed_trades
```

### _detect_signals_for_date()

Handles both scored-mode and legacy-mode signal detection, matching the existing
`BacktestEngine.run()` logic exactly:

```python
def _detect_signals_for_date(
    ts: TickerSimState,
    T_date: pd.Timestamp,
    full_idx: int,
    setup_types: List[str],
) -> Optional[dict]:
    """
    Detect a setup signal for ticker ts on date T_date.
    Matches BacktestEngine.run() signal detection logic exactly:
      - Scored mode (ts.params is not None): routes PULLBACK through scan_pullback_scored,
        applies VCP co-signal boost, then detects other setup types with params forwarded.
      - Legacy mode (ts.params is None): calls _detect_signals() directly.
    Returns signal dict or None. No side effects.
    """
    df_slice  = ts.ticker_df.iloc[:full_idx + 1]
    spy_slice = ts.spy_df.loc[ts.spy_df.index <= T_date]
    rs_t = {
        "rs_ratio":    float(ts.rs_ratio_s.iloc[full_idx]),
        "rs_52w_high": float(ts.rs_52wh_s.iloc[full_idx]),
        "rs_blue_dot": bool(ts.rs_ratio_s.iloc[full_idx] >= ts.rs_52wh_s.iloc[full_idx] * (1.0 - RS_BLUE_DOT_TOLERANCE_PCT)),
        "rs_score":    float(ts.rs_score_s.iloc[full_idx]),
        "spy_3m":      float(ts.spy_3m_s.iloc[full_idx]),
    }

    if ts.params is not None:
        # Scored mode: PULLBACK via scan_pullback_scored
        if "PULLBACK" in setup_types:
            from engines.engine3 import scan_pullback_scored as _sps
            pb_setup, pb_score = _sps(ts.ticker, df_slice, ts.sr_zones_cache, ts.params,
                                      rs_score=float(rs_t["rs_score"]))
            if pb_setup is not None:
                # VCP co-signal boost (same logic as BacktestEngine.run())
                try:
                    from engines.engine2 import scan_vcp
                    vcp_setup = scan_vcp(ts.ticker, df_slice, spy_slice, ts.sr_zones_cache)
                    if vcp_setup is not None:
                        from constants import VCP_COSIGNAL_BOOST
                        pb_score = min(100, pb_score + VCP_COSIGNAL_BOOST)
                except Exception:
                    pass
                pb_setup["_final_score"] = pb_score
                return pb_setup
        # Other setup types in scored mode
        non_pb = [s for s in setup_types if s != "PULLBACK"]
        if non_pb:
            return _detect_signals(ts.ticker, df_slice, spy_slice, ts.sr_zones_cache,
                                   rs_t, non_pb, ts.params)
        return None
    else:
        # Legacy mode
        return _detect_signals(ts.ticker, df_slice, spy_slice, ts.sr_zones_cache,
                               rs_t, setup_types, None)
```

---

## backend/backtest_engine.py changes

### New: BacktestEngine.prepare()

```python
async def prepare(self, shared_spy_df: Optional[pd.DataFrame] = None) -> Optional["TickerSimState"]:
    """
    Fetch and pre-compute all data for this ticker. Returns a TickerSimState
    ready for use in run_portfolio_backtest_universe().

    Preserves WFO compatibility: if self.ticker_df and self.spy_df are already
    set (pre-loaded by WFO), uses them directly without re-fetching.

    Returns None if data fetch fails.
    """
    # ── 1. Fetch or use preloaded data ────────────────────────────────────
    if self.ticker_df is not None and self.spy_df is not None:
        ticker_df = self.ticker_df
        spy_df    = self.spy_df
    else:
        ticker_df, spy_df_fetched = await _fetch_data(self.ticker, self.start_date)
        spy_df = shared_spy_df if shared_spy_df is not None else spy_df_fetched
        if ticker_df is None or spy_df is None:
            return None

    # ── 2. Price column identification ────────────────────────────────────
    adj_col = "Adj Close" if "Adj Close" in ticker_df.columns else "Close"

    # ── 3. SR zones ───────────────────────────────────────────────────────
    from engines.engine1 import calculate_sr_zones as _calc_sr_zones
    sr_zones_cache = _calc_sr_zones(self.ticker, ticker_df)

    # ── 4. Indicator columns ──────────────────────────────────────────────
    if "_EMA8" not in ticker_df.columns:
        ticker_df = ticker_df.copy()
        _c = ticker_df[adj_col]
        _h = ticker_df["High"]
        _l = ticker_df["Low"]
        ticker_df["_EMA8"]    = _ema(_c, 8)
        ticker_df["_EMA20"]   = _ema(_c, 20)
        ticker_df["_SMA50"]   = _sma(_c, 50)
        ticker_df["_SMA200"]  = _sma(_c, 200)
        ticker_df["_ATR14"]   = _atr(_h, _l, _c, 14)
        ticker_df["_CCI20"]   = _cci(_h, _l, _c, 20)
        if "Volume" in ticker_df.columns:
            ticker_df["_VOLSMA50"] = ticker_df["Volume"].rolling(50, min_periods=10).mean()

    ema20_full = ticker_df["_EMA20"]
    atr14_full = ticker_df["_ATR14"] if "_ATR14" in ticker_df.columns else None

    # ── 5. RS series ──────────────────────────────────────────────────────
    _close_s     = ticker_df[adj_col]
    _spy_adj     = "Adj Close" if "Adj Close" in spy_df.columns else "Close"
    _spy_aligned = spy_df[_spy_adj].reindex(ticker_df.index, method="ffill").fillna(0.0)
    _mask        = _spy_aligned > 0
    _rs_ratio_s  = pd.Series(0.0, index=ticker_df.index)
    _rs_ratio_s[_mask] = _close_s[_mask] / _spy_aligned[_mask]
    _rs_52wh_s   = _rs_ratio_s.rolling(252, min_periods=1).max()
    _PERIODS = [63, 126, 189, 252]
    _WEIGHTS = [0.40, 0.20, 0.20, 0.20]
    _rs_score_s = pd.Series(0.0, index=ticker_df.index)
    _rs_wt_s    = pd.Series(0.0, index=ticker_df.index)
    for _p, _w in zip(_PERIODS, _WEIGHTS):
        _tk_ret  = _close_s / _close_s.shift(_p) - 1.0
        _spy_ret = _spy_aligned / _spy_aligned.shift(_p) - 1.0
        _valid   = ~(_tk_ret.isna() | _spy_ret.isna() | ~_mask)
        _rs_score_s += _w * (_tk_ret.where(_valid, 0.0) - _spy_ret.where(_valid, 0.0))
        _rs_wt_s    += _w * _valid.astype(float)
    _rs_score_s = (_rs_score_s / _rs_wt_s.replace(0.0, np.nan)).fillna(0.0)
    _spy_3m_s = (_spy_aligned / _spy_aligned.shift(63) - 1.0).fillna(0.0)

    from portfolio_backtest import TickerSimState
    return TickerSimState(
        ticker=self.ticker,
        ticker_df=ticker_df,
        spy_df=spy_df,
        adj_col=adj_col,
        ticker_dates=ticker_df.index,
        ema20_full=ema20_full,
        atr14_full=atr14_full,
        sr_zones_cache=sr_zones_cache,
        rs_ratio_s=_rs_ratio_s,
        rs_52wh_s=_rs_52wh_s,
        rs_score_s=_rs_score_s,
        spy_3m_s=_spy_3m_s,
        params=self.params,
    )
```

### Updated: BacktestEngine.run()

`run()` calls `prepare()` internally to avoid duplicating the data-loading logic:

```python
async def run(self) -> BacktestSummary:
    state = await self.prepare()   # sections 1–3 now live in prepare()
    if state is None:
        return compute_metrics(self.ticker, "+".join(self.setup_types),
                               self.start_date, self.end_date, [], self.run_id)
    # sections 4–5 (replay loop) unchanged — use state.ticker_df, state.spy_df, etc.
    ticker_df        = state.ticker_df
    spy_df           = state.spy_df
    adj_col          = state.adj_col
    sr_zones_cache   = state.sr_zones_cache
    ema20_full       = state.ema20_full
    _rs_ratio_s      = state.rs_ratio_s
    _rs_52wh_s       = state.rs_52wh_s
    _rs_score_s      = state.rs_score_s
    _spy_3m_s        = state.spy_3m_s
    # ... rest of run() unchanged
```

WFO compatibility is preserved because `prepare()` checks `self.ticker_df is not None`
before fetching — WFO pre-loads `ticker_df` and `spy_df` on the engine instance, and
`prepare()` uses them directly without re-fetching.

---

## backend/main.py changes

### Request model

```python
class BacktestRunRequest(BaseModel):
    start_date:    str           = Field(default_factory=lambda: BACKTEST_DIAG_START_DATE)
    end_date:      str           = Field(default_factory=lambda: BACKTEST_DIAG_END_DATE)
    max_positions: int           = 4
    ticker_count:  Optional[int] = None
    min_score:     float         = 0.0
    setup_types:   List[str]     = Field(default_factory=lambda: [
        "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"
    ])
```

### Endpoint update

```python
@app.post("/api/diagnostics/backtest/run", status_code=202)
async def run_backtest_diagnostics(
    background_tasks: BackgroundTasks,
    req: BacktestRunRequest = Body(default=BacktestRunRequest()),
):
```

Using `Body(default=BacktestRunRequest())` ensures no body (or missing `Content-Type`) still
works — FastAPI uses the default instance. The frontend always sends a JSON body after this
change, so the two are deployed atomically.

Ticker list:
```python
all_tickers = list(ACTIVE_UNIVERSE) if ACTIVE_UNIVERSE else list(SCAN_UNIVERSE)
tickers = all_tickers[:req.ticker_count] if req.ticker_count else all_tickers
```

Calls `run_portfolio_backtest_universe(tickers, config, params=BacktestParams(), progress_cb=_progress)`.

Result metadata:
```python
report = {
    "generated_at":   ...,
    "start_date":     req.start_date,
    "end_date":       req.end_date,
    "max_positions":  req.max_positions,
    "tickers_run":    len(tickers),
    "setup_types":    req.setup_types,
    "min_score":      req.min_score,
    "total_trades":   len(adapted),
    ...
}
```

---

## frontend/src/components/DiagnosticsTab.jsx changes

### Config state

```jsx
const [btConfig, setBtConfig] = useState({
  startYear:    2017,
  endYear:      2025,
  maxPositions: 4,
  tickerCount:  null,
  minScore:     0,
  setupTypes:   ['PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE'],
})
```

Year dropdowns range 2015–2025.

### Config panel UI

Compact config section above the "Run Backtest" button:

```
[2017 ▼] → [2025 ▼]   Positions [4]   Universe [Full (~700) ▼]   Min Score [0]

  [✓] PULLBACK  [✓] BASE  [✓] RES_BREAKOUT  [✓] HTF  [✓] LCE

                        [ RUN FULL SYSTEM BACKTEST ]
```

Universe dropdown values: `null` → "Full (~700)", `200` → "Top 200", `100` → "Top 100", `50` → "Top 50".

### API call

```js
await fetch('/api/diagnostics/backtest/run', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    start_date:    `${btConfig.startYear}-01-01`,
    end_date:      `${btConfig.endYear}-12-31`,
    max_positions: btConfig.maxPositions,
    ticker_count:  btConfig.tickerCount,
    min_score:     btConfig.minScore,
    setup_types:   btConfig.setupTypes,
  }),
})
```

### Label fix

```jsx
// Before:
{src === 'live' ? 'Live Trades' : 'Backtest (V4 baseline)'}

// After:
{src === 'live' ? 'Live Trades' : 'Full System Backtest'}
```

Result sub-header shows config used:
```jsx
{src === 'backtest' && backtestData && (
  <span style={{ color: 'var(--muted)', fontSize: 11, fontFamily: 'monospace' }}>
    {backtestData.start_date} → {backtestData.end_date}
    · {backtestData.tickers_run} tickers
    · max {backtestData.max_positions} positions
  </span>
)}
```

---

## Testing Checklist

**Portfolio cap:**
- [ ] With max_positions=2 and 100+ tickers, never more than 2 simultaneous open positions
- [ ] When a trade exits on day T, a new signal can enter on the same day T (freed before collection)
- [ ] Highest-score signal fills first when multiple fire on the same day
- [ ] Tickers with no bar on T_date are skipped for advance and signal collection

**Config UI:**
- [ ] Changing year range uses selected dates in API call
- [ ] Ticker count = 50 sends ticker_count=50; full = sends null
- [ ] Unchecking a setup type removes it from results
- [ ] Min score = 70 produces fewer trades than min score = 0

**Regression:**
- [ ] `BacktestEngine.run()` still produces identical results to before (calls prepare() internally)
- [ ] WFO path unaffected — prepare() short-circuits when ticker_df/spy_df pre-loaded
- [ ] Label shows "Full System Backtest" not "V4 baseline"
- [ ] Result metadata includes start_date, end_date, max_positions

---

## Files Summary

| Action | File |
|--------|------|
| Create | `backend/portfolio_backtest.py` |
| Modify | `backend/backtest_engine.py` |
| Modify | `backend/main.py` |
| Modify | `frontend/src/components/DiagnosticsTab.jsx` |
