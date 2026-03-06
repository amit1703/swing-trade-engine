# Phase 2 Architecture Upgrade — Tasks 2, 3, 4, 12, 13, 14

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Multi-factor market regime scoring, structural pullback enforcement, wider ATR stop loss, weekly timeframe confirmation, ATR contraction detection, and Minervini volume dry-up.

**Architecture:** Engine 0 replaces the binary EMA check with a 7-factor scoring system (0–100). Breadth and 52-week H/L metrics are computed from the bulk-prefetch cache in `main.py` and passed to engine 0 for final scoring. Engine 3 removes the pure-EMA path; all pullbacks now require structural support (KDE zone, prior consolidation low, or demand zone). Engine 2 gains ATR contraction, explicit volume dry-up, and weekly confirmation. All stop-loss calculations use `ATR_STOP_MULTIPLIER` from constants.

**Tech Stack:** Python 3.10, pandas, numpy, yfinance, scipy

---

## Task A — Update constants.py

**Files:**
- Modify: `backend/constants.py`

### Step 1: Change ATR stop multiplier and add new constants

In `backend/constants.py`, find the Risk Management section and update:

```python
# ── Risk Management & Stop Loss ────────────────────────────────────────────
ATR_STOP_MULTIPLIER = 0.8          # ATR × multiplier below swing low (was 0.2 — widened to prevent stop hunts)
ENTRY_PRICE_MULTIPLIER = 1.001     # 0.1% above current price for entry orders
MIN_RISK_REWARD_RATIO = 1.0        # Minimum acceptable R:R ratio for setups
TARGET_RR             = 2.0        # Default take-profit multiplier

# ── VCP Volatility Contraction (Task 13) ───────────────────────────────────
VCP_ATR_CONTRACTION_THRESHOLD = 0.6   # ATR today < ATR20_avg × 0.6 confirms compression

# ── Market Regime Scoring Weights (Task 2) ─────────────────────────────────
REGIME_WEIGHT_EMA20   = 20   # SPY close > EMA20
REGIME_WEIGHT_SMA50   = 15   # SPY close > SMA50
REGIME_WEIGHT_MA_STACK = 15  # SMA50 > SMA200
REGIME_WEIGHT_SLOPE    = 10  # EMA20 slope over 5 days
REGIME_WEIGHT_BREADTH  = 20  # % universe above SMA50
REGIME_WEIGHT_HL       = 10  # New 52-week highs vs lows ratio
REGIME_WEIGHT_VIX      = 10  # VIX below its 20-day SMA

REGIME_AGGRESSIVE_THRESHOLD = 70   # 70–100 = AGGRESSIVE
REGIME_SELECTIVE_THRESHOLD  = 40   # 40–69  = SELECTIVE
                                    # 0–39   = DEFENSIVE (Engines 2 & 3 disabled)
```

### Step 2: Verify no tests break

Run:
```bash
cd backend && python -c "from constants import ATR_STOP_MULTIPLIER, VCP_ATR_CONTRACTION_THRESHOLD; print(ATR_STOP_MULTIPLIER, VCP_ATR_CONTRACTION_THRESHOLD)"
```
Expected: `0.8 0.6`

### Step 3: Commit
```bash
git add backend/constants.py
git commit -m "feat(constants): widen ATR stop to 0.8, add regime weights + VCP contraction threshold"
```

---

## Task B — Rewrite engine0.py (Task 2: Multi-Factor Regime Score)

**Files:**
- Modify: `backend/engines/engine0.py`

### Step 1: Understand the target output

The new `check_market_regime()` signature:
```python
def check_market_regime(
    breadth_pct: float = 0.5,   # fraction of universe above SMA50 (0.0–1.0)
    hl_ratio: float = 0.5,      # new_highs / (new_highs + new_lows + 1)
) -> Dict:
```

Returns:
```python
{
    "is_bullish": bool,       # regime_score >= REGIME_SELECTIVE_THRESHOLD
    "regime_score": int,      # 0–100
    "regime": str,            # "AGGRESSIVE" | "SELECTIVE" | "DEFENSIVE" | "ERROR:..."
    "spy_close": float,
    "spy_20ema": float,
    "spy_sma50": float,
    "spy_sma200": float,
    "vix": float,
    "vix_sma20": float,
    "factors": dict,          # per-factor breakdown for logging/debugging
}
```

### Step 2: Write the full engine0.py replacement

Replace `backend/engines/engine0.py` entirely:

