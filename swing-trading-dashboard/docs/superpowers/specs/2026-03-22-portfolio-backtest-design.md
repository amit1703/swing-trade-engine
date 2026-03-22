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
    start_date:    str       = "2017-01-01"
    end_date:      str       = "2024-12-31"
    max_positions: int       = 4
    ticker_count:  Optional[int]   = None   # None = full universe
    min_score:     float     = 0.0
    setup_types:   List[str] = field(default_factory=lambda: [
        "PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"
    ])
```

### TickerSimState

Frozen data object produced by `BacktestEngine.prepare()`. Holds everything needed to
detect signals and advance trades for one ticker without re-fetching:

```python
@dataclass
class TickerSimState:
    ticker:          str
    ticker_df:       pd.DataFrame   # full df with pre-computed indicator columns
    spy_df:          pd.DataFrame   # shared SPY df (same object across all tickers)
    adj_col:         str            # "Adj Close" or "Close"
    all_dates:       pd.DatetimeIndex
    ema20_full:      pd.Series
    atr14_full:      pd.Series
    sr_zones_cache:  list
    rs_ratio_s:      pd.Series
    rs_52wh_s:       pd.Series
    rs_score_s:      pd.Series
    spy_3m_s:        pd.Series
    regime_label_s:  pd.Series
    # mutable runtime state (reset before each portfolio run)
    is_in_trade:     bool           = False
    last_close_date: Optional[date] = None
```

### run_portfolio_backtest_universe()

```python
async def run_portfolio_backtest_universe(
    tickers: List[str],
    config: BacktestConfig,
    progress_cb=None,
) -> List[dict]:
```

**Phase 1 — Parallel data loading (concurrent, semaphore-gated):**

1. Fetch SPY once — shared across all ticker states
2. For each ticker, call `engine.prepare(spy_df)` concurrently (semaphore = `CONCURRENCY_LIMIT`)
3. Collect successful `TickerSimState` objects; skip failures silently
4. Update progress callback after each ticker loads

**Phase 2 — Coordinated day-by-day replay:**

```
union_dates = sorted union of all ticker date indices, filtered to [start_date, end_date]
open_positions = []       # list of {trade_state, ticker_state} dicts, max = config.max_positions
completed_trades = []

for T_date in union_dates:

    # Step 1: advance all open positions
    still_open = []
    for pos in open_positions:
        closed, exit_price, exit_reason = _manage_open_trade(pos["trade_state"], bar_for(pos, T_date))
        if closed:
            completed_trades.append(build_trade_record(pos, T_date, exit_price, exit_reason))
            pos["ticker_state"].is_in_trade = False
            pos["ticker_state"].last_close_date = T_date.date()
        else:
            still_open.append(pos)
    open_positions = still_open

    # Step 2: check available slots
    available = config.max_positions - len(open_positions)
    if available <= 0:
        continue

    # Step 3: resolve regime — skip signal collection if DEFENSIVE
    current_regime = resolve_regime(T_date, spy_state)
    if current_regime == "DEFENSIVE":
        continue

    # Step 4: collect signals from all free tickers
    candidates = []
    for ts in ticker_states:
        if ts.is_in_trade:
            continue
        if not has_next_bar(ts, T_date):          # need T+1 open for entry price
            continue
        signal = _detect_signals_for_date(ts, T_date, config.setup_types)
        if signal is None:
            continue
        score = signal.get("_final_score") or 0.0
        if score < config.min_score:
            continue
        candidates.append((score, signal, ts))

    # Step 5: fill slots — best score first
    candidates.sort(key=lambda x: -x[0])
    for score, signal, ts in candidates[:available]:
        next_idx = ts.all_dates.get_loc(T_date) + 1
        entry_price = float(ts.ticker_df["Open"].iloc[next_idx])
        open_positions.append(build_open_position(signal, ts, T_date, entry_price))
        ts.is_in_trade = True

# Step 6: force-close any positions still open at end_date
for pos in open_positions:
    completed_trades.append(close_at_end(pos))
    pos["ticker_state"].is_in_trade = False

