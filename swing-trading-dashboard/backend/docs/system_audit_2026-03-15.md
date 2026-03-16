# System Audit — Swing Trading Dashboard
**Date:** 2026-03-15
**Optuna Trial:** #433 (frozen parameters)
**Scope:** Entry logic, exit logic, regime filter, signal ranking, portfolio management, hardcoded override findings

---

## 1. Entry Logic

### E2 — VCP (Coiled Spring / Path A only)

**Source:** `engines/engine2.py → scan_vcp()`

E2 now runs **Path A only**. All confirmed-breakout paths (B–E) were removed; Engine 6 owns confirmed breakouts.

Gates that must ALL pass:

1. **Minimum data:** `len(data) >= 60`, `close.dropna() >= 55`
2. **Trend filter (baseline):** `EMA8 > EMA20` AND `close > SMA50`
3. **Trend filter (Path A):** `close > SMA200` — strict Stage 2 requirement
4. **TR contraction:** mean TR of last 5 bars `<` mean TR of prior 20 bars
5. **ATR compression:** `ATR14_today < ATR20_avg × VCP_ATR_CONTRACTION_THRESHOLD (0.6)` — from constants.py
6. **Progressive contractions:** `contraction_count >= VCP_MIN_CONTRACTIONS_STRICT (3)` AND `is_progressive=True` — from constants.py
7. **U-shape parabola:** scipy `curve_fit` parabola over last 15 bars with `a > 0.005` and vertex in `[0, lb]`
8. **Volume dry-up:** 3-day avg volume `< avg_vol` AND at least one bar in last 10 `< 0.5 × avg_vol` (Minervini gate)
9. **Resistance proximity:** price within 5% below a KDE resistance zone
10. **Volume gate at zone:** either in dry-up phase below zone OR at breakout with vol surge `>=1.5x avg`

**Risk math:**
- `entry = round(lh × 1.001, 2)` (bar high + 0.1%)
- `stop_base = min(low, nearest_res["lower"])`
- `stop_loss = round(stop_base - ATR_STOP_MULTIPLIER × ATR14, 2)` — `ATR_STOP_MULTIPLIER=1.278` from constants.py
- `risk = entry - stop_loss` — rejected if `<= 0` or `> entry × 0.15`

**Param sources:** `ATR_STOP_MULTIPLIER`, `VCP_ATR_CONTRACTION_THRESHOLD`, `VCP_MIN_CONTRACTIONS_STRICT` all from constants.py. No BacktestParams fields govern E2 entry gates.

**Live vs backtest path:** Both use the same `scan_vcp()` function. In scored mode, VCP runs as a co-signal booster to pullback detection (adds `params.vcp_bonus = 1.370` to the pullback score) but does not generate a standalone signal.

---

### E3 — Pullback

**Source:** `engines/engine3.py → scan_pullback_scored()` (scored mode, both live and backtest)

Gates (scored mode — the only production path for backtest and live):

1. **Trend (hard gate):** `EMA8 > EMA20 AND close > SMA50` → +2 pts; or `EMA8 > EMA20 AND close > SMA50×0.97` → +1 pt; otherwise `return (None, 0.0)`
2. **Value zone (hard gate):** `low <= EMA8 OR low <= EMA20` → +2 pts; if `latr > 0` and close within `params.ema_distance (1.651)` ATR of EMA8 or EMA20 → +1 pt bonus
3. **CCI hook (hard gate):** `cci_prev < params.cci_threshold (-54.5)` AND `cci_today > cci_prev`; if `cci_prev < -100` → +2 pts, else → +1 pt
4. **Pin-bar score:** `close >= EMA20` → +2 pts; `close >= EMA20 × 0.98` → +1 pt
5. **Structural support (hard gate):** nearest support via `_find_structural_support()` — checks KDE zone, consolidation low, high-vol demand zone, ascending trendline in that priority order → +2 pts; ascending trendline → +`params.tdl_bonus (1.016)` additional pts
6. **Risk math validity:** `risk > 0 AND risk <= entry × 0.15`