```python
"""
Engine 0: Institutional Market Regime Engine (Task 2)
══════════════════════════════════════════════════════
Multi-factor regime scoring system (0–100).

Factor weights (total = 100):
  1. SPY Close > EMA20          → 20 pts  (momentum gate)
  2. SPY Close > SMA50          → 15 pts  (intermediate trend)
  3. SMA50 > SMA200             → 15 pts  (MA stack — Stage 2 market)
  4. EMA20 slope (5-day)        → 10 pts  (trend acceleration)
  5. % universe above SMA50     → 20 pts  (breadth — passed from main.py)
  6. 52-week H/L ratio          → 10 pts  (breadth quality — passed from main.py)
  7. VIX < VIX SMA20            → 10 pts  (fear gauge)

Regime zones:
  70–100  →  AGGRESSIVE  (full engine suite enabled)
  40–69   →  SELECTIVE   (engines enabled, size conservatively)
  0–39    →  DEFENSIVE   (Engines 2 & 3 disabled)
"""

from typing import Dict

import numpy as np
import pandas as pd
import yfinance as yf

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from indicators import ema as _ema, sma as _sma
from constants import (
    REGIME_WEIGHT_EMA20,
    REGIME_WEIGHT_SMA50,
    REGIME_WEIGHT_MA_STACK,
    REGIME_WEIGHT_SLOPE,
    REGIME_WEIGHT_BREADTH,
    REGIME_WEIGHT_HL,
    REGIME_WEIGHT_VIX,
    REGIME_AGGRESSIVE_THRESHOLD,
    REGIME_SELECTIVE_THRESHOLD,
)


def check_market_regime(
    breadth_pct: float = 0.5,
    hl_ratio: float = 0.5,
) -> Dict:
    """
    Fetch SPY (1y) + VIX (3mo) data and compute a 7-factor regime score.

    Parameters
    ----------
    breadth_pct : float
        Fraction of the scan universe whose daily close is above SMA50.
        Computed by main.py from the bulk-prefetch cache and passed here.
        Default 0.5 (neutral) when called before prefetch.
    hl_ratio : float
        new_highs / (new_highs + new_lows + 1) across the scan universe.
        Default 0.5 (neutral).

    Returns
    -------
    dict
        is_bullish    : bool   — regime_score >= REGIME_SELECTIVE_THRESHOLD
        regime_score  : int    — 0–100
        regime        : str    — "AGGRESSIVE" | "SELECTIVE" | "DEFENSIVE"
        spy_close     : float
        spy_20ema     : float
        spy_sma50     : float
        spy_sma200    : float
        vix           : float  (0.0 on fetch failure)
        vix_sma20     : float
        factors       : dict   — per-factor point breakdown
    """
    try:
        # ── Fetch SPY 1y daily data ───────────────────────────────────────────
        spy = yf.download(
            "SPY",
            period="1y",
            interval="1d",
            auto_adjust=False,
            prepost=False,
            progress=False,
            threads=False,
        )

        if spy is None or spy.empty:
            return _error("No SPY data returned from yfinance")

        if isinstance(spy.columns, pd.MultiIndex):
            spy.columns = spy.columns.get_level_values(0)

        close_col = "Adj Close" if "Adj Close" in spy.columns else "Close"
        close = spy[close_col].dropna()

        if len(close) < 22:
            return _error(f"Insufficient SPY data: {len(close)} bars (need 22)")

        # ── Compute SPY indicators ────────────────────────────────────────────
        ema20_s  = _ema(close, 20)
        sma50_s  = _sma(close, 50)
        sma200_s = _sma(close, 200)

        def _fv(s) -> float:
            v = s.iloc[-1]
            f = float(v.item() if hasattr(v, "item") else v)
            return 0.0 if f != f else f  # NaN → 0.0

        lc      = _fv(close)
        l_ema20 = _fv(ema20_s)
        l_sma50 = _fv(sma50_s)
        l_sma200 = _fv(sma200_s)

        if lc <= 0 or l_ema20 <= 0:
            return _error("SPY price or EMA20 is zero/NaN")

        # ── EMA20 slope over last 5 bars ──────────────────────────────────────
        ema20_clean = ema20_s.dropna()
        slope_score = 0
        if len(ema20_clean) >= 6:
            old = float(ema20_clean.iloc[-6])
            new = float(ema20_clean.iloc[-1])
            if old > 0:
                pct_slope = (new - old) / old  # e.g. +0.005 = rising 0.5%/5d
                # Linear scale: ≥+0.5% → full 10pts; ≤-0.5% → 0pts
                slope_score = int(min(10, max(0, (pct_slope + 0.005) / 0.01 * 10)))

        # ── Factor 1–4 scores ─────────────────────────────────────────────────
        f1 = REGIME_WEIGHT_EMA20   if lc > l_ema20  else 0
        f2 = REGIME_WEIGHT_SMA50   if lc > l_sma50  else 0
        f3 = REGIME_WEIGHT_MA_STACK if (l_sma50 > 0 and l_sma200 > 0 and l_sma50 > l_sma200) else 0
        f4 = slope_score  # 0–10

        # ── VIX fetch (Factor 7) ──────────────────────────────────────────────
        vix_close = 0.0
        vix_sma20 = 0.0
        f7 = 0
        try:
            vix_df = yf.download(
                "^VIX",
                period="3mo",
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            if vix_df is not None and not vix_df.empty:
                if isinstance(vix_df.columns, pd.MultiIndex):
                    vix_df.columns = vix_df.columns.get_level_values(0)
                vc = vix_df["Close"].dropna() if "Close" in vix_df.columns else pd.Series(dtype=float)
                if len(vc) >= 20:
                    vix_close = float(vc.iloc[-1])
                    vix_sma20 = float(vc.rolling(20).mean().iloc[-1])
                    if vix_close > 0 and vix_sma20 > 0 and vix_close < vix_sma20:
                        f7 = REGIME_WEIGHT_VIX
        except Exception:
            pass  # VIX failure is non-fatal — factor 7 scores 0

        # ── Factor 5 (breadth) and 6 (H/L ratio) ─────────────────────────────
        # breadth_pct = 0.0 → all below SMA50 (max bearish) → 0 pts
        # breadth_pct = 1.0 → all above SMA50 (max bullish) → REGIME_WEIGHT_BREADTH pts
        f5 = int(round(min(breadth_pct, 1.0) * REGIME_WEIGHT_BREADTH))

        # hl_ratio = 0.0 → all new lows → 0 pts
        # hl_ratio = 1.0 → all new highs → REGIME_WEIGHT_HL pts
        f6 = int(round(min(hl_ratio, 1.0) * REGIME_WEIGHT_HL))

        regime_score = f1 + f2 + f3 + f4 + f5 + f6 + f7

        regime = _score_to_regime(regime_score)
        is_bullish = regime_score >= REGIME_SELECTIVE_THRESHOLD

        return {
            "is_bullish":   is_bullish,
            "regime_score": regime_score,
            "regime":       regime,
            "spy_close":    round(lc, 2),
            "spy_20ema":    round(l_ema20, 2),
            "spy_sma50":    round(l_sma50, 2),
            "spy_sma200":   round(l_sma200, 2),
            "vix":          round(vix_close, 2),
            "vix_sma20":    round(vix_sma20, 2),
            "breadth_pct":  round(breadth_pct, 3),
            "hl_ratio":     round(hl_ratio, 3),
            "factors": {
                "f1_ema20":   f1,
                "f2_sma50":   f2,
                "f3_ma_stack": f3,
                "f4_slope":   f4,
                "f5_breadth": f5,
                "f6_hl_ratio": f6,
                "f7_vix":     f7,
            },
        }

    except Exception as exc:
        return _error(str(exc)[:120])


def _score_to_regime(score: int) -> str:
    if score >= REGIME_AGGRESSIVE_THRESHOLD:
        return "AGGRESSIVE"
    if score >= REGIME_SELECTIVE_THRESHOLD:
        return "SELECTIVE"
    return "DEFENSIVE"


def _error(msg: str) -> Dict:
    return {
        "is_bullish":   False,
        "regime_score": 0,
        "regime":       f"ERROR: {msg}",
        "spy_close":    0.0,
        "spy_20ema":    0.0,
        "spy_sma50":    0.0,
        "spy_sma200":   0.0,
        "vix":          0.0,
        "vix_sma20":    0.0,
        "breadth_pct":  0.5,
        "hl_ratio":     0.5,
        "factors":      {},
    }
```

