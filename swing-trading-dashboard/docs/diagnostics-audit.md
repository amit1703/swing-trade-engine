# Diagnostics Page Audit

## 3 Sources (Tab Toggle)

The page has three modes — **Live**, **Full System Backtest**, and **IS/OOS Split** — controlled by a `source` state that switches the API endpoint.

---

## 1. Live Tab (`/api/diagnostics/report`)

Pulls **closed trades from the portfolio** (SQLite `trades` table, up to 10,000). For each trade, it does a **retrospective regime lookup** — binary-searches the scan history to find the regime at the time of entry, so regime bucketing is accurate even for old trades.

Returns 6 sections:

| Section | What it shows |
|---|---|
| **Summary cards** | Total trades, Profit Factor, Win Rate, Avg R, Expectancy, Max Drawdown |
| **Equity Curve** | Cumulative R-multiple line chart (lightweight-charts, synthetic dates starting 2020-01-01) |
| **Setup Breakdown** | Per-setup-type table: Trades, Win%, Profit Factor, Avg R, Expectancy, Max DD. ⚠ warning if <20 trades |
| **Ticker Distribution** | Top 20 tickers by absolute R contribution, horizontal bar chart |
| **Regime Performance** | AGGRESSIVE / SELECTIVE / DEFENSIVE / UNKNOWN cards — Trades, Win Rate, Avg R, Expectancy |

**Note:** `regime_score` from analytics is `None` for live trades (regime is enriched from scan history, not stored per-trade).

---

## 2. Full System Backtest (`/api/diagnostics/backtest/run` → `/api/diagnostics/backtest`)

### What it does
- Runs `run_portfolio_backtest_universe()` (from `portfolio_backtest.py`) over the full 700-ticker universe
- **Two-phase** execution, polled every 3s:
  - **Phase 1:** Parallel signal generation per ticker (fast)
  - **Phase 2:** Sequential day-by-day portfolio simulation (slow, can't be parallelized — enforces global `max_positions` cap)
- Result cached atomically to `cache/backtest_diagnostics.json` via `tempfile + os.replace()`

### Configurable params (in UI)

| Param | Default | Options |
|---|---|---|
| Date range | 2017 → 2024 | Start: 2015–2022, End: 2021–2025 |
| Max positions | 4 | 1–20 |
| Min score | 0 | 0–100 |
| Ticker count | Full (~700) | 50 / 100 / 200 / Full |
| Setup types | PULLBACK, BASE, RES_BREAKOUT, HTF, LCE | checkboxes |

### Important differences vs live scanner

- No ≥70 score gate (unless you set `minScore > 0`)
- No hot-sector injection
- Regime uses only 4/7 factors (softer threshold — 40 pts max on f1–f4)
- RS rank gate disabled in both
- Higher trade count, lower average quality floor

**Displays same sections as Live** (summary cards, equity curve, setup breakdown, ticker distribution, regime performance).

**Trade adapter:** `initial_stop → stop_loss`, `exit_price → close_price`, `regime` passed through from trade record, `status = "closed"`.

---

## 3. IS/OOS Split (`/api/diagnostics/isoos/run` → `/api/diagnostics/isoos`)

### What it does
- Runs **two sequential** portfolio backtests — IS period first, then OOS period
- Same `run_portfolio_backtest_universe()` engine, same filters
- Cached to `cache/isoos_diagnostics.json`

### Configurable params

| Param | Default |
|---|---|
| IS window | 2017 → 2021 |
| OOS window | 2022 → 2024 |
| Max positions | 4 |
| Min score | 0 |
| Setup types | PULLBACK, BASE, RES_BREAKOUT, HTF, LCE |

### UI shows
- **Comparison table** — IS vs OOS side by side: Win Rate, Profit Factor, Avg R, Max DD, Trades
- **Delta row** — OOS − IS for each metric, color-coded green/red
- **Collapsible IS breakdown** — per-setup-type table (blue header)
- **Collapsible OOS breakdown** — per-setup-type table (orange header)

**Purpose:** Detect overfitting — if IS metrics are much better than OOS, the strategy parameters are curve-fitted.

---

## Analytics Engine (`analytics.py`)

All computation is in pure functions, no DB/FastAPI imports:

| Function | Computes |
|---|---|
| `compute_live_diagnostics()` | Win rate, Avg R, Expectancy, Profit Factor, Max Drawdown, Equity Curve |
| `compute_setup_breakdown()` | Per-setup metrics + `low_sample` flag (< `LOW_SAMPLE_THRESHOLD`) |
| `compute_ticker_distribution()` | R contribution ranked, sorted by abs(total R) |
| `compute_regime_performance()` | Metrics per AGGRESSIVE/SELECTIVE/DEFENSIVE/UNKNOWN bucket |
| `compute_selective_breakdown()` | SELECTIVE regime only — classifies each setup as STRONG/WEAK/INSUFFICIENT_DATA, simulates before/after filter, suggests `SELECTIVE_SETUP_WEIGHTS` values |
| `compute_regime_stability()` | Flip count, flip rate/month, avg regime duration — from scan history. Ignores single-scan blips |

**R-multiple formula:** `(exit - entry) / (entry - stop)`. Open trades and trades with missing `close_price` are excluded silently.

---

## Key State & Polling

- Backtest: polls `/api/diagnostics/backtest/status` every **3 seconds** while `btRunning`
- IS/OOS: polls `/api/diagnostics/isoos/status` every **3 seconds** while `ioRunning`
- Both show a progress bar (done/total), phase label, and explanation text
- Re-running keeps existing data visible while new run proceeds
- 409 returned if a run is already in progress (prevents double-triggers)

---

## Known Issues / Notes

1. **`regime_score` vs `regime`** — Live diagnostics enrich regime via binary search on scan history. Backtest trades carry `regime` directly from `TradeRecord` but `regime_score = None`, so all backtest trades land in `UNKNOWN` in `compute_regime_performance` unless `portfolio_backtest.py` sets the `regime` field on each trade.

2. **Equity curve uses synthetic dates** starting `2020-01-01`, one per trade — it is not time-aligned to real trade dates.

3. **Setup types excluded by default:** `VCP` is not in the default backtest setup type list. Consistent with VCP being a bonus score signal, not directly traded.

4. **IS/OOS missing sections** — IS/OOS responses only include `summary` and `setup_breakdown` per period. `ticker_distribution` and `regime_performance` are not computed or displayed for IS/OOS.

5. **`selective_analysis` not rendered** — computed in both Live and Full Backtest responses (`compute_selective_breakdown()`) but `DiagnosticsTab.jsx` never reads `data?.selective_analysis`. The data exists in the API response but is silently dropped on the frontend.