Total raw score passes into scored mode weighting. Threshold applied after weighting (see Section 4).

**RS pre-gate:** Before any engine runs in scored mode (backtest line 837, main.py line 1229):
- `rs_score < params.rs_threshold (0.066)` → bar is skipped entirely

**Module-level RS gate (legacy paths only):** `RS_REJECT_THRESHOLD = -0.01219` in engine3.py is used only by `scan_pullback()` and `scan_relaxed_pullback()` — not by `scan_pullback_scored()`. This is intentional; see Section 6.

**Stop formula:**
- `stop_base = min(low, nearest_sup["lower"])`
- `stop_loss = round(stop_base - ATR_STOP_MULTIPLIER × ATR14, 2)` — `ATR_STOP_MULTIPLIER=1.278` from constants.py

**Live vs backtest path:** Both route through `scan_pullback_scored()` with the same `_LIVE_PARAMS`/`params` object (BacktestParams defaults). The live scanner also runs `scan_relaxed_pullback()` as a fallback when the scored path fails, but backtest does NOT; backtest only runs `scan_pullback_scored()` in scored mode.

---

### E5 — Base Pattern (Flat Base / Cup & Handle)

**Source:** `engines/engine5.py → scan_base_pattern()` dispatches to `scan_flat_base()` and `scan_cup_handle()`

**Params from BacktestParams (via `params` argument):**
- `params.base_vol_ratio (1.425)` — min volume ratio for BRK signal
- `params.base_quality_min (19)` — minimum quality score to keep candidate
- `params.base_stop_atr (0.2)` — stop ATR multiplier

**scan_flat_base() gates (Darvas Box):**
1. `len(data) >= 60`, `close.dropna() >= 55`
2. Stage 2: `SMA50 > SMA200 AND close > SMA50`
3. ATR14 valid
4. Volume dry-up: 5-day avg vol `< 50-day avg vol`
5. Box tightness: `box_height <= 3.5 × ATR14` (hardcoded multiplier)
6. Ceiling touches: at least 2 highs within `ceiling - 0.5 × ATR14`
7. Close in upper 25% of box
8. Signal = "BRK" if `close > ceiling AND vol_ratio >= params.base_vol_ratio AND range_contraction`; Signal = "DRY" if within 1% of ceiling; else `return None`

**scan_cup_handle() gates:**
1. `len(data) >= 60`, `close.dropna() >= 55`
2. `close > SMA200`
3. Cup depth: `0.15 <= depth <= min(0.45, atr_pct × 10)` — ATR-proportional depth ceiling
4. Peak-to-low duration `>= 25` bars
5. Right rim recovery `>= 50%` of cup depth
6. Handle `>= 5` bars
7. Price in upper 50% of cup depth
8. Handle ATR `< decline-phase ATR` (volatility contraction)
9. Signal = "BRK" if `close > handle_high AND vol_ratio >= params.base_vol_ratio AND range_contraction`; Signal = "DRY" if within 1%; else `return None`

**Stop formula (both patterns):**
- `stop_loss = round(floor_v - params.base_stop_atr × ATR14, 2)` — flat base uses `floor_val` (box floor), cup uses `handle_low_price`

**Quality score (0–100):** Computed from 4 factors × 25 pts each: RS vs SPY outperformance, tightness, volume dry-up, RS blue dot. Candidate must pass `params.base_quality_min (19)` or it is dropped before returning.

**Live vs backtest path:** Same `scan_base_pattern()` with `_LIVE_PARAMS`/`params` passed. Identical code path.

---

### E6 — Resistance Breakout

**Source:** `engines/engine6.py → scan_resistance_breakout()`