### Step 3: Verify syntax
```bash
cd backend && python -c "import py_compile; py_compile.compile('engines/engine0.py', doraise=True); print('OK')"
```
Expected: `OK`

### Step 4: Commit
```bash
git add backend/engines/engine0.py
git commit -m "feat(engine0): multi-factor regime scoring 0-100 (AGGRESSIVE/SELECTIVE/DEFENSIVE)"
```

---

## Task C — Wire breadth calculation in main.py (Task 2 continued)

**Files:**
- Modify: `backend/main.py`

### Step 1: Add `compute_universe_breadth()` helper to main.py

After the `_inject_hot_sector` function (around line 1245), add:

```python
def compute_universe_breadth(
    ticker_cache: dict,
    tickers: List[str],
    sample_size: int = 200,
) -> tuple:
    """
    Compute two breadth metrics from the bulk-prefetch cache.

    Returns
    -------
    (breadth_pct, hl_ratio) : tuple[float, float]
        breadth_pct : fraction of sampled tickers where close > SMA50 (0.0–1.0)
        hl_ratio    : new_highs / (new_highs + new_lows + 1)   (0.0–1.0)
    """
    candidates = [t for t in tickers if t in ticker_cache and ticker_cache[t][1] is not None]
    sample = candidates[:sample_size]
    if not sample:
        return 0.5, 0.5

    above_50 = new_highs = new_lows = total = 0

    for t in sample:
        _, df = ticker_cache[t]
        if df is None or len(df) < 52:
            continue
        try:
            adj = "Adj Close" if "Adj Close" in df.columns else "Close"
            close = df[adj].dropna()
            if len(close) < 52:
                continue
            lc = float(close.iloc[-1])
            sma50_val = close.rolling(50).mean().iloc[-1]
            if not pd.isna(sma50_val) and lc > float(sma50_val):
                above_50 += 1
            lookback = min(252, len(close))
            h52 = float(close.iloc[-lookback:].max())
            l52 = float(close.iloc[-lookback:].min())
            if lc >= h52 * 0.97:
                new_highs += 1
            elif lc <= l52 * 1.03:
                new_lows += 1
            total += 1
        except Exception:
            pass

    if total == 0:
        return 0.5, 0.5

    breadth_pct = above_50 / total
    hl_ratio    = new_highs / (new_highs + new_lows + 1)
    return round(breadth_pct, 3), round(hl_ratio, 3)
```

