# V5 Strategy Design — 2026-03-10

## Overview

Evolutionary improvement over V4. Core architecture (scanner, ranking, RS filtering, liquidity gating, setup detection) is preserved unchanged. V5 targets: exit efficiency, diagnostic visibility, and analytical transparency.

---

## 1. Setup-Specific Exit Logic

### Constants (`backend/constants.py`)

Four new ATR multiplier constants replace the single shared `TRAIL_ATR_MULT`:

```python
VCP_TRAIL_ATR_MULT          = 2.0    # tight trail — VCP breakouts move fast
PULLBACK_TRAIL_ATR_MULT     = 3.0    # moderate trail — trending but less explosive
RES_BREAKOUT_TRAIL_ATR_MULT = 4.25   # wide trail — breakouts need room to trend
BASE_TRAIL_ATR_MULT         = 4.162  # unchanged from existing TRAIL_ATR_MULT
```

`TRAIL_ATR_MULT` retained as fallback default for unknown setup types.

### Trail Formula (`backend/main.py` — `_enrich_trade()`)

```python
_TRAIL_ATR_BY_TYPE = {
    "VCP":          VCP_TRAIL_ATR_MULT,
    "PULLBACK":     PULLBACK_TRAIL_ATR_MULT,
    "RES_BREAKOUT": RES_BREAKOUT_TRAIL_ATR_MULT,
    "BASE":         BASE_TRAIL_ATR_MULT,
}
atr_mult      = _TRAIL_ATR_BY_TYPE.get(setup_type, TRAIL_ATR_MULT)
ema20_floor   = l20                                    # EMA20 structural trend floor
atr_trail     = current_price - (atr_mult * current_atr)
raw_trail     = max(atr_trail, ema20_floor)            # Option B: ATR floored by EMA20
trailing_stop = max(float(trade["stop_loss"]), raw_trail)  # ratchet: never loosen
```

`setup_type` read from trade metadata JSON (already stored for all setup types).

### Ratchet Guarantee

`max(original_stop, raw_trail)` ensures the trailing stop never moves downward regardless of ATR fluctuation or EMA20 dips.

---

## 2. Market Regime Filter — No Code Change

The V5 Optuna diagnostics show a quality inflection near regime_score ≈ 59. This is already enforced by the scoring system — no hard gate needed.

**Comment added to `constants.py`** documenting:
- `REGIME_SELECTIVE_THRESHOLD = 40` and `REGIME_AGGRESSIVE_THRESHOLD = 70` define scoring tiers
- SELECTIVE regime earns ~53% of AGGRESSIVE regime points (`SCORE_SELECTIVE_REGIME_FACTOR = 0.53`)
- `MIN_SETUP_SCORE = 70` filters out low-regime setups as a downstream consequence
- Together these produce the effective quality inflection observed near regime_score ≈ 59 in Optuna diagnostics

No threshold constants changed. Soft scoring effect preserved over hard cutoff.

---

## 3. `analytics.py` — Live Diagnostics Module

### Location

`swing-trading-dashboard/backend/analytics.py` — new file.

### Data Contract

All functions accept `trades: list[dict]` matching the shape returned by `get_all_trades()` from `database.py`. Key fields used:

- `entry_price`, `stop_loss`, `close_price` — for R-multiple calculation
- `status` — `"OPEN"` | `"CLOSED"` (only CLOSED trades used for realized metrics)
- `setup_type` — for breakdown grouping
- `ticker` — for distribution grouping
- `regime_score` (from metadata JSON, optional) — for regime performance bucketing

### R-Multiple

```python
risk = entry_price - stop_loss
r    = (close_price - entry_price) / risk   # positive = win, negative = loss
```

### Public Functions

#### `compute_live_diagnostics(trades) -> dict`

```python
{
    "total_trades":   int,
    "profit_factor":  float | None,   # None if no losing trades
    "win_rate":       float,          # 0.0–1.0
    "avg_R":          float,
    "expectancy":     float,          # win_rate * avg_win_R + loss_rate * avg_loss_R
    "max_drawdown":   float,          # peak-to-trough in cumulative R
    "equity_curve_R": list[float],    # cumulative R sequence for charting
}
```

#### `compute_setup_breakdown(trades) -> dict`

```python
{
    "VCP": {
        "trades":         int,
        "win_rate":       float,
        "profit_factor":  float | None,
        "avg_R":          float,
        "expectancy":     float,
        "max_drawdown":   float,
        "low_sample":     bool,       # True if trades < 20
    },
    "PULLBACK": { ... },
    "RES_BREAKOUT": { ... },
    "BASE": { ... },
}
```

#### `compute_ticker_distribution(trades) -> list[dict]`

```python
[
    {
        "ticker":           str,
        "trade_count":      int,
        "total_pnl":        float,    # sum of realized R across trades
        "pct_contribution": float,    # ticker total_pnl / abs(portfolio total_pnl)
    },
    ...  # sorted descending by abs(pct_contribution)
]
```

#### `compute_regime_performance(trades) -> dict`

Three buckets matching existing tiers:

```python
{
    "AGGRESSIVE": { "trades": int, "win_rate": float, "avg_R": float },
    "SELECTIVE":  { "trades": int, "win_rate": float, "avg_R": float },
    "DEFENSIVE":  { "trades": int, "win_rate": float, "avg_R": float },
}
```

Regime score bucketing: AGGRESSIVE ≥70, SELECTIVE 40–69, DEFENSIVE <40. Trades without regime_score go into `"UNKNOWN"` bucket.