**Params from BacktestParams (via `params` argument using `getattr` with fallbacks):**
- `params.brk_vol_mult (3.0161)` — minimum volume multiplier (×50d avg)
- `params.brk_stop_atr (1.6675)` — stop distance from resistance in ATR units
- `params.brk_min_pct (0.04333)` — minimum close above resistance (buffer)
- `params.brk_gap_pct (0.01021)` — max close above resistance (gap ceiling in engine; T+1 open gap check in backtest)
- `params.brk_donchian_n (87)` — Donchian rolling-high lookback
- `params.brk_pivot_strength (2)` — bars each side for pivot high detection
- `params.brk_atr_expansion (1.474)` — min ATR expansion for breakout bar
- `params.brk_min_consolidation (10)` — min bars near resistance before breakout

**Module-level defaults used when params=None:**
- `_MAX_DAYS_LOOKBACK = 3` — scan last 3 bars for breakout
- `_MAX_EXTEND_PCT = 0.05` — overextension gate (hardcoded)
- `_CONSOL_TOLERANCE = 0.08` — consolidation window (hardcoded)
- `_DEDUP_THRESHOLD = 0.005` — resistance dedup threshold (hardcoded)
- `_PIVOT_HISTORY_BARS = 252` — pivot lookback (hardcoded)

**Gate sequence (per bar, per resistance candidate):**
1. `len(data) >= max(60, brk_donchian_n + 10)`
2. Trend: `close > SMA50`
3. Zone cross: `pre_close <= resistance < brk_close`
4. Breakout buffer: `brk_close >= resistance × (1 + brk_min_pct)`
5. Overextension (for aged signals): `close[-1] <= resistance × 1.05` — hardcoded `_MAX_EXTEND_PCT`
6. Volume: `vol_ratio >= brk_vol_mult`
7. ATR expansion (if `brk_atr_expansion > 0`): `bar_range / brk_atr >= brk_atr_expansion`
8. Consolidation: at least 1 close in `[brk_min_consolidation + 10]` bars prior within `resistance × (1 - 0.08)` — hardcoded tolerance
9. Gap gate (within engine): `(brk_close - resistance) / resistance <= brk_gap_pct`
10. Risk validity: `risk > 0 AND risk <= entry × 0.15`

**Stop formula:**
- `entry = round(brk_high × 1.001, 2)`
- `stop_loss = round(resistance - brk_stop_atr × latr, 2)` — uses CURRENT bar's ATR, not breakout bar's

**Take-profit (engine output):**
- `nearest_resistance_target(entry, zones, risk)` — KDE zone above entry; fallback via `TARGET_RR=4.346` in zone_utils

**Live vs backtest path:** Same `scan_resistance_breakout()` function with same params object. Identical code path.

---

## 2. Exit Logic

### Stop Loss

All stops are set at entry and managed via `_manage_open_trade()` in `backtest_engine.py`.

**Check order (per bar):**
1. `low <= trailing_stop` → fill at `trailing_stop` (exit = "STOP")
2. `high >= take_profit` → fill at `take_profit` (exit = "TARGET")
3. If still open and `close > entry_price`: update trailing stop (ratchet only up)

**Stop is checked before target** — protects against gap-down days.

### Take-Profit Formula

In **scored mode** (params is not None), the engine-computed take_profit is **overridden** in backtest_engine.py line 944–946:

```python
_risk = entry_price - stop_loss
take_profit = round(entry_price + self.params.tp_multiple * _risk, 2)
```