### Step 2: Restructure scan flow in `_run_scan()` to call breadth after prefetch

The existing flow is:
```
Engine 0 → if bearish early exit → SPY fetch → bulk prefetch → per-ticker
```

The new flow is:
```
SPY fetch → bulk prefetch → compute breadth → Engine 0 (full score) → per-ticker gating
```

Find the Engine 0 call in `_run_scan()`:
```python
regime_start = time.time()
regime = await loop.run_in_executor(None, check_market_regime)
```

Replace it with a deferred call (move it to AFTER the prefetch). Specifically:

**a)** Delete the early Engine 0 call and early-exit block (the `if not regime["is_bullish"]...` check).

**b)** After the bulk prefetch block and the earnings cache load, add:

```python
        # ── Engine 0: Multi-factor regime (computed after prefetch for breadth) ──
        regime_start = time.time()
        breadth_pct, hl_ratio = compute_universe_breadth(_ticker_cache, tickers)
        log.info(
            "Breadth: %.1f%% above SMA50  H/L ratio: %.2f",
            breadth_pct * 100, hl_ratio,
        )
        regime = await loop.run_in_executor(
            None, check_market_regime, breadth_pct, hl_ratio
        )
        regime_time = time.time() - regime_start
        if not dry_run:
            await save_regime(DB_PATH, scan_ts, regime)
        log.info(
            "Engine 0: %s  score=%d  (SPY=%.2f  EMA20=%.2f  SMA50=%.2f)  "
            "breadth=%.1f%%  VIX=%.1f  [%.1fs]",
            regime["regime"],
            regime["regime_score"],
            regime["spy_close"],
            regime["spy_20ema"],
            regime["spy_sma50"],
            breadth_pct * 100,
            regime["vix"],
            regime_time,
        )
        _scan_state["engine_stats"]["e0"] = {
            "spy_close":    round(regime["spy_close"], 2),
            "spy_ema20":    round(regime["spy_20ema"], 2),
            "regime_score": regime["regime_score"],
            "is_bullish":   regime["is_bullish"],
            "duration_s":   round(regime_time, 1),
            "factors":      regime.get("factors", {}),
        }
        _scan_state["engine_stats"]["timing"]["regime_s"] = round(regime_time, 2)

        if not regime["is_bullish"] and not force:
            log.info(
                "Regime DEFENSIVE (score=%d < %d) — Engines 2 & 3 disabled",
                regime["regime_score"], REGIME_SELECTIVE_THRESHOLD,
            )
```

**c)** Remove the old engine 0 stat update block (the one that previously set `_scan_state["engine_stats"]["e0"]`).

**d)** Add `REGIME_SELECTIVE_THRESHOLD` to the constants import at the top of main.py.

### Step 3: Update the existing early-exit guard in _process()