### Backtest Interface

No imports of `database.py`, `main.py`, or any FastAPI types inside `analytics.py`. A future backtest engine passes simulated trade dicts with the same shape — no changes to analytics layer needed.

---

## 4. Enhanced `/api/analyze/{ticker}`

### New Response Fields

Added alongside existing `verdict`, `narrative`, `signals`, `verdict_color`, `quality`:

| Field | Type | Source |
|---|---|---|
| `detected_setup` | `str \| null` | `scan_setups` DB, latest scan for ticker |
| `setup_quality_score` | `int \| null` | `setup_score` from DB setup record (0–100) |
| `rs_rank` | `float \| null` | `rs_rank` from setup metadata JSON |
| `regime_alignment` | `"STRONG" \| "MODERATE" \| "WEAK"` | Current regime vs setup type requirements |
| `entry_quality` | `"IDEAL" \| "ACCEPTABLE" \| "EXTENDED"` | Derived from `distance_pct`, `volume_ratio`, `rs_blue_dot` |
| `price_risk_pct` | `float \| null` | `(entry - stop) / entry` |
| `risk_level` | `"LOW" \| "MODERATE" \| "HIGH"` | Derived from `price_risk_pct` (<2% / 2–4% / >4%) |
| `reject_reasons` | `list[str]` | All blocking conditions (empty list if setup is valid) |

### Regime Alignment Mapping

- AGGRESSIVE + any setup → `"STRONG"`
- SELECTIVE + any setup → `"MODERATE"`
- DEFENSIVE → `"WEAK"` regardless of setup

### Entry Quality Mapping

- `distance_pct < 1%` AND `volume_ratio > 1.5` AND `rs_blue_dot` → `"IDEAL"`
- `distance_pct < 3%` OR `volume_ratio > 1.0` → `"ACCEPTABLE"`
- Otherwise → `"EXTENDED"`

### `reject_reasons` Logic (all conditions checked, all failures collected)

1. RS rank < 70 → `"Weak relative strength — RS rank below minimum threshold"`
2. No setup in DB for ticker → `"No valid setup pattern detected under current strategy rules"`
3. Regime DEFENSIVE → `"Market regime is defensive — conditions do not support new entries"`
4. `setup_quality_score < 70` → `"Setup detected but score below minimum quality threshold"`

Empty list (`[]`) when no blocking conditions.

### StockIntelPanel UI Update

New structured section below existing narrative:

- RS rank badge (colored by percentile tier)
- Regime alignment chip (green/amber/red)
- Entry quality label
- Risk level indicator with `price_risk_pct` value
- `reject_reasons` rendered as amber/red bullet list when non-empty

---

## 5. Diagnostics Tab

### Backend: `/api/diagnostics/report`

New endpoint in `main.py`:

```python
@app.get("/api/diagnostics/report")
async def diagnostics_report():
    trades = await get_all_trades(DB_PATH)
    closed = [t for t in trades if t["status"] == "CLOSED"]
    return {
        "summary":            compute_live_diagnostics(closed),
        "setup_breakdown":    compute_setup_breakdown(closed),
        "ticker_distribution": compute_ticker_distribution(closed),
        "regime_performance": compute_regime_performance(closed),
    }
```

### Frontend: `DiagnosticsTab.jsx`

New component, new tab in `App.jsx` alongside SCANNER and PORTFOLIO.

**Five sections:**

1. **Summary Cards** — 6 metric cards: Total Trades, Profit Factor, Win Rate, Avg R, Expectancy, Max Drawdown

2. **Equity Curve** — Line chart of `equity_curve_R` using `lightweight-charts` (existing project dependency)

3. **Setup Breakdown Table** — columns: Setup Type / Trades / Win Rate / Profit Factor / Avg R / Expectancy / Max DD. `low_sample` flag renders a `⚠` indicator on the row.

4. **Ticker Distribution** — Ranked list: Ticker / Trade Count / Total PnL / % Contribution, sorted by contribution descending

5. **Regime Performance** — 3-column card grid: AGGRESSIVE / SELECTIVE / DEFENSIVE, each showing trades + win rate + avg R

**Empty state** — all sections show muted "No closed trade data yet" placeholder when `closed.length === 0`.

**Styling** — dark background, `text-slate-*` typography, accent colors matching setup types (blue=VCP, amber=PULLBACK, green=RES_BREAKOUT). Consistent with existing dashboard.

---

## Files Changed

| File | Change |
|---|---|
| `backend/constants.py` | Add 4 ATR trail constants; add regime inflection comment |
| `backend/analytics.py` | New file — pure analytics functions |
| `backend/main.py` | Update `_enrich_trade()` trail logic; add `/api/diagnostics/report` endpoint; enhance `/api/analyze/{ticker}` response |
| `frontend/src/App.jsx` | Add DIAGNOSTICS tab; wire up fetch |
| `frontend/src/components/DiagnosticsTab.jsx` | New component |
| `frontend/src/components/StockIntelPanel.jsx` | Add new fields section |

## Files NOT Changed

- `backend/scoring.py` — ranking system preserved
- `backend/engines/` — all 8 engines preserved
- `backend/tickers.py` — universe preserved
- `backend/indicators.py` — indicator functions preserved
- `backend/database.py` — schema unchanged (no new columns)
- `frontend/src/components/SetupTable.jsx` — unchanged
- `frontend/src/components/TradingChart.jsx` — unchanged
- `frontend/src/components/PortfolioTab.jsx` — unchanged (exit logic changes are backend only)