`params.tp_multiple = 4.3458` (Optuna trial #433). This is the **only** source for the take-profit in production backtest and live modes.

In **legacy mode** (params=None), each engine's `take_profit` field is used directly. `zone_utils.nearest_resistance_target()` returns the nearest upstream KDE resistance or falls back to `entry + TARGET_RR × risk` where `TARGET_RR = 4.346` from constants.py — effectively the same value.

### Trailing Stop Rules

The trailing stop is updated in `_manage_open_trade()` at line 415–428 only when `close > entry_price`:

```python
atr_trail = close - mult × atr14
new_trail = max(ema20, atr_trail)
if new_trail > trailing_stop:
    trailing_stop = new_trail  # ratchet only — never moves down
```

**Multiplier selection logic (priority order):**

1. If `trail_mult_override` is set on the trade → use that value directly (V4 baseline audit mode)
2. Else if `params` is set AND `setup_type == "RES_BREAKOUT"` → `params.brk_trail_mult (6.9060)`
3. Else if `params` is set AND `setup_type == "BASE"` → `params.base_trail_mult (6.995)`
4. Else → look up `_TRAIL_ATR_BY_SETUP` dict for setup type:
   - `"VCP"` → `VCP_TRAIL_ATR_MULT = 2.0` (constants.py) — tight
   - `"PULLBACK"` → `PULLBACK_TRAIL_ATR_MULT = 3.0` (constants.py) — moderate
   - `"RES_BREAKOUT"` → `RES_BREAKOUT_TRAIL_ATR_MULT = 4.25` (constants.py) — this is bypassed by rule 2 above in scored mode
   - `"BASE"` → `BASE_TRAIL_ATR_MULT = 4.162` (constants.py) — bypassed by rule 3 above in scored mode
   - Any other/unknown → `TRAIL_ATR_MULT = 4.162` (constants.py fallback)

**Summary per setup type in production scored mode:**
| Setup | Trail Multiplier | Source |
|---|---|---|
| VCP | 2.0 | constants.py `VCP_TRAIL_ATR_MULT` |
| PULLBACK | 3.0 | constants.py `PULLBACK_TRAIL_ATR_MULT` |
| RES_BREAKOUT | 6.906 | `params.brk_trail_mult` (BacktestParams #433) |
| BASE | 6.995 | `params.base_trail_mult` (BacktestParams) |
| HTF / LCE | 4.162 | constants.py `TRAIL_ATR_MULT` fallback |

The trailing stop also has a **floor of EMA20**: `new_trail = max(ema20, atr_trail)`. This prevents the ATR trail from moving below the 20-day EMA even on low-ATR periods.

---

## 3. Market Regime Filter

### Regime Computation

**Live scanner:** Full 7-factor regime score via `engines/engine0.py → check_market_regime()`:
- F1: SPY close > EMA20 → 20 pts (`REGIME_WEIGHT_EMA20`)
- F2: SPY close > SMA50 → 15 pts (`REGIME_WEIGHT_SMA50`)
- F3: SMA50 > SMA200 → 15 pts (`REGIME_WEIGHT_MA_STACK`)
- F4: EMA20 slope (5-bar) → 0–10 pts (`REGIME_WEIGHT_SLOPE`)
- F5: % universe above SMA50 → 20 pts (`REGIME_WEIGHT_BREADTH`)
- F6: New 52-week highs vs lows ratio → 10 pts (`REGIME_WEIGHT_HL`)
- F7: VIX below 20-day SMA → 10 pts (`REGIME_WEIGHT_VIX`)
- Max score: 100 pts

**Live thresholds (from constants.py):**
- `REGIME_AGGRESSIVE_THRESHOLD = 70` → score 70–100 = AGGRESSIVE
- `REGIME_SELECTIVE_THRESHOLD = 59` → score 59–69 = SELECTIVE
- score < 59 = DEFENSIVE

**Backtest:** 4-factor only (F1–F4; F5/F6/F7 require live universe data). Max score: 60 pts. Proportionally scaled thresholds in `filters.py`:
- `_BACKTEST_REGIME_AGGRESSIVE = 42` (= 70/100 × 60)
- `_BACKTEST_REGIME_SELECTIVE = 24` (= 40/100 × 60)
- score < 24 = DEFENSIVE

Note: `REGIME_SELECTIVE_THRESHOLD = 59` maps to 40 pts in full system, but the backtest uses 24 (= 40/100 × 60). The comment in `filters.py` says "equiv 40/100" which is internally consistent.

**`is_bullish`** in main.py: `regime_score >= REGIME_SELECTIVE_THRESHOLD (59)`, i.e., SELECTIVE or AGGRESSIVE.

### Which Engines Are Active Per Regime

| Regime | E2 VCP | E3 Pullback | E5 Base | E6 BRK | WATCHLIST |
|---|---|---|---|---|---|
| AGGRESSIVE | Active | Active (scored) | Active | Active | Active |
| SELECTIVE | Active | Active (scored) | Active | **Skipped** (`brk_aggressive_only=True`) | Active |
| DEFENSIVE | **Skipped** | **Skipped** | Active | **Skipped** | Active |

Details:
- E2/E3 gate: `if regime["is_bullish"] or force:` — gates on `is_bullish` (SELECTIVE or AGGRESSIVE)
- E6 gate (live): `regime["regime"] == "AGGRESSIVE" or not _LIVE_PARAMS.brk_aggressive_only` — with `brk_aggressive_only=True` (default), E6 only runs in AGGRESSIVE
- E6 gate (backtest, scored mode): if `setup_type == "RES_BREAKOUT" AND _current_regime == "SELECTIVE"` AND `params.brk_aggressive_only=True` → `continue` (skip)
- DEFENSIVE backtest: `if _current_regime == "DEFENSIVE": continue` — skips all signal detection
- E5 always runs; watchlist always runs (near-breakout detection)

---

## 4. Signal Ranking and Selection

### score_threshold Gate (Scored Mode)

In backtest (`backtest_engine.py` line 919):
```python
final_score = raw_score × weight
if final_score < self.params.score_threshold:
    continue  # signal discarded
```

`params.score_threshold = 2.50` (frozen, not in Optuna search space per backtest_engine.py line 98 comment).

### How final_score Is Computed

For each signal type:

```python
is_breakout = setup_type in ("VCP", "RES_BREAKOUT", "HTF", "LCE")
is_base     = setup_type == "BASE"
weight = (
    params.breakout_weight (1.724)  if is_breakout
    else params.base_weight (3.895) if is_base
    else params.pullback_weight (1.842)   # PULLBACK
)
final_score = raw_score × weight
```

**raw_score sources:**
- PULLBACK: `scan_pullback_scored()` returns additive score (max ~14 pts without bonuses)
  - VCP co-signal adds `params.vcp_bonus = 1.370` to the pullback raw score
  - TDL support adds `params.tdl_bonus = 1.016`
- RES_BREAKOUT: `_raw_score` from engine6 (base 5.0 + volume/breakout bonuses, max ~9.8)
- VCP/BASE/HTF/LCE: `_SIGNAL_BASE_SCORES` dict (VCP=6.0, BASE=5.0, HTF=5.0, LCE=4.0) used as raw_score when no `_raw_score` field is present

**Minimum final_score to pass gate:**
- PULLBACK minimum raw_score: `2.50 / 1.842 = 1.36` (barely above minimum possible with hard gates satisfied)
- RES_BREAKOUT minimum raw_score: `2.50 / 1.724 = 1.45` (but engine6 base score is 5.0, so this never fails)
- BASE minimum raw_score: `2.50 / 3.895 = 0.64` (engine5 base is 5.0, never fails)

In practice, the `score_threshold` gate primarily filters **weak pullbacks** (low CCI conviction, no pin bar, no TDL support).

### Live Scanner Equivalent (MIN_SETUP_SCORE)

The live scanner applies a **different scoring system** via `score_and_filter_setups()` in `scoring.py`. This is the RS-rank/regime/sector/RR/volume/quality unified score (0–100), gated at `MIN_SETUP_SCORE = 70` (production). This is **not** the same as the backtest score_threshold gate.

In the live scanner, the pullback scored gate (`_LIVE_PARAMS.score_threshold = 2.50`) is applied **per-engine** (E3 line 1309) before setups enter the unified scoring pool.

### Concurrent Position Limit

In backtest (`backtest_engine.py` line 791):
```python
if len(open_trades) >= MAX_OPEN_POSITIONS:
    continue  # skip signal detection for this bar
```

`MAX_OPEN_POSITIONS = 5` (constants.py). No new signals are detected when 5 trades are already open; existing trades continue to be managed.

### cooldown_days

In backtest (`backtest_engine.py` line 803–809):
```python
if (
    self.params is not None
    and self._last_close_date is not None
    and (T_date.date() - self._last_close_date).days < self.params.cooldown_days
):
    continue
```

`params.cooldown_days = 4`. After any trade closes, the **next 4 calendar days** are blocked from new entries for that ticker. `_last_close_date` is set per-ticker per BacktestEngine instance. In the universe backtest, each ticker runs in its own BacktestEngine, so cooldown is per-ticker.

**Note:** cooldown_days is only enforced in **scored mode** (params is not None). In legacy mode it does not apply.

---

## 5. Portfolio Management

### Risk Model Constants (constants.py)

| Constant | Value | Meaning |
|---|---|---|
| `RISK_PER_TRADE_PCT` | 1.0 | Risk 1% of equity per trade (1R = 1%) |
| `MAX_POSITION_SIZE_PCT` | 20.0 | Maximum position size as % of equity |
| `MAX_OPEN_POSITIONS` | 5 | Maximum concurrent open positions |

### Position Size Computation

Computed in `TradeRecord.__post_init__()` (`backtest_engine.py` line 190–196):

```python
stop_dist_pct = (entry_price - initial_stop) / entry_price
raw_pos = RISK_PER_TRADE_PCT / stop_dist_pct   # = 1.0% / stop_distance%
position_size_pct = min(raw_pos, MAX_POSITION_SIZE_PCT)  # cap at 20%
portfolio_pnl_pct = pnl_pct × position_size_pct / 100.0
```

**Example:** Stop distance = 5% → position size = 1.0 / 0.05 = 20% (at the cap). Stop distance = 10% → 10% position. Stop distance = 2% → 50% raw, capped to 20%.

This is a **1R = 1% of equity** model. The `portfolio_pnl_pct` field is used for all portfolio metrics (equity curve, max drawdown, profit factor). The raw `pnl_pct` (price-only return) is stored separately for reference.

### Liquidity Gate (pre-signal)

Enforced per-bar before any engine runs (`filters.py → passes_liquidity()`):
- 50-day **median** volume `>= LIQUIDITY_MIN_AVG_VOLUME (750,000)`
- `last_close × median_volume_50d >= LIQUIDITY_MIN_DOLLAR_VOLUME ($25,000,000)`

### Earnings Blackout

`in_earnings_blackout()` blocks signals within `EARNINGS_BLACKOUT_DAYS = 7` calendar days before any known earnings date (range: `[-1, +7]` days from earnings).

---

## 6. Hardcoded Override Findings

The following values are hardcoded in engine or filter code and are NOT sourced from BacktestParams or constants.py. Each is rated for risk.

| Location | Hardcoded Value | Description | Rating |
|---|---|---|---|
| `engine3.py` line 386 | `EMA_DISTANCE_ATR = 0.75` | ATR proximity threshold in `scan_relaxed_pullback()` — distinct from `params.ema_distance` which controls scored mode | RISK — `scan_relaxed_pullback` is a live fallback that can produce signals diverging from the Optuna-tuned `ema_distance=1.651` |
| `engine3.py` line 99 | `ZONE_TOLERANCE = 0.025` | 2.5% tolerance for KDE zone touch in `_find_structural_support()` | OK — geometric tolerance, not optimizable |
| `engine3.py` line 135 | `_prox_pct = max(0.03, 1.2 × latr / ll)` | ATR-relative proximity for consolidation low support | OK — volatility-normalized, sensible constant |
| `engine3.py` line 156 | `1.5 × avg_vol` | Volume threshold for demand zone qualification in `_find_structural_support()` | OK — matches constants intent; not Optuna-tunable |
| `engine3.py` line 299 | `risk > entry × 0.15` | 15% max stop-loss gate | OK — hard risk limit, intentional |
| `engine6.py` line 59 | `_MAX_EXTEND_PCT = 0.05` | Overextension gate for aged signals (5% above resistance) | OK — not Optuna-tunable, but consistent |
| `engine6.py` line 60 | `_CONSOL_TOLERANCE = 0.08` | Consolidation proximity window (8% below resistance) | OK — not tunable, but stable |
| `engine6.py` line 61 | `_DEDUP_THRESHOLD = 0.005` | Resistance level deduplication (0.5%) | OK — geometric constant |
| `engine6.py` line 87 | `_gap_pct` fallback `= 0.042` | Default gap ceiling when `params` is None (legacy mode) | RISK — diverges from `params.brk_gap_pct = 0.01021` if engine6 is ever called without params in live path. Actual live path always passes `_LIVE_PARAMS`, so this is only a legacy/test risk |
| `engine5.py` line 150 | `3.5 × latr` | Darvas box tightness gate (box height ≤ 3.5 ATR) | OK — not Optuna-tunable, defines pattern |
| `engine5.py` line 154 | `ceiling - 0.5 × latr` | Ceiling touch threshold | OK — geometric, sensible |
| `engine5.py` line 328 | `min(0.45, atr_pct × 10)` | Max cup depth ceiling | OK — ATR-proportional, sensible |
| `engine5.py` line 332 | `25` bars | Min peak-to-low duration for cup | OK — pattern definition constant |
| `engine2.py` line 903 | `a > 0.005` | Parabola coefficient threshold for U-shape | OK — geometric, stable |
| `engine2.py` line 84–85` | `lows[k] < tl_val × 0.99` (1% wick tolerance) | Ascending trendline validation | OK — geometric tolerance |
| `engine2.py` line 447 | `PROXIMITY_PCT = 0.015` | 1.5% proximity in `scan_near_breakout()` | OK — watchlist only, no trade impact |
| `backtest_engine.py` line 74 | `WARMUP_BARS = 252` | Historical warmup bars before backtest start | OK — technical constant |
| `backtest_engine.py` line 75 | `ZONE_RECOMPUTE_N = 5` | KDE zone recompute frequency | OK — performance optimization |
| `backtest_engine.py` line 133–141 | `_SIGNAL_BASE_SCORES` dict | Base scores for non-pullback signals (VCP=6.0, RES_BREAKOUT=6.0, etc.) | RISK — these scores feed into `final_score = raw_score × weight`. If an engine does not emit `_raw_score`, the hardcoded base score is used. Engine6 always emits `_raw_score`; VCP/HTF/LCE use the dict. VCP in scored mode runs only as a booster, but if it becomes standalone again the base score 6.0 × 1.724 = 10.3 would always exceed threshold |
| `filters.py` line 91–92 | `_BACKTEST_REGIME_AGGRESSIVE = 42`, `_BACKTEST_REGIME_SELECTIVE = 24` | Backtest regime thresholds | RISK (minor) — these are derived from the live 100-pt thresholds proportionally (70×60/100, 40×60/100). If `REGIME_AGGRESSIVE_THRESHOLD` or `REGIME_SELECTIVE_THRESHOLD` is updated in constants.py, these two hardcoded values in filters.py will NOT update automatically. They are not derived at runtime |
| `backtest_engine.py` line 55–60 | `_TRAIL_ATR_BY_SETUP` dict | Trail multipliers for VCP (2.0), PULLBACK (3.0) | RISK — VCP and PULLBACK trail multipliers are read from constants.py at module load via lambda, but are **not** Optuna-tunable through BacktestParams. Only RES_BREAKOUT and BASE have `params.brk_trail_mult`/`params.base_trail_mult` |
| `engine3.py` line 37 | `RS_REJECT_THRESHOLD = -0.01219` | Module-level RS floor for legacy pullback functions | RISK (minor) — this value is from V4 Optuna (trial #951) and is separate from `BacktestParams.rs_threshold = 0.066`. The scored path bypasses this constant entirely, using the BacktestParams value. The relaxed fallback in live scanner uses this constant. The two values are intentionally different (see existing docs/system_config_2026-03-15.md section on dual RS thresholds) |

---

## 7. System Behavior Summary

### When to Enter

On each bar T, the system first checks a cascade of pre-conditions before any engine runs. The bar is skipped if: the regime is DEFENSIVE (all engines blocked) or if there are already 5 open positions (`MAX_OPEN_POSITIONS`) or if the ticker fails the liquidity gate (50d median volume < 750K or dollar volume < $25M) or if an earnings announcement is within 7 days or if cooldown_days (4) has not elapsed since the last closed trade. In scored mode, the bar is also skipped if `rs_score < params.rs_threshold (0.066)`. If all pre-checks pass, the appropriate engine runs on `df.iloc[:T+1]` (no lookahead). The detected setup's raw_score is multiplied by a setup-type weight (`pullback_weight=1.842`, `breakout_weight=1.724`, or `base_weight=3.895`) to produce `final_score`. If `final_score < score_threshold (2.50)` the signal is discarded. For RES_BREAKOUT, there is an additional regime gate: `brk_aggressive_only=True` blocks BRK signals in any SELECTIVE regime bar even if the score passes. For pullbacks, a VCP co-signal on the same bar adds `vcp_bonus=1.370` to the raw_score before weighting. If the signal survives all gates, entry is scheduled at the T+1 open price. A gap-chase check fires for RES_BREAKOUT: if the T+1 open is already more than `brk_gap_pct (1.021%)` above the resistance zone, the signal is cancelled.

### When to Exit

Every open trade is evaluated on each bar before new signals are detected. The stop is checked first: if bar low touches or crosses the trailing stop, the trade closes at the stop price ("STOP"). If not stopped, the target is checked: if bar high reaches the take_profit, the trade closes at target price ("TARGET"). The take_profit is always `entry + tp_multiple (4.3458) × risk`. If neither exit fires and the trade is profitable (close > entry), the trailing stop ratchets upward to `max(EMA20, close − mult × ATR14)` — it never moves down. The trail multiplier differs by setup: 2.0 ATR for VCP (tight), 3.0 ATR for PULLBACK (moderate), 6.906 ATR for RES_BREAKOUT (wide), 6.995 ATR for BASE (wide). Any trade still open at `end_date` is force-closed at that day's closing price ("EOD").

### When Not to Trade

The system blocks all new entries in six categories. Regime: DEFENSIVE regime (SPY score < 59 in 7-factor live scoring, < 24 in 4-factor backtest scoring) halts E2, E3 and E6 entirely; SELECTIVE additionally halts E6 breakouts (`brk_aggressive_only=True`). Score quality: pullback final_score < 2.50, or unified live score < 70 (`MIN_SETUP_SCORE`). RS quality: stock RS score < 0.066 (`rs_threshold`) bars the ticker from all scored signal detection; the separate module-level `RS_REJECT_THRESHOLD=-0.01219` bars the legacy scan paths from persistent underperformers. Concurrency: more than 5 positions are already open. Liquidity: 50-day median volume < 750K shares or dollar volume < $25M. Cooldown: within 4 calendar days of the most recent closed trade on the same ticker (scored mode only). Earnings: signal date within 7 calendar days before any known earnings release. Pattern-specific: each engine has hard gates (trend, contraction depth, structural support, etc.) that must pass regardless of regime or score — a signal that fails these geometric gates never reaches the scoring layer.