The existing code gates engines 2/3 at the scan level (early return from `_run_scan()`). Now that regime is computed after prefetch, the early return still works — it just happens after the prefetch instead of before. No changes needed inside `_process()`.

### Step 4: Verify the import chain works
```bash
cd backend && python -c "
from engines.engine0 import check_market_regime
r = check_market_regime(breadth_pct=0.6, hl_ratio=0.7)
print(r['regime'], r['regime_score'])
assert 'regime_score' in r
assert 'factors' in r
print('Engine 0 import OK')
"
```

### Step 5: Commit
```bash
git add backend/main.py
git commit -m "feat(main): compute universe breadth after prefetch, pass to engine0 regime scorer"
```

---

## Task D — Update engine3.py (Task 3: Structural Pullback + Task 4: ATR Stop)

**Files:**
- Modify: `backend/engines/engine3.py`
- Modify: `backend/main.py` (remove scan_ema_pullback import + call)

### Step 1: Update the engine3.py imports and add structural support helpers

At the top of `backend/engines/engine3.py`, update the constants import:
```python
from constants import (
    CCI_STRICT_FLOOR, CCI_RLX_FLOOR, TARGET_RR,
    TRENDLINE_TOUCH_TOLERANCE_PCT, ATR_STOP_MULTIPLIER,
)
```

### Step 2: Add `_find_structural_support()` helper

Add before the `scan_pullback` function:

```python
def _find_structural_support(
    ll: float,
    lc: float,
    sr_zones: List[Dict],
    trendline: Optional[Dict],
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    avg_vol: float,
) -> Optional[Dict]:
    """
    Find the nearest structural support for a pullback.

    Checks three layers (in priority order):
      1. KDE SUPPORT zone (Engine 1 horizontal zone)
      2. Prior consolidation low (recent swing low where price bounced ≥3 bars)
      3. High-volume demand zone (reversal bar with volume ≥150% avg)
      4. Ascending trendline touch

    Returns a dict with keys: level, lower, upper, source
    Returns None if no structural support found.
    """
    ZONE_TOLERANCE = 0.025  # 2.5% zone width tolerance

    # ── 1. KDE support zone ───────────────────────────────────────────────────
    support_zones = [z for z in sr_zones if z.get("type") == "SUPPORT"]
    for z in support_zones:
        low_in_zone   = z["lower"] * (1 - ZONE_TOLERANCE) <= ll <= z["upper"] * (1 + ZONE_TOLERANCE)
        close_in_zone = z["lower"] <= lc <= z["upper"]
        if low_in_zone or close_in_zone:
            return {
                "level":  z["level"],
                "lower":  z["lower"],
                "upper":  z["upper"],
                "source": "KDE",
            }

    # ── 2. Prior consolidation low ────────────────────────────────────────────
    # Look back up to 60 bars; find local lows where price held ≥3 bars before moving up.
    if len(low) >= 15:
        low_vals = low.values[-60:] if len(low) >= 60 else low.values
        for i in range(len(low_vals) - 8, 3, -1):
            candidate = float(low_vals[i])
            if candidate <= 0:
                continue
            # Must be a local minimum vs surrounding 3 bars
            if not (candidate <= min(low_vals[max(0, i-3):i])
                    and candidate <= min(low_vals[i+1:min(len(low_vals), i+4)])):
                continue
            # Price must have bounced: at least 3 of the next 5 bars closed above candidate
            bounced = sum(
                1 for j in range(i + 1, min(len(low_vals), i + 6))
                if float(low_vals[j]) > candidate * 1.005
            )
            if bounced < 3:
                continue
            # Candidate must be within 3% of current bar's low
            if abs(ll - candidate) / candidate > 0.03:
                continue
            return {
                "level":  round(candidate, 4),
                "lower":  round(candidate * 0.99, 4),
                "upper":  round(candidate * 1.01, 4),
                "source": "CONSOLIDATION_LOW",
            }

    # ── 3. High-volume demand zone ────────────────────────────────────────────
    # A bullish reversal bar (close > open) with volume ≥ 150% avg, within last 30 bars.
    if avg_vol > 0 and len(close) >= 10 and len(low) >= 10:
        lookback = min(30, len(close))
        close_vals  = close.values[-lookback:]
        low_vals    = low.values[-lookback:]
        high_vals   = high.values[-lookback:]
        vol_vals    = volume.values[-lookback:] if len(volume) >= lookback else None

        if vol_vals is not None:
            for i in range(len(close_vals) - 2, 1, -1):  # skip last bar (current)
                bar_vol = float(vol_vals[i])
                if bar_vol < 1.5 * avg_vol:
                    continue
                bar_close = float(close_vals[i])
                bar_low   = float(low_vals[i])
                bar_high  = float(high_vals[i])
                # Must be a bullish reversal bar
                if i == 0:
                    continue
                bar_open = float(close_vals[i - 1])  # approximate open with prev close
                if bar_close <= bar_open:
                    continue
                # Current low must be near this demand zone
                if abs(ll - bar_low) / bar_low > 0.03:
                    continue
                # Price must have held above this zone since
                held = all(
                    float(low_vals[j]) >= bar_low * 0.98
                    for j in range(i + 1, len(low_vals))
                )
                if not held:
                    continue
                return {
                    "level":  round(bar_low, 4),
                    "lower":  round(bar_low * 0.99, 4),
                    "upper":  round(bar_high, 4),
                    "source": "DEMAND_ZONE",
                }

    # ── 4. Ascending trendline ────────────────────────────────────────────────
    if trendline is not None:
        ascending_tl = trendline.get("ascending")
        if ascending_tl is not None:
            touched, tl_value = _check_ascending_trendline_touch(ll, ascending_tl)
            if touched and tl_value > 0:
                return {
                    "level":  round(tl_value, 4),
                    "lower":  round(tl_value * 0.99, 4),
                    "upper":  round(tl_value * 1.01, 4),
                    "source": "ASCENDING_TDL",
                }

    return None
```