return completed_trades
```

**Key behaviours:**
- One position per ticker at a time (enforced by `ts.is_in_trade`)
- No cross-day queuing — signals either fill on their day or are skipped entirely
- Regime gate applies to new entries only — existing open trades run to their natural exit
- Cooldown per ticker: reuses `last_close_date` on `TickerSimState`
- `_manage_open_trade` is reused unchanged from `backtest_engine.py`

---

## backend/backtest_engine.py changes

### New: BacktestEngine.prepare()

```python
async def prepare(self, shared_spy_df: Optional[pd.DataFrame] = None) -> Optional[TickerSimState]:
```

Extracts sections 1–3 of the current `run()` method:
1. Fetch ticker data (or use `self.ticker_df` if pre-loaded)
2. Use `shared_spy_df` if provided, otherwise fetch SPY
3. Compute indicator columns (_EMA8, _EMA20, _SMA50, _SMA200, _ATR14, _CCI20, _VOLSMA50)
4. Compute RS series (rs_ratio_s, rs_52wh_s, rs_score_s, spy_3m_s)
5. Compute SR zones cache
6. Compute regime label series from SPY
7. Return `TickerSimState`; return `None` on data failure

`run()` is updated to call `prepare()` internally — no duplication, no behaviour change.

### New module-level helper: _detect_signals_for_date()

```python
def _detect_signals_for_date(
    ts: TickerSimState,
    T_date: pd.Timestamp,
    setup_types: List[str],
    params: Optional[BacktestParams] = None,
) -> Optional[dict]:
```

Wraps the existing `_detect_signals()` call inside the replay loop.
Constructs `df_slice = ts.ticker_df.iloc[:full_idx+1]` and delegates to `_detect_signals()`.
Returns signal dict or None. No side effects, no trade state mutation.

---

## backend/main.py changes

### Request model

```python
class BacktestRunRequest(BaseModel):
    start_date:    str            = Field(default_factory=lambda: BACKTEST_DIAG_START_DATE)
    end_date:      str            = Field(default_factory=lambda: BACKTEST_DIAG_END_DATE)
    max_positions: int            = 4
    ticker_count:  Optional[int]  = None
    min_score:     float          = 0.0
    setup_types:   List[str]      = ["PULLBACK", "BASE", "RES_BREAKOUT", "HTF", "LCE"]
```

### Endpoint update

`POST /api/diagnostics/backtest/run` gains an optional body (`BacktestRunRequest`).
No body = all defaults (backward compatible with any existing callers).

Ticker list selection:
```python
all_tickers = list(ACTIVE_UNIVERSE) if ACTIVE_UNIVERSE else list(SCAN_UNIVERSE)
if req.ticker_count:
    tickers = all_tickers[:req.ticker_count]
else:
    tickers = all_tickers
```

Calls `run_portfolio_backtest_universe(tickers, config, progress_cb)` instead of
`run_backtest_universe`.

Result metadata updated:
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

### Config state (added to component)

```jsx
const [btConfig, setBtConfig] = useState({
  startYear:    2017,
  endYear:      2024,
  maxPositions: 4,
  tickerCount:  null,   // null = full universe
  minScore:     0,
  setupTypes:   ['PULLBACK', 'BASE', 'RES_BREAKOUT', 'HTF', 'LCE'],
})
```

### Config panel UI

Rendered above the "Run Backtest" button. Compact single-row layout on desktop,
wraps on mobile. Uses existing dashboard styling (monospace font, dark bg):

```
[2017 ▼] → [2024 ▼]   Positions [4]   Universe [Full (~700) ▼]   Min Score [0]

  [✓] PULLBACK  [✓] BASE  [✓] RES_BREAKOUT  [✓] HTF  [✓] LCE

                        [ RUN BACKTEST ]
```

Dropdowns for start/end year: 2015–2024.
Universe dropdown: `Full (~700)` (null) / `Top 200` / `Top 100` / `Top 50`.

### API call update

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

`DiagnosticsTab.jsx` line 342:
```jsx
// Before:
{src === 'live' ? 'Live Trades' : 'Backtest (V4 baseline)'}

// After:
{src === 'live' ? 'Live Trades' : 'Full System Backtest'}
```

Result header shows config used:
```jsx
{src === 'backtest' && backtestData && (
  <span style={{ color: 'var(--muted)', fontSize: 11 }}>
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
- [ ] When a trade exits on day T, a new signal can enter on the same day T (slot freed before signal collection)
- [ ] Highest-score signal fills first when multiple fire on the same day

**Config UI:**
- [ ] Changing year range and running uses the selected dates
- [ ] Ticker count = 50 sends ticker_count=50 to API; full = sends null
- [ ] Unchecking a setup type removes it from results entirely
- [ ] Min score = 70 produces fewer trades than min score = 0

**Regression:**
- [ ] `BacktestEngine.run()` still works identically for per-ticker WFO use cases
- [ ] Label shows "Full System Backtest" not "V4 baseline"
- [ ] Result metadata shows start_date, end_date, max_positions in response

---

## Files Summary

| Action | File |
|--------|------|
| Create | `backend/portfolio_backtest.py` |
| Modify | `backend/backtest_engine.py` |
| Modify | `backend/main.py` |
| Modify | `frontend/src/components/DiagnosticsTab.jsx` |