### Step 3: Update `scan_pullback()` to use `_find_structural_support()` and `ATR_STOP_MULTIPLIER`

Replace the support zone detection block (steps 3a and 3b) inside `scan_pullback()`:

Old code (lines ~126–164):
```python
        # ── 3a. Engine 1 support zone touch (HORIZONTAL) ───────────────────
        support_zones = [z for z in sr_zones if z["type"] == "SUPPORT"]
        nearest_sup = None
        ...
        # ── 3b. Ascending trendline touch ───────────────────────────────────
        ...
        if nearest_sup is None:
            ...
            return None
```

New code:
```python
        # ── 3. Structural support (KDE zone / consolidation low / demand zone / TDL) ──
        vol_sma50   = ind.volume.rolling(50).mean()
        vsm_val     = vol_sma50.iloc[-1]
        avg_vol_sup = float(vsm_val.item() if hasattr(vsm_val, "item") else vsm_val)

        nearest_sup = _find_structural_support(
            ll, lc, sr_zones, trendline,
            ind.high, ind.low, ind.close, ind.volume, avg_vol_sup,
        )
        if nearest_sup is None:
            if debug:
                print(
                    f"Engine 3 Pullback: REJECTED - No structural support "
                    f"(no KDE zone, consolidation low, demand zone, or ascending TDL near low={ll:.2f})"
                )
            return None

        is_ascending_tdl = nearest_sup["source"] == "ASCENDING_TDL"
        ascending_tl_value = nearest_sup["level"] if is_ascending_tdl else 0.0
```

Also update the stop loss formula inside `scan_pullback()`:
```python
        # Old: stop_loss = round(stop_base - 0.2 * latr, 2)
        stop_base = min(ll, nearest_sup["lower"])
        stop_loss = round(stop_base - ATR_STOP_MULTIPLIER * latr, 2)
```

And update the return dict to include the support source:
```python
        return {
            ...
            "support_level":  nearest_sup["level"],
            "support_source": nearest_sup["source"],   # NEW
            "is_ascending_tdl": is_ascending_tdl,
            ...
        }
```

### Step 4: Update `scan_relaxed_pullback()` similarly

Replace the support zone detection block with `_find_structural_support()` call (same as Step 3).

Update stop loss:
```python
        stop_base = min(ll, nearest_sup["lower"])
        stop_loss = round(stop_base - ATR_STOP_MULTIPLIER * latr, 2)
```

Add `support_source` to return dict.

### Step 5: DELETE `scan_ema_pullback()` entirely

Remove the entire `scan_ema_pullback()` function (lines 386–520 in the original file).

### Step 6: Remove `scan_ema_pullback` from main.py

In `backend/main.py`:

a) Update the import:
```python
# Old:
from engines.engine3 import scan_pullback, scan_relaxed_pullback, scan_ema_pullback
# New:
from engines.engine3 import scan_pullback, scan_relaxed_pullback
```

b) Delete the EMA pullback block in `_process()`:
```python
# DELETE this entire block:
                        else:
                            # Pure EMA path: no KDE zone required ...
                            try:
                                pb_ema = await loop.run_in_executor(
                                    None, scan_ema_pullback, ticker, df, zones, tl, rs_score
                                )
                                ...
                            except Exception as pb_ema_exc:
                                log.warning("EMA pullback check failed for %s: %s", ticker, pb_ema_exc)
```

c) Remove `"ema": 0` from the `engine_stats["e3"]` dict in both the module-level `_scan_state` and the `_run_scan()` initialization.

### Step 7: Verify syntax
```bash
cd backend && python -c "
import py_compile
py_compile.compile('engines/engine3.py', doraise=True)
py_compile.compile('main.py', doraise=True)
print('OK')
"
```

### Step 8: Commit
```bash
git add backend/engines/engine3.py backend/main.py
git commit -m "feat(engine3): structural pullback enforcement + ATR_STOP_MULTIPLIER + remove EMA-only path"
```

---

## Task E — Update engine2.py (Tasks 4, 12, 13, 14: ATR stop, weekly confirm, contraction, dry-up)

**Files:**
- Modify: `backend/engines/engine2.py`

### Step 1: Update constants import in engine2.py

```python
from constants import TARGET_RR, ATR_STOP_MULTIPLIER, VCP_ATR_CONTRACTION_THRESHOLD
```

### Step 2: Add `_weekly_confirmed()` helper (Task 12)

Add before `scan_vcp()`:

```python
def _weekly_confirmed(df: pd.DataFrame) -> bool:
    """
    Task 12: Multi-timeframe confirmation.

    Resamples daily OHLCV to weekly (week-ending Friday) and checks:
      • Weekly EMA8 > Weekly EMA20
      • Weekly Close > Weekly EMA20  (price above short-term weekly trend)

    Returns True when both conditions hold on the most recent complete week.
    Returns False on any data error (fail open — do not block setups).
    """
    try:
        data = _prep(df)
        if data is None or len(data) < 40:
            return False

        adj  = _adj_col(data)
        wkly = data.resample("W-FRI").agg({
            adj:    "last",
            "High": "max",
            "Low":  "min",
        }).dropna()

        if len(wkly) < 22:
            return False

        wc      = wkly[adj]
        w_ema8  = _ema(wc, 8)
        w_ema20 = _ema(wc, 20)

        if w_ema8.dropna().empty or w_ema20.dropna().empty:
            return False

        we8  = float(w_ema8.iloc[-1])
        we20 = float(w_ema20.iloc[-1])
        wlc  = float(wc.iloc[-1])

        if any(v != v for v in [we8, we20, wlc]):  # NaN check
            return False

        return we8 > we20 and wlc > we20

    except Exception:
        return False  # fail open
```

### Step 3: Replace all `0.2 * latr` stop-loss calculations with `ATR_STOP_MULTIPLIER * latr`

In `scan_vcp()`, find all occurrences of:
```python
stop_loss  = round(stop_base - 0.2 * latr, 2)
```
Replace with:
```python
stop_loss  = round(stop_base - ATR_STOP_MULTIPLIER * latr, 2)
```

There are occurrences in:
- Path B (confirmed breakout)
- Path C (trendline breakout)
- Path D (KDE breakout)
- Path E (RS lead)
- Path A (DRY coiled spring)

Run:
```bash
grep -n "0.2 \* latr" backend/engines/engine2.py
```
and replace all 5 instances.

### Step 4: Add ATR contraction check to Path A (Task 13)

In Path A (DRY), after the existing True Range contraction check (A2):

```python
        # ── A2. True Range contraction (mean TR last 5 < prev 20) ────────────
        if len(tr) < 26:
            ...
            return None

        last5_tr  = ...
        prev20_tr = ...
        if last5_tr >= prev20_tr:
            ...
            return None

        # ── A2b. ATR contraction confirmation (Task 13) ───────────────────────
        # Require today's ATR < 20-bar ATR average × VCP_ATR_CONTRACTION_THRESHOLD
        # This confirms genuine volatility compression, not just a low-TR day.
        atr_today   = float(atr14.iloc[-1].item() if hasattr(atr14.iloc[-1], "item") else atr14.iloc[-1])
        atr20_clean = atr14.dropna()
        atr_compressed = False
        if len(atr20_clean) >= 20:
            atr20_avg = float(atr20_clean.iloc[-20:].mean())
            atr_compressed = atr_today < atr20_avg * VCP_ATR_CONTRACTION_THRESHOLD
            if not atr_compressed:
                if debug:
                    print(
                        f"Engine 2 VCP: REJECTED - ATR not compressed "
                        f"(ATR={atr_today:.4f}, ATR20avg={atr20_avg:.4f}, "
                        f"threshold={atr20_avg * VCP_ATR_CONTRACTION_THRESHOLD:.4f})"
                    )
                return None
        else:
            atr_compressed = False  # insufficient data — let pass-through
```

### Step 5: Add explicit Minervini volume dry-up field (Task 14)

The existing `_has_vol_dryup()` already checks for `volume < 50% avg` in last 10 bars. Add the field to the Path A return dict:

```python
        # ── A4. Volume dry-up ─────────────────────────────────────────────────
        last3_vol = ...
        is_dry = last3_vol < avg_vol and _has_vol_dryup(volume, avg_vol)

        # Task 14: Minervini strict dry-up — any bar in last 5 < 50% avg
        is_minervini_dryup = _has_vol_dryup(volume, avg_vol)
```

### Step 6: Add `weekly_confirmed` and `atr_compressed` + `is_minervini_dryup` to ALL return dicts

**Path A (DRY) return dict** — add:
```python
                    "weekly_confirmed":    _weekly_confirmed(df),
                    "atr_compressed":      atr_compressed,
                    "is_minervini_dryup":  is_minervini_dryup,
```

**Path B (BRK) return dict** — add:
```python
                    "weekly_confirmed":    _weekly_confirmed(df),
                    "atr_compressed":      False,
                    "is_minervini_dryup":  _has_vol_dryup(volume, avg_vol),
```

**Path C (TDL) return dict** — add same as Path B.

**Path D (KDE) return dict** — add same as Path B.

**Path E (RS Lead) return dict** — add same as Path B.

### Step 7: Verify syntax and imports
```bash
cd backend && python -c "
import py_compile
py_compile.compile('engines/engine2.py', doraise=True)
print('OK')
from engines.engine2 import scan_vcp, _weekly_confirmed
print('Imports OK')
"
```

### Step 8: Commit
```bash
git add backend/engines/engine2.py
git commit -m "feat(engine2): ATR_STOP_MULTIPLIER, weekly_confirmed, ATR contraction (Task13), Minervini dry-up (Task14)"
```

---

## Task F — Smoke test the full pipeline (manual)

### Step 1: Start the backend
```bash
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 2: Trigger a dry-run scan on 3 tickers
```bash
curl -X POST "http://localhost:8000/api/run-scan?dry_run=true&tickers=AAPL,MSFT,NVDA"
```

Wait 15 seconds, then:
```bash
curl "http://localhost:8000/api/scan-status" | python -m json.tool
```

### Step 3: Check the regime output
Verify `engine_stats.e0` contains:
- `regime_score` (integer 0–100)
- `is_bullish` (bool)
- `factors` dict with 7 keys

### Step 4: Check VCP setups contain new fields
```bash
curl "http://localhost:8000/api/setups/vcp" | python -m json.tool | grep -E "weekly_confirmed|atr_compressed|is_minervini_dryup"
```

### Step 5: Confirm no `scan_ema_pullback` references remain
```bash
grep -r "scan_ema_pullback\|ema_pullback" backend/
```
Expected: no output (function completely removed).

### Step 6: Commit final verification
```bash
git add -A
git commit -m "chore: phase2 smoke test verified — regime scoring, structural pullback, ATR stop, weekly confirm"
```

---

## Quick Reference: New Fields Added to Setup Dicts

| Field | Engines | Type | Description |
|-------|---------|------|-------------|
| `weekly_confirmed` | VCP, all paths | bool | Weekly EMA8 > EMA20 AND close > EMA20 |
| `atr_compressed` | VCP Path A only | bool | ATR < ATR20avg × 0.6 |
| `is_minervini_dryup` | VCP all paths | bool | Any bar in last 10 < 50% avg vol |
| `support_source` | PULLBACK | str | "KDE" / "CONSOLIDATION_LOW" / "DEMAND_ZONE" / "ASCENDING_TDL" |

## New Regime Output Fields

| Field | Type | Description |
|-------|------|-------------|
| `regime_score` | int 0–100 | Composite score |
| `regime` | str | "AGGRESSIVE" / "SELECTIVE" / "DEFENSIVE" |
| `spy_sma50` | float | SPY SMA50 value |
| `spy_sma200` | float | SPY SMA200 value |
| `vix` | float | Latest VIX close |
| `vix_sma20` | float | VIX 20-day SMA |
| `breadth_pct` | float | % universe above SMA50 |
| `hl_ratio` | float | New highs / (new highs + new lows + 1) |
| `factors` | dict | Per-factor point breakdown |
